# AI_RULES.md — SA Algal Bloom Monitor

**Any AI reading this file must follow these rules strictly before modifying any code.**

---

## 1. Project Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.11, FastAPI, uvicorn |
| Frontend | React (Create React App), Leaflet |
| Primary DB (cloud) | Supabase PostgreSQL via psycopg2 |
| Local DB (dev) | SQL Server via pyodbc |
| DB switching | `db_config.py` — reads `DATABASE_URL` env var |
| ML | scikit-learn, LightGBM, joblib |
| Hosting | Render (API), Vercel (frontend), Supabase (DB) |

---

## 2. Directory Structure

```
algal-bloom-monitor/
├── api/
│   └── main.py              # FastAPI app — endpoints only, no business logic
├── data_ingestion/
│   ├── fetch_weather.py     # Open-Meteo API → WeatherReadings DB
│   ├── fetch_satellite.py   # Google Earth Engine → bloom_heatmap_latest.geojson
│   ├── fetch_ocean_currents.py  # Simulated SA gulf currents → currents.json
│   ├── coastal_bloom_map.py # RBF interpolation → bloom_heatmap_latest.geojson
│   └── load_ground_truth.py # SA Gov CSV → KareniaReadings DB
├── ml_engine/
│   ├── beach_safety_score.py  # Scores 0–100 → beach_safety_scores.json
│   ├── particle_tracker.py    # Lagrangian 72hr forecast → forecast_latest.json
│   ├── train_classifier.py    # Trains bloom_model.pkl
│   ├── bloom_model.pkl        # Committed — do not gitignore
│   └── label_encoder.pkl      # Committed — do not gitignore
├── data_ingestion/
│   └── sa_bloom_data.csv    # SA Gov Karenia data — manually updated monthly
├── data/
│   ├── indices/bloom_heatmap_latest.geojson
│   ├── forecasts/forecast_latest.json
│   ├── ocean/currents.json
│   ├── beach_safety_scores.json
│   └── refresh_log.json     # Written by refresh_data.py — do not commit
├── frontend/sa-bloom-dashboard/
│   └── src/
│       ├── App.js           # All React state, API calls, and JSX
│       └── App.css          # All styles including responsive media queries
├── db_config.py             # DB connection switching — do not duplicate this logic
├── refresh_data.py          # Orchestrates all 7 data scripts — the only refresh entry point
├── cron_trigger.py          # Called by GitHub Actions to hit /api/refresh
└── .github/workflows/
    └── daily_refresh.yml    # Runs at 2am UTC daily
```

### Where logic must live

| Concern | Must live in |
|---|---|
| HTTP endpoints, request/response shaping | `api/main.py` |
| External API calls (weather, GEE, etc.) | `data_ingestion/` scripts |
| ML inference and scoring | `ml_engine/` scripts |
| DB connection, SQL dialect switching | `db_config.py` only |
| Refresh orchestration | `refresh_data.py` only |
| React state, API calls, map rendering | `frontend/.../App.js` |
| CSS layout and responsive styles | `frontend/.../App.css` |

**Never** put DB connection logic outside `db_config.py`. **Never** put endpoint logic inside `data_ingestion/` or `ml_engine/` scripts.

---

## 3. Database Rules

- Always import from `db_config`: `from db_config import get_connection, adapt_sql, ph, IS_POSTGRES`
- Always use `adapt_sql()` on any query containing `SELECT TOP N` — converts to `LIMIT N` for PostgreSQL
- Always use `ph(n)` for INSERT placeholders — returns `%s,%s,...` (Postgres) or `?,?,...` (SQL Server)
- Always pass INSERT parameters as a **tuple** to `cursor.execute()` — psycopg2 requires this
- Never hardcode a connection string anywhere except `db_config.py`
- Never check `IS_POSTGRES` outside `db_config.py` or `api/main.py`

---

## 4. File Size Limit

**No file may exceed 300 lines.**

If a file is approaching 300 lines, split it:
- `api/main.py` → extract endpoint groups into `api/routes_weather.py`, `api/routes_forecast.py`, etc., then include with `app.include_router()`
- `data_ingestion/` scripts → extract shared helpers into `data_ingestion/utils.py`
- `ml_engine/` scripts → extract scoring logic into `ml_engine/scoring.py`

---

## 5. Python Style

### Type hints
All function signatures must include type hints:

```python
# Correct
def save_to_db(location: dict, data: dict) -> int:
    ...

# Wrong
def save_to_db(location, data):
    ...
```

### Docstrings
All functions with more than 3 lines of logic must have a docstring:

```python
def calculate_safety_score(cell_count: int, wind_speed: float, wind_dir: float, sfabi: float) -> float:
    """
    Compute beach safety score 0–100 using SA Health thresholds.

    Args:
        cell_count: Karenia brevis cells per litre
        wind_speed: wind speed in km/h from Open-Meteo
        wind_dir:   wind direction in degrees
        sfabi:      Sentinel-2 SFABI index value

    Returns:
        Safety score where 100 = safe, 0 = extreme danger
    """
```

### Error handling
- Every `requests.get()` call must have an explicit `timeout` parameter
- Every subprocess that writes a file must validate the output before accepting it
- Never silence exceptions with a bare `except: pass` — always log the error

---

## 6. Modularity Rules

- Every data script must have a `run()` function as its entry point (for direct import by tests or orchestrators)
- Scripts that are called by `refresh_data.py` via subprocess must also work standalone: `if __name__ == "__main__": run()`
- `refresh_data.py` is the **only** place that calls data scripts in sequence — never chain scripts by importing one from another
- New data sources must follow the pattern: fetch → validate → write to DB or file. Never write to both DB and file in the same script

---

## 7. Never-Blank Data Rules

These rules apply to every endpoint and every refresh script:

1. **Back up before overwriting**: before any script writes a file, the caller must back up the existing file
2. **Validate before accepting**: GeoJSON must have `≥1 feature`; JSON forecasts must have non-empty `snapshots`; DB inserts must have `≥1 row`
3. **Restore on failure**: if validation fails, restore the backup
4. **API endpoints always return**: never return `null`, never return an error object where the frontend expects an array
5. **Array endpoints**: `/api/weather` and `/api/cell-counts` return `{"readings": [...], "last_updated": "...", "data_source": "..."}` — not a bare array

---

## 8. Environment Variables

| Variable | Used in | Purpose |
|---|---|---|
| `DATABASE_URL` | `db_config.py` | Supabase connection string (URL-encoded `@` as `%40`) |
| `REFRESH_KEY` | `api/main.py` | Authenticates `POST /api/refresh` via `X-Refresh-Key` header |
| `GEE_SERVICE_ACCOUNT_JSON` | `fetch_satellite.py` | Full GEE service account JSON as a single-line string |

- Never hardcode these values anywhere
- Never commit `.env` or any `*.json` file matching `smart-464108*.json` or `*service_account*.json`
- The `.gitignore` already excludes these — do not remove those entries

---

## 9. Frontend Rules

- The production API URL is hardcoded in `App.js` line 6: `const API='https://sa-algal-bloom.onrender.com/api'`
- Do not use `process.env.REACT_APP_*` for the API URL — Vercel does not pick it up correctly at build time
- All state variables are declared at the top of `App.js` — do not move them or split them across components
- `fetchAll()` uses `Promise.allSettled` — never change this to `Promise.all` (one failing request must not blank the whole dashboard)
- CSS breakpoint for mobile is `768px` — all responsive rules are in `App.css` under `@media (max-width: 768px)`

---

## 10. Deployment

| Service | Trigger | Config |
|---|---|---|
| Render (API) | Push to `main` | `render.yaml` |
| Vercel (frontend) | Push to `main` | auto-detected CRA |
| GitHub Actions (cron) | Daily 2am UTC | `.github/workflows/daily_refresh.yml` |

- The Render free tier sleeps after 15 min idle — `cron_trigger.py` handles the cold start wake before triggering refresh
- `render_cron.yaml` is present but unused (Render Cron Jobs are paid) — the GitHub Actions workflow is the active scheduler
- Do not add `render_cron.yaml` as an active Render service
