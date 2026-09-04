import csv
from io import StringIO
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from dotenv import load_dotenv
from event_ids import realtime_event_id

load_dotenv()

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
DATA_DIR = Path(__file__).parent / "data" / "firms"
LIVE_DATA_PATH = DATA_DIR / "realtime_viirs.csv"
STATUS_PATH = DATA_DIR / "realtime_status.json"
REFRESH_LOCK = threading.Lock()


def _load_facilities():
    import pandas as pd

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return pd.DataFrame(columns=["latitude", "longitude"])
    try:
        from sqlalchemy import create_engine, text

        with create_engine(database_url, pool_pre_ping=True).connect() as connection:
            return pd.read_sql(
                text("SELECT latitude, longitude FROM industrial_facilities"),
                connection,
            )
    except Exception:
        return pd.DataFrame(columns=["latitude", "longitude"])


def _number(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence(value):
    confidence = _number(value)
    return confidence / 100 if confidence > 1 else confidence


def _temporal_groups(rows):
    groups = {}
    for row in rows:
        key = (
            round(_number(row.get("latitude")), 3),
            round(_number(row.get("longitude")), 3),
        )
        timestamp = f'{row.get("acq_date", "")} {str(row.get("acq_time", "")).zfill(4)[:4]}'
        groups.setdefault(key, []).append(timestamp)
    return groups


def _config() -> dict[str, str | int]:
    bbox = os.getenv("NASA_FIRMS_BBOX", "68,6,97,37")
    sources = os.getenv(
        "NASA_FIRMS_SOURCES",
        os.getenv("NASA_FIRMS_SOURCE", "VIIRS_NOAA21_NRT"),
    )
    return {
        "map_key": os.getenv("NASA_FIRMS_MAP_KEY", ""),
        "sources": [source.strip() for source in sources.split(",") if source.strip()],
        "bbox": bbox,
        "days": int(os.getenv("NASA_FIRMS_DAYS", "1")),
        "interval_seconds": int(os.getenv("REALTIME_REFRESH_SECONDS", "900")),
    }


def _read_status() -> dict:
    if not STATUS_PATH.exists():
        config = _config()
        return {
            "configured": bool(config["map_key"]),
            "source": ",".join(config["sources"]),
            "bbox": config["bbox"],
            "last_success": None,
            "last_error": None,
            "fetched_count": 0,
        }
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary_file:
        temporary_file.write(content)
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(path)


def _validate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    valid_rows = []
    for row in rows:
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            valid_rows.append(row)
    return valid_rows


def refresh_realtime_data() -> dict:
    config = _config()
    status = _read_status()
    status.update(
        configured=bool(config["map_key"]),
        source=", ".join(config["sources"]),
        bbox=config["bbox"],
    )

    if not config["map_key"]:
        status["last_error"] = "NASA_FIRMS_MAP_KEY is not configured"
        _write_atomic(STATUS_PATH, json.dumps(status, indent=2))
        raise RuntimeError(status["last_error"])

    if not 1 <= config["days"] <= 5:
        raise ValueError("NASA_FIRMS_DAYS must be between 1 and 5")

    with REFRESH_LOCK:
        rows = []
        errors = []
        for source in config["sources"]:
            url = (
                f"{BASE_URL}/{config['map_key']}/{source}/"
                f"{config['bbox']}/{config['days']}"
            )
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                rows.extend(csv.DictReader(response.text.splitlines()))
            except requests.RequestException as error:
                errors.append(f"{source}: {error}")

        rows = _validate_rows(rows)
        unique_rows = {}
        for row in rows:
            key = tuple(row.get(column, "") for column in (
                "latitude", "longitude", "acq_date", "acq_time", "satellite"
            ))
            unique_rows[key] = row
        rows = list(unique_rows.values())
        if not rows and errors:
            raise RuntimeError("; ".join(errors))
        fieldnames = []
        for row in rows:
            for fieldname in row:
                if fieldname not in fieldnames:
                    fieldnames.append(fieldname)
        csv_content = ""
        if fieldnames:
            csv_buffer = StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            csv_content = csv_buffer.getvalue()
        _write_atomic(LIVE_DATA_PATH, csv_content)

        status.update(
            last_success=datetime.now(timezone.utc).isoformat(),
            last_error="; ".join(errors) if errors else None,
            fetched_count=len(rows),
        )
        _write_atomic(STATUS_PATH, json.dumps(status, indent=2))
        try:
            get_realtime_events()
        except Exception as error:
            status["last_error"] = f"Prediction refresh failed: {error}"
            _write_atomic(STATUS_PATH, json.dumps(status, indent=2))
    return status


def get_realtime_status() -> dict:
    status = _read_status()
    last_success = status.get("last_success")
    status["stale"] = True
    if last_success:
        age_seconds = (
            datetime.now(timezone.utc) - datetime.fromisoformat(last_success)
        ).total_seconds()
        status["age_seconds"] = max(0, round(age_seconds))
        status["stale"] = age_seconds > _config()["interval_seconds"] * 2
    else:
        status["age_seconds"] = None
    return status


def get_realtime_events() -> list[dict]:
    if not LIVE_DATA_PATH.exists():
        return []
    from feature_engineering.landcover import calculate_landcover_features
    from feature_engineering.spatial import calculate_spatial_features
    from ml.inference.service import predict_and_persist
    from persistence.detector import calculate_persistence, calculate_persistence_score

    with LIVE_DATA_PATH.open(newline="", encoding="utf-8") as data_file:
        candidates = []
        rows = list(csv.DictReader(data_file))
        facilities = _load_facilities()
        temporal_groups = _temporal_groups(rows)
        for row in rows:
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                frp = float(row.get("frp", 0) or 0)
            except (TypeError, ValueError):
                frp = 0
            event_id = realtime_event_id(row)
            spatial = calculate_spatial_features(
                {"latitude": latitude, "longitude": longitude}, facilities
            )
            landcover = calculate_landcover_features(
                {"latitude": latitude, "longitude": longitude}
            )
            group = temporal_groups[
                (round(latitude, 3), round(longitude, 3))
            ]
            detection_count = len(group)
            duration_hours = 0.0
            if len(group) > 1:
                import pandas as pd

                timestamps = pd.to_datetime(group, errors="coerce")
                duration_hours = max(
                    0.0, (timestamps.max() - timestamps.min()).total_seconds() / 3600
                )
            persistence = calculate_persistence(
                detection_count, duration_hours, 0
            )
            persistence_score = calculate_persistence_score(
                detection_count, duration_hours, 0
            )
            prediction = predict_and_persist(
                event_id,
                {
                    "frp_mean": frp,
                    "frp_max": frp,
                    "confidence": _confidence(row.get("confidence")),
                    "facility_distance": spatial["facility_distance_m"] or 0,
                    "facility_count": spatial["facilities_within_5km"],
                    "industrial_ratio": landcover["industrial_ratio"] or 0,
                    "forest_ratio": landcover["forest_ratio"] or 0,
                    "agriculture_ratio": landcover["agriculture_ratio"] or 0,
                    "builtup_ratio": landcover["builtup_ratio"] or 0,
                    "detection_count": detection_count,
                    "event_duration_hours": duration_hours,
                },
            )
            candidates.append(
                {
                    "event_id": event_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "detection_count": detection_count,
                    "frp": frp,
                    "frp_mean": frp,
                    "frp_max": frp,
                    "confidence": row.get("confidence") or None,
                    "classification": prediction["prediction"],
                    "prediction_confidence": prediction["prediction_confidence"],
                    "persistence": (
                        "PERSISTENT" if persistence == "PERSISTENT" else "TRANSIENT"
                    ),
                    "persistence_score": persistence_score,
                    "high_risk": (
                        prediction["prediction"] == "INDUSTRIAL_FIRE"
                        and float(prediction["prediction_confidence"]) >= 0.65
                    ) or persistence_score >= 70,
                }
            )

    # Keep the dashboard feed balanced and bounded for the MVP.
    candidates.sort(key=lambda event: (-event["frp"], event["event_id"]))
    selected = candidates[:300]
    for event in selected:
        event.pop("frp")
    return selected


def get_realtime_event(event_id: str) -> dict | None:
    return next(
        (event for event in get_realtime_events() if event["event_id"] == event_id),
        None,
    )