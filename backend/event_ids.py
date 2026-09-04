import hashlib


def _stable_digest(parts: list[str]) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12].upper()


def realtime_event_id(row: dict[str, str]) -> str:
    parts = [
        "NRT",
        row.get("latitude", ""),
        row.get("longitude", ""),
        row.get("acq_date", ""),
        row.get("acq_time", ""),
        row.get("satellite", ""),
        row.get("instrument", ""),
    ]
    return f"EVT-NRT-{_stable_digest(parts)}"


def batch_event_id(event_df) -> str:
    detection_keys = sorted(
        "|".join(str(event.get(column, "")) for column in (
            "latitude",
            "longitude",
            "acquisition_date",
            "acquisition_time",
            "satellite",
        ))
        for _, event in event_df.iterrows()
    )
    return f"EVT-BATCH-{_stable_digest(detection_keys)}"
