import csv
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from .predict import predict


PREDICTIONS_PATH = Path(__file__).parents[2] / "data" / "predictions" / "event_predictions.csv"
PREDICTION_FIELDS = (
    "event_id",
    "event_code",
    "prediction",
    "prediction_confidence",
    "predicted_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_prediction(event_id: str, result: dict, event_code: str | None = None) -> dict:
    records = []
    if PREDICTIONS_PATH.exists():
        with PREDICTIONS_PATH.open(newline="", encoding="utf-8-sig") as predictions_file:
            records = list(csv.DictReader(predictions_file))

    record = {
        "event_id": event_id,
        "event_code": event_code or event_id,
        "prediction": result["prediction"],
        "prediction_confidence": result["confidence"],
        "predicted_at": _now(),
    }
    records = [record if row.get("event_id") == event_id else row for row in records]
    if not any(row.get("event_id") == event_id for row in records):
        records.append(record)

    PREDICTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", newline="", encoding="utf-8", dir=PREDICTIONS_PATH.parent, delete=False
    ) as temporary_file:
        writer = csv.DictWriter(temporary_file, fieldnames=PREDICTION_FIELDS)
        writer.writeheader()
        writer.writerows(records)
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(PREDICTIONS_PATH)
    return record


def predict_and_persist(
    event_id: str,
    payload: dict,
    event_code: str | None = None,
) -> dict:
    return persist_prediction(event_id, predict(payload), event_code)


def get_prediction(event_id: str) -> dict | None:
    if not PREDICTIONS_PATH.exists():
        return None
    with PREDICTIONS_PATH.open(newline="", encoding="utf-8-sig") as predictions_file:
        return next(
            (row for row in csv.DictReader(predictions_file) if row.get("event_id") == event_id),
            None,
        )
