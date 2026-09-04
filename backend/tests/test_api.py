import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "get_realtime_events", lambda: [])
    monkeypatch.setattr(main, "get_realtime_event", lambda _event_id: None)
    return TestClient(main.app)


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_event_listing_uses_batch_contract(client):
    response = client.get("/events")
    body = response.json()

    assert response.status_code == 200
    assert body["source"] == "BATCH"
    assert body["count"] == len(body["events"])
    assert body["events"][0]["event_id"] == "EVT-IND-001"
    assert {"latitude", "longitude", "detection_count"} <= body["events"][0].keys()


def test_realtime_event_listing_and_detail_contract(client, monkeypatch):
    realtime_event = {
        "event_id": "EVT-NRT-TEST123456",
        "latitude": 28.1,
        "longitude": 77.2,
        "detection_count": 1,
        "frp_mean": 42.0,
        "frp_max": 42.0,
        "confidence": "n",
        "classification": "OTHER_THERMAL_ANOMALY",
        "persistence": "TRANSIENT",
        "persistence_score": 20,
        "high_risk": False,
    }
    monkeypatch.setattr(main, "get_realtime_events", lambda: [realtime_event])
    monkeypatch.setattr(main, "get_realtime_event", lambda event_id: realtime_event if event_id == realtime_event["event_id"] else None)

    listing = client.get("/events")
    detail = client.get(f"/events/{realtime_event['event_id']}")

    assert listing.status_code == 200
    assert listing.json()["source"] == "NASA_FIRMS_MULTI_SOURCE_NRT"
    assert listing.json()["events"] == [realtime_event]
    assert detail.status_code == 200
    assert detail.json()["event_id"] == realtime_event["event_id"]
    assert detail.json()["thermal"]["confidence"] == "n"
    assert detail.json()["temporal"]["event_duration_hours"] == 0


def test_batch_event_detail_uses_shared_contract(client):
    response = client.get("/events/EVT-IND-001")
    body = response.json()

    assert response.status_code == 200
    assert body["event_id"] == "EVT-IND-001"
    assert {
        "event_id",
        "thermal",
        "spatial",
        "land_cover",
        "temporal",
        "classification",
        "persistence",
        "persistence_score",
    } <= body.keys()
    assert body["temporal"]["event_duration_hours"] == pytest.approx(47.07)


def test_statistics(client):
    response = client.get("/statistics")
    body = response.json()

    assert response.status_code == 200
    assert body["total_events"] > 0
    assert {
        "industrial_fires",
        "wildfires",
        "agricultural_burning",
        "persistent_sources",
        "recurring_events",
        "high_risk_events",
    } <= body.keys()


def test_realtime_refresh_success_and_failure(client, monkeypatch):
    expected = {"configured": True, "fetched_count": 2, "last_error": None}
    monkeypatch.setattr(main, "refresh_realtime_data", lambda: expected)

    response = client.post("/realtime/refresh")

    assert response.status_code == 200
    assert response.json() == expected

    monkeypatch.setattr(
        main,
        "refresh_realtime_data",
        lambda: (_ for _ in ()).throw(RuntimeError("upstream unavailable")),
    )
    response = client.post("/realtime/refresh")

    assert response.status_code == 502
    assert response.json()["detail"] == "upstream unavailable"


def test_prediction_endpoint_persists_and_reads_prediction(client, monkeypatch):
    prediction = {
        "event_id": "EVT-NRT-TEST123456",
        "event_code": "EVT-NRT-TEST123456",
        "prediction": "INDUSTRIAL_FIRE",
        "prediction_confidence": 0.91,
        "predicted_at": "2026-09-04T00:00:00+00:00",
    }
    monkeypatch.setattr(main, "predict_and_persist", lambda *args: prediction)
    monkeypatch.setattr(main, "get_prediction", lambda _event_id: prediction)

    response = client.post(
        "/predictions",
        json={
            "event_id": prediction["event_id"],
            "frp_mean": 42,
            "confidence": 0.9,
            "facility_distance": 100,
            "industrial_ratio": 0.8,
            "forest_ratio": 0.1,
        },
    )

    assert response.status_code == 200
    assert response.json() == prediction
    assert client.get(f"/predictions/{prediction['event_id']}").json() == prediction


def test_pipeline_job_status_and_success(client, monkeypatch):
    expected_status = {
        "status": "completed",
        "output": "backend/data/events/events.csv",
        "rows": 4,
    }
    monkeypatch.setattr(main, "get_job_status", lambda: {"clustering": expected_status})
    monkeypatch.setattr(main, "run_job", lambda stage: {**expected_status, "stage": stage})

    status_response = client.get("/pipeline/jobs")
    job_response = client.post("/pipeline/jobs/clustering")

    assert status_response.status_code == 200
    assert status_response.json()["clustering"]["status"] == "completed"
    assert job_response.status_code == 200
    assert job_response.json()["stage"] == "clustering"


def test_pipeline_job_errors(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "run_job",
        lambda _stage: (_ for _ in ()).throw(ValueError("unknown pipeline stage")),
    )
    response = client.post("/pipeline/jobs/not-a-stage")

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown pipeline stage"

    monkeypatch.setattr(
        main,
        "run_job",
        lambda _stage: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    response = client.post("/pipeline/jobs/clustering")

    assert response.status_code == 500
    assert response.json()["detail"] == "database unavailable"


def test_missing_event_returns_not_found(client):
    response = client.get("/events/EVT-DOES-NOT-EXIST")

    assert response.status_code == 404
    assert response.json()["detail"] == "Event EVT-DOES-NOT-EXIST not found"
