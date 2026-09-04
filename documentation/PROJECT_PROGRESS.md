# AthletiQ Project Progress

**Review date:** 4 September 2026  
**Repository:** AthletiQ  
**Current maturity:** Working MVP prototype with partially connected processing modules

## Executive Summary

The repository contains a functioning thermal-intelligence dashboard prototype. NASA FIRMS/VIIRS ingestion, CSV-backed FastAPI endpoints, event clustering, feature engineering, an XGBoost classifier, and a React/Leaflet dashboard are present. The dashboard is runnable with generated data, but the complete architecture described in the design documents is not yet implemented as one end-to-end production pipeline.

The most important current boundary is that `backend/main.py` serves dashboard data primarily from CSV files. The database event engine, feature-building workflow, and ML inference code exist, but they are not automatically invoked by the realtime refresh path or exposed through API endpoints.

## Implemented Areas

### Data ingestion and realtime refresh

- `backend/firm_ingestion.py` fetches NASA FIRMS data, validates coordinates and required fields, normalizes records, writes raw and cleaned CSV files, and supports PostgreSQL/PostGIS persistence with duplicate protection.
- `backend/realtime.py` refreshes multiple FIRMS NRT sources, deduplicates records, writes data and status files atomically, detects stale data, and limits the dashboard feed to 300 events.
- FIRMS configuration supports an API key, source list, bounding box, day range, and refresh interval through environment variables.

### Backend API

`backend/main.py` provides a FastAPI service with:

- Health and service status endpoints.
- Event summaries and individual event detail.
- Persistent-event listing.
- Aggregate statistics.
- Realtime status and manual refresh endpoints.
- CORS configuration for the local frontend.
- A startup refresh loop.

The API reads generated files under `backend/data` and does not currently query PostgreSQL for dashboard responses.

### Event processing and features

- `backend/event_engine.py` loads thermal detections, normalizes timestamps, clusters detections using a 5 km Haversine DBSCAN radius, groups detections across a 24-hour gap, calculates event centers, classifies persistence, and computes initial confidence and risk scores.
- Event results can be written to PostGIS and exported to `backend/data/events/events.csv`.
- `backend/feature_engineering/` includes thermal, spatial, temporal, recurrence, facility-proximity, detection-count, duration, and persistence features.
- `backend/feature_engineering/landcover.py` remains a placeholder and returns no land-cover ratios.

### Machine learning

- `backend/ml/training/train_model.py` trains a stratified XGBoost multiclass classifier using 11 structured features and saves the model, label encoder, and feature list.
- `backend/ml/inference/predict.py` loads the saved artifact, validates payload fields, normalizes confidence, and returns a predicted class and probability.
- A trained artifact is present at `backend/ml/models/industrial_fire_classifier.joblib`.

### Frontend

The React/TypeScript dashboard in `frontend/src/` includes:

- KPI metric cards and service/realtime status.
- Event search and filters.
- Leaflet map markers, popups, selection, and a 5 km radius circle.
- Event inspection for thermal, spatial, land-cover, temporal, and persistence data.
- Initial parallel API loading, event-detail loading, fallback data, automatic 60-second refresh, and manual realtime refresh.

## Current Data and Artifacts

The repository currently contains these populated data files:

| File | Approximate rows | Role |
| --- | ---: | --- |
| `backend/data/events/events.csv` | 300 | Event map summaries |
| `backend/data/features/event_features.csv` | 300 | Event-level features and persistence |
| `backend/data/processed/training.csv` | 300 | Classifier/statistics input |
| `backend/data/processed/training_with_recurrence.csv` | 300 | Training data with recurrence |
| `backend/data/firms/viirs_raw.csv` | 14 | Raw FIRMS sample |
| `backend/data/firms/thermal_anomalies.csv` | 14 | Cleaned FIRMS sample |
| `backend/data/firms/realtime_viirs.csv` | 2,411 | Realtime dashboard feed |

These generated files demonstrate available sample output, but do not by themselves prove that every upstream processing step has recently run end to end.

## Implemented Data Flows

### Realtime dashboard path

```text
NASA FIRMS/VIIRS
    -> backend/realtime.py
    -> backend/data/firms/realtime_viirs.csv
    -> backend/main.py
    -> React/Leaflet dashboard
```

### Batch/database path

```text
PostgreSQL thermal detections
    -> backend/event_engine.py
    -> events table and event links
    -> backend/data/events/events.csv
    -> feature_engineering/build_features.py
    -> backend/data/features/event_features.csv
```

### ML path

```text
Processed training CSV
    -> backend/ml/training/train_model.py
    -> industrial_fire_classifier.joblib
    -> backend/ml/inference/predict.py
```

These paths are currently separate. Realtime refresh does not run event clustering, feature engineering, or model inference.

## Known Gaps and Risks

### High priority

- Realtime events receive deterministic placeholder classification, persistence, and risk values based on list position in `backend/realtime.py`; they are not produced by ML or geospatial analysis.
- ML inference is not connected to FastAPI, the event engine, or realtime refresh, and there is no prediction endpoint or prediction persistence.
- Realtime IDs generally do not match feature-file IDs, so selecting many realtime events cannot resolve real detail data and causes frontend fallback behavior.
- `backend/database/schema.sql` and `backend/database/thermal_schema.sql` define incompatible `thermal_anomalies` structures. Ingestion and event processing expect the normalized schema in `schema.sql`.
- There are no application unit tests, API tests, ML evaluation tests, frontend tests, or end-to-end integration tests.

### Medium priority

- Land-cover extraction is not implemented.
- INSAT ingestion, satellite imagery processing, fire-station lookup, alerting, SMS/notification preferences, audit logging, chatbot analytics, and authentication are documented but absent.
- Historical event, facility, GeoJSON/map-layer, and versioned `/api/v1` endpoints are absent.
- Aggregate statistics combine processed training data and feature-table data rather than consistently representing the realtime feed.
- The API event-detail response omits some available fields, including brightness temperature and recurrence/persistence details.
- Confidence values are normalized in backend feature data but are rendered as percentages in the frontend without a consistent conversion contract.
- `frontend/vite.config.ts` configures an `/api` proxy, while the frontend currently calls the backend host directly.
- `frontend/index.html` references `/flame-icon.svg`, but that asset is not present in the repository.
- Docker Compose provisions PostgreSQL/PostGIS only; it does not provision the backend, frontend, workers, scheduler, or ML service.

## Validation Completed During This Review

- Python source files compile successfully.
- The frontend production build succeeds with Vite.
- The frontend build reports a main-bundle size warning above 500 kB.
- The database smoke test exists in `backend/database/test_db.py`, but the repository has no broad automated test suite.
- Root-level pytest collection depends on the active environment having SQLAlchemy and pytest installed.
- The backend README references `backend/requirements.txt`, but the only requirements file is at the repository root: `requirements.txt`.

## Recommended Next Work

1. Choose and document one canonical `thermal_anomalies` schema, then align ingestion, event processing, seed scripts, and initialization order.
2. Define stable event IDs and a shared event/detail contract for realtime and batch outputs.
3. Connect realtime refresh to event clustering, feature generation, and ML inference, or explicitly expose those as separate jobs with persisted outputs.
4. Add API tests for health, event listing, event detail, statistics, realtime refresh, and error handling.
5. Add a classifier endpoint and store model version, prediction, confidence, and timestamp with each event.
6. Implement real land-cover features and replace frontend synthetic/fallback values with API-backed data.
7. Add integration coverage for FIRMS ingestion through dashboard rendering.
8. Only after the core path is coherent, implement the larger documented roadmap: INSAT, imagery, alerts, authentication, fire stations, analytics chatbot, and production deployment services.

## Repository Areas Reviewed

- Root configuration: `docker-compose.yml`, `requirements.txt`.
- Backend service, ingestion, realtime, event engine, persistence, pipeline, geospatial, feature engineering, database, ML, and data directories.
- Frontend Vite/TypeScript configuration, API service, application shell, components, and styles.
- Existing backend and frontend READMEs.
- Existing architecture, product requirements, and market/competitive analysis documents.
