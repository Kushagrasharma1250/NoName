# TRACE Backend

The backend is a FastAPI service for the TRACE:Thermal risk & anomaly classification engine dashboard. It serves event summaries, persistent thermal sources, aggregate statistics, and detailed event telemetry from generated CSV data. Supporting modules ingest NASA FIRMS data, build event clusters, engineer features, run classification, and persist results in PostgreSQL/PostGIS.

## Technology Stack

- Python 3.10+
- FastAPI and Uvicorn
- Pandas and NumPy for data processing
- Scikit-learn and XGBoost for machine learning
- SQLAlchemy and Psycopg for PostgreSQL/PostGIS access
- Requests and python-dotenv for ingestion and configuration
- Docker Compose with PostgreSQL/PostGIS for local infrastructure

## Requirements

- Python 3.10 or newer
- PostgreSQL with PostGIS, or Docker Desktop
- A NASA FIRMS map key for live ingestion

The repository currently does not include `backend/requirements.txt`. The backend imports FastAPI, Uvicorn, pandas, NumPy, python-dotenv, SQLAlchemy, scikit-learn, requests, and joblib. Install the dependencies in the active Python environment before running the service.

## Configuration

Create `backend/.env` for database-backed ingestion and event processing:

```env
DATABASE_URL=postgresql+psycopg2://fire_admin:131006@localhost:5432/fire_intelligence
NASA_FIRMS_MAP_KEY=your_nasa_firms_map_key
NASA_FIRMS_BBOX=68,6,97,37
NASA_FIRMS_SOURCE=VIIRS_NOAA21_NRT
NASA_FIRMS_SOURCES=VIIRS_NOAA21_NRT,VIIRS_NOAA20_NRT,VIIRS_SNPP_NRT,MODIS_NRT
NASA_FIRMS_DAYS=5
REALTIME_REFRESH_SECONDS=900
```

`main.py` reads the generated CSV files under `backend/data` and does not require a database connection to serve the dashboard endpoints. `event_engine.py`, `firm_ingestion.py`, and the database modules do require `DATABASE_URL`. Keep API keys and database credentials out of source control.

The real-time service refreshes the configured FIRMS/VIIRS area on startup and every `REALTIME_REFRESH_SECONDS`. Use `POST /realtime/refresh` for an immediate refresh and `GET /realtime/status` to inspect configuration, last successful retrieval, record count, and staleness.

Realtime acquisition is separate from processing jobs. The refresh persists raw FIRMS data; processing stages are explicitly triggered and their status is persisted in `backend/data/pipeline_status.json`:

- `POST /pipeline/jobs/ingestion` normalizes the persisted realtime CSV and writes detections to PostgreSQL/PostGIS.
- `POST /pipeline/jobs/clustering` runs database-backed event clustering and exports `backend/data/events/events.csv`.
- `POST /pipeline/jobs/features` builds event features and exports `backend/data/features/event_features.csv`.
- `POST /pipeline/jobs/inference` runs the classifier over the feature output and exports `backend/data/predictions/event_predictions.csv`.
- `GET /pipeline/jobs` returns the status, timestamps, output path, row count, and errors for each stage.

Run the stages in this order after `POST /realtime/refresh`: `ingestion`, `clustering`, `features`, then `inference`. Each stage is independently rerunnable; a later stage consumes the previous stage's persisted output.

## Start PostgreSQL

The included Compose configuration starts PostGIS on port `5432`:

```powershell
docker compose up -d postgres
```

The database settings are defined in `docker-compose.yml`:

- Database: `fire_intelligence`
- User: `fire_admin`
- Port: `5432`

On a new PostgreSQL volume, Docker initializes the database in this order:

1. `backend/database/schema.sql` creates the PostGIS extension, facilities, and the canonical normalized `thermal_anomalies` table.
2. `backend/database/events_schema.sql` creates the event table that references thermal detections by `event_id`.
3. `backend/database/seed_facilities.sql` inserts the sample facilities idempotently.

`backend/database/thermal_schema.sql` is deprecated and must not be run. The canonical thermal anomaly columns are `latitude`, `longitude`, `acquisition_date`, `acquisition_time`, `brightness_temperature`, `background_temperature`, `frp`, `confidence`, `satellite`, `instrument`, `daynight`, `source`, `source_dataset`, `anomaly_type`, `event_id`, and `location`.

## Run the API

From the repository root, activate the project environment and start Uvicorn:

```powershell
.\.venv\Scripts\Activate.ps1
cd backend
uvicorn main:app --reload --port 8000
```

The API is available at `http://localhost:8000`. Interactive API documentation is available at `http://localhost:8000/docs`, with the OpenAPI schema at `http://localhost:8000/openapi.json`.

## API Endpoints

### `GET /`

Returns the service name and online status.

### `GET /health`

Returns:

```json
{"status": "healthy"}
```

### `GET /events`

Returns one stable event-summary envelope for either the realtime FIRMS feed or the batch event export. Every event uses `event_id` as its public identifier; realtime IDs use the `EVT-NRT-...` namespace and batch IDs use `EVT-BATCH-...`.

```json
{
  "events": [
    {
      "event_id": "EVT_2026_001",
      "latitude": 29.9511,
      "longitude": -90.0715,
      "detection_count": 12
    }
  ]
}
```

`GET /events/{event_id}` uses the same detail contract for both sources: `event_id`, `thermal`, `spatial`, `land_cover`, `temporal`, `classification`, `persistence`, and `persistence_score`. Fields unavailable for realtime detections are returned as `null` or zero rather than changing the response shape.

### Land-cover configuration

Feature generation reads a categorical GeoTIFF configured with `LANDCOVER_RASTER_PATH`. The default class mapping follows ESA WorldCover: forest classes `10,20,30`, agriculture `40`, and built-up `50`. Set `LANDCOVER_RADIUS_M` to change the sampling radius, and use `LANDCOVER_CLASS_MAPPING` JSON to match another product, for example:

```env
LANDCOVER_RASTER_PATH=C:\data\worldcover.tif
LANDCOVER_RADIUS_M=500
LANDCOVER_CLASS_MAPPING={"forest":[10,20,30],"agriculture":[40],"builtup":[50],"industrial":[51]}
```

`industrial_ratio` is `null` by default because ESA WorldCover does not distinguish industrial land from other built-up land. Provide a dataset-specific industrial class through the mapping when available. Without `LANDCOVER_RASTER_PATH`, all land-cover fields remain `null`; no synthetic values are generated.

If the CSV is missing, the endpoint returns an empty event list.

### `GET /events/persistent`

Returns rows marked `PERSISTENT` in `backend/data/features/event_features.csv`, including the persistence score and total count.

### `GET /statistics`

Returns aggregate totals derived from the processed training data and event features:

- `total_events`
- `industrial_fires`
- `wildfires`
- `agricultural_burning`
- `persistent_sources`
- `recurring_events`
- `high_risk_events`

### `GET /events/{event_id}`

Returns thermal, spatial, land-cover, temporal, and persistence details for one event. The endpoint returns HTTP 404 when the feature file or requested event is unavailable.

## Data Flow

1. `firm_ingestion.py` fetches and cleans VIIRS thermal anomalies from NASA FIRMS.
2. `backend/database` contains the database connection and schema scripts for PostgreSQL/PostGIS.
3. `event_engine.py` loads thermal detections and groups nearby detections into events using spatial and temporal rules.
4. `feature_engineering` builds thermal, spatial, land-cover, and temporal features.
5. `ml/training/train_model.py` trains the industrial fire classifier; the trained model is stored under `ml/models`.
6. `ml/inference/predict.py` provides model prediction logic.
7. `persistence` and `pipeline` contain persistence detection and processing workflow code.
8. The API reads the generated CSV outputs and exposes them to the frontend.

## Generated Data Files

The API expects these files when they are available:

- `backend/data/events/events.csv`: event map summaries
- `backend/data/features/event_features.csv`: event-level feature and persistence data
- `backend/data/processed/training_with_recurrence.csv`: classification and aggregate statistics data
- `backend/data/firms/`: downloaded and cleaned FIRMS data

## Frontend Integration

The frontend defaults to `http://localhost:8000`. To use another API host, set `VITE_API_URL` in the frontend environment. CORS is currently enabled for `http://localhost:5173` and `http://127.0.0.1:5173`.

## Quick Checks

With the API running:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/events
Invoke-RestMethod http://localhost:8000/statistics
```
