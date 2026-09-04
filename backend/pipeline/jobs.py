import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

BACKEND_DIR = Path(__file__).parents[1]
DATA_DIR = BACKEND_DIR / "data"
LIVE_DATA_PATH = DATA_DIR / "firms" / "realtime_viirs.csv"
STATUS_PATH = DATA_DIR / "pipeline_status.json"
FEATURES_PATH = DATA_DIR / "features" / "event_features.csv"
PREDICTIONS_PATH = DATA_DIR / "predictions" / "event_predictions.csv"

STAGES = ("ingestion", "clustering", "features", "inference")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_status() -> dict:
    defaults = {
        stage: {"status": "never_run", "started_at": None, "completed_at": None}
        for stage in STAGES
    }
    if STATUS_PATH.exists():
        stored = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        for stage in STAGES:
            defaults[stage].update(stored.get(stage, {}))
    return defaults


def _write_status(status: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=STATUS_PATH.parent, delete=False
    ) as temporary_file:
        json.dump(status, temporary_file, indent=2)
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(STATUS_PATH)


def _set_stage(stage: str, **values) -> None:
    status = _read_status()
    status[stage].update(values)
    _write_status(status)


def _run_clustering() -> dict:
    import event_engine

    event_engine.main()
    return {"output": str(DATA_DIR / "events" / "events.csv")}


def _run_ingestion() -> dict:
    if not LIVE_DATA_PATH.exists():
        raise FileNotFoundError(f"Realtime input does not exist: {LIVE_DATA_PATH}")

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from firm_ingestion import (
        clean_viirs_data,
        save_to_database,
        transform_to_thermal_anomalies,
    )

    raw_data = pd.read_csv(LIVE_DATA_PATH)
    cleaned_data = clean_viirs_data(raw_data)
    thermal_data = transform_to_thermal_anomalies(cleaned_data)
    inserted_count = save_to_database(thermal_data)
    return {
        "output": str(LIVE_DATA_PATH),
        "rows": len(thermal_data),
        "inserted": inserted_count,
    }


def _run_features() -> dict:
    feature_engineering_dir = str(BACKEND_DIR / "feature_engineering")
    if feature_engineering_dir not in sys.path:
        sys.path.insert(0, feature_engineering_dir)
    from feature_engineering.build_features import build_feature_table

    feature_table = build_feature_table()
    FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    feature_table.to_csv(FEATURES_PATH, index=False)
    return {"output": str(FEATURES_PATH), "rows": len(feature_table)}


def _number(value, default=0.0) -> float:
    if value is None or pd.isna(value) or value == "":
        return default
    return float(value)


def _run_inference() -> dict:
    from ml.inference.predict import predict

    if not FEATURES_PATH.exists():
        raise FileNotFoundError(f"Feature output does not exist: {FEATURES_PATH}")

    features = pd.read_csv(FEATURES_PATH)
    predictions = []
    failures = []
    for _, row in features.iterrows():
        payload = {
            "frp_mean": _number(row.get("frp_mean")),
            "frp_max": _number(row.get("frp_max")),
            "confidence": _number(row.get("confidence_mean")),
            "facility_distance": _number(row.get("facility_distance_m")),
            "facility_count": int(_number(row.get("facilities_within_5km"))),
            "industrial_ratio": _number(row.get("industrial_ratio")),
            "forest_ratio": _number(row.get("forest_ratio")),
            "agriculture_ratio": _number(row.get("agriculture_ratio")),
            "builtup_ratio": _number(row.get("builtup_ratio")),
            "detection_count": int(_number(row.get("detection_count"), 1)),
            "event_duration_hours": _number(row.get("event_duration_hours")),
        }
        try:
            result = predict(payload)
            predictions.append({
                "event_id": row["event_id"],
                "event_code": row.get("event_code", row["event_id"]),
                "prediction": result["prediction"],
                "prediction_confidence": result["confidence"],
                "predicted_at": _now(),
            })
        except Exception as error:
            failures.append({"event_id": row.get("event_id"), "error": str(error)})

    output = pd.DataFrame(
        predictions,
        columns=[
            "event_id",
            "event_code",
            "prediction",
            "prediction_confidence",
            "predicted_at",
        ],
    )
    PREDICTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PREDICTIONS_PATH, index=False)
    result = {
        "output": str(PREDICTIONS_PATH),
        "rows": len(output),
        "failures": failures,
    }
    if failures and not predictions:
        raise RuntimeError(f"Inference failed for every feature row: {failures[0]}")
    return result


_RUNNERS = {
    "ingestion": _run_ingestion,
    "clustering": _run_clustering,
    "features": _run_features,
    "inference": _run_inference,
}


def run_job(stage: str) -> dict:
    if stage not in _RUNNERS:
        raise ValueError(f"Unknown pipeline stage: {stage}. Choose from {STAGES}.")

    started_at = _now()
    _set_stage(stage, status="running", started_at=started_at, error=None)
    try:
        result = _RUNNERS[stage]()
    except Exception as error:
        _set_stage(stage, status="failed", completed_at=_now(), error=str(error))
        raise
    _set_stage(stage, status="completed", completed_at=_now(), error=None, **result)
    return _read_status()[stage]


def get_job_status() -> dict:
    return _read_status()
