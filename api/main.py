from dotenv import load_dotenv
load_dotenv()

import json
import os
import sys
import logging
import joblib
import numpy as np
from datetime import datetime
from fastapi import FastAPI, Header, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from db_config import get_connection, adapt_sql, IS_POSTGRES

app = FastAPI(title="SA Algal Bloom Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Absolute project root — works regardless of uvicorn launch directory ──
# api/main.py lives at <root>/api/main.py  →  root = two levels up from __file__
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def root_path(*parts):
    """Return an absolute path relative to the project root."""
    return os.path.join(ROOT, *parts)

# ── Refresh key (set on Render dashboard) ──
REFRESH_KEY = os.getenv("REFRESH_KEY", "")

# ── Load ML model once at startup ──
MODEL   = None
ENCODER = None

def load_model():
    global MODEL, ENCODER
    try:
        MODEL   = joblib.load(root_path("ml_engine", "bloom_model.pkl"))
        ENCODER = joblib.load(root_path("ml_engine", "label_encoder.pkl"))
        print(f"ML model loaded OK from {root_path('ml_engine', 'bloom_model.pkl')}")
    except Exception as e:
        print(f"Model load warning: {e}")

load_model()

# ── Import refresh module (lives in project root) ──
sys.path.insert(0, ROOT)
try:
    import refresh_data as _refresh_module
    _REFRESH_AVAILABLE = True
except ImportError:
    _REFRESH_AVAILABLE = False


# ── Helpers for response metadata ─────────────────────────────────────────────
def _meta(source_key, file_path=None):
    """Return last_updated + data_source dict to attach to any response."""
    last_updated = None

    # 1. Try refresh log
    try:
        log_path = root_path("data", "refresh_log.json")
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                log = json.load(f)
            last_updated = log.get("sources", {}).get(source_key, {}).get("last_success")
    except Exception:
        pass

    # 2. Fall back to file mtime
    if not last_updated and file_path and os.path.exists(file_path):
        try:
            last_updated = datetime.fromtimestamp(
                os.path.getmtime(file_path)
            ).isoformat()
        except Exception:
            pass

    return {
        "last_updated": last_updated,
        "data_source":  "live" if last_updated else "unknown",
    }


# ════════════════════════════════════
# ENDPOINT 1 — Health check
# ════════════════════════════════════
@app.api_route("/api/health", methods=["GET", "HEAD"])
def health(response: Response):
    return {
        "status":    "ok",
        "timestamp": datetime.now().isoformat(),
        "model":     "loaded" if MODEL else "not loaded"
    }


# ════════════════════════════════════
# ENDPOINT — Debug (path diagnostics)
# ════════════════════════════════════
@app.get("/api/debug")
def debug():
    forecast_path = root_path("data", "forecasts", "forecast_latest.json")
    heatmap_path  = root_path("data", "indices", "bloom_heatmap_latest.geojson")
    safety_path   = root_path("data", "beach_safety_scores.json")
    model_path    = root_path("ml_engine", "bloom_model.pkl")

    # Walk data/ directory
    data_dir  = root_path("data")
    file_tree = {}
    if os.path.isdir(data_dir):
        for dirpath, dirnames, filenames in os.walk(data_dir):
            rel = os.path.relpath(dirpath, ROOT)
            file_tree[rel] = filenames

    return {
        "ROOT":              ROOT,
        "cwd":               os.getcwd(),
        "IS_POSTGRES":       IS_POSTGRES,
        "files": {
            "forecast_latest.json":         os.path.exists(forecast_path),
            "bloom_heatmap_latest.geojson": os.path.exists(heatmap_path),
            "beach_safety_scores.json":     os.path.exists(safety_path),
            "bloom_model.pkl":              os.path.exists(model_path),
        },
        "paths": {
            "forecast": forecast_path,
            "heatmap":  heatmap_path,
            "safety":   safety_path,
            "model":    model_path,
        },
        "data_directory": file_tree,
    }


# ════════════════════════════════════
# ENDPOINT 2 — Bloom heatmap
# ════════════════════════════════════
def _cell_counts_as_geojson() -> dict:
    """
    Build a GeoJSON FeatureCollection from live KareniaReadings as a fallback
    when the satellite bloom_heatmap_latest.geojson has no features.

    Returns:
        GeoJSON FeatureCollection with lat/lon/severity/cell_count properties
        matching the format the frontend expects for circle markers.
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(adapt_sql("""
            SELECT TOP 100
                beach_name, latitude, longitude,
                cell_count_per_litre, severity
            FROM KareniaReadings
            ORDER BY recorded_at DESC
        """))
        rows = cursor.fetchall()
        conn.close()
        features = []
        for r in rows:
            if r[1] is None or r[2] is None:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "lat":        float(r[1]),
                    "lon":        float(r[2]),
                    "severity":   r[4] or "Low",
                    "cell_count": r[3] or 0,
                    "sfabi":      None,
                    "beach_name": r[0],
                },
                "geometry": {
                    "type":        "Point",
                    "coordinates": [float(r[2]), float(r[1])],
                },
            })
        return {
            "type":        "FeatureCollection",
            "features":    features,
            "data_source": "ground_truth_fallback",
        }
    except Exception as e:
        logging.warning(f"_cell_counts_as_geojson failed: {e}")
        return {"type": "FeatureCollection", "features": [], "data_source": "error"}


@app.get("/api/bloom-heatmap")
def bloom_heatmap():
    """Return satellite bloom GeoJSON, falling back to ground truth dots if empty."""
    path = root_path("data", "indices", "bloom_heatmap_latest.geojson")
    meta = _meta("satellite", path)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            features = data.get("features", [])
            # If satellite GeoJSON has real data, return it
            if features:
                data["last_updated"] = meta["last_updated"]
                data["data_source"]  = meta["data_source"]
                return data
        except Exception as e:
            logging.warning(f"bloom_heatmap: GeoJSON load error: {e}")

    # Satellite empty or missing — fall back to ground truth cell count dots
    fallback = _cell_counts_as_geojson()
    fallback["last_updated"] = meta["last_updated"]
    return fallback


# ════════════════════════════════════
# ENDPOINT 2b — Satellite-only data
# ════════════════════════════════════
@app.get("/api/satellite")
def satellite_data():
    """
    Return ONLY real Sentinel-2 SFABI data with stats.

    Never falls back to ground truth — used by the dedicated satellite tab
    so it can accurately show 'unavailable' when GEE data is absent.

    Returns:
        GeoJSON FeatureCollection with sfabi-valued features + metadata block.
    """
    path = root_path("data", "indices", "bloom_heatmap_latest.geojson")
    meta = _meta("satellite", path)
    empty_response = {
        "type": "FeatureCollection",
        "features": [],
        "data_source": "unavailable",
        "last_updated": meta["last_updated"],
        "stats": None,
    }
    if not os.path.exists(path):
        return empty_response
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        features = [
            ft for ft in data.get("features", [])
            if ft.get("properties", {}).get("sfabi") is not None
        ]
        if not features:
            return empty_response
        sfabi_vals = [ft["properties"]["sfabi"] for ft in features]
        high = sum(1 for v in sfabi_vals if v > 0.15)
        med  = sum(1 for v in sfabi_vals if 0.05 < v <= 0.15)
        low  = sum(1 for v in sfabi_vals if v <= 0.05)
        return {
            "type":         "FeatureCollection",
            "features":     features,
            "data_source":  "sentinel2",
            "last_updated": meta["last_updated"],
            "stats": {
                "n_pixels":  len(features),
                "sfabi_min": round(min(sfabi_vals), 4),
                "sfabi_max": round(max(sfabi_vals), 4),
                "sfabi_mean": round(sum(sfabi_vals) / len(sfabi_vals), 4),
                "high_pixels":   high,
                "medium_pixels": med,
                "low_pixels":    low,
            },
        }
    except Exception as e:
        logging.warning(f"satellite_data: {e}")
        return empty_response



# ════════════════════════════════════
# ENDPOINT 3 — Cell counts
# ════════════════════════════════════
@app.get("/api/cell-counts")
def cell_counts():
    meta = _meta("ground_truth")
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(adapt_sql("""
            SELECT TOP 100
                beach_name,
                latitude,
                longitude,
                cell_count_per_litre,
                severity,
                recorded_at
            FROM KareniaReadings
            ORDER BY recorded_at DESC
        """))
        rows = cursor.fetchall()
        conn.close()
        readings = [
            {
                "beach_name":           r[0],
                "latitude":             r[1],
                "longitude":            r[2],
                "cell_count_per_litre": r[3],
                "severity":             r[4],
                "recorded_at":          r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
        return {
            "readings":    readings,
            "last_updated": meta["last_updated"],
            "data_source":  "live" if rows else "empty",
        }
    except Exception:
        return {"readings": [], "last_updated": None, "data_source": "error"}


# ════════════════════════════════════
# ENDPOINT 4 — Weather
# ════════════════════════════════════
@app.get("/api/weather")
def weather():
    meta = _meta("weather")
    try:
        conn   = get_connection()
        cursor = conn.cursor()

        if IS_POSTGRES:
            cursor.execute("""
                SELECT DISTINCT ON (location_name)
                    location_name,
                    latitude,
                    longitude,
                    wind_speed,
                    wind_direction,
                    sea_surface_temp,
                    solar_radiation,
                    wave_height,
                    recorded_at
                FROM weatherreadings
                ORDER BY location_name, recorded_at DESC
            """)
        else:
            cursor.execute("""
                SELECT
                    location_name,
                    latitude,
                    longitude,
                    wind_speed,
                    wind_direction,
                    sea_surface_temp,
                    solar_radiation,
                    wave_height,
                    recorded_at
                FROM WeatherReadings
                WHERE recorded_at = (
                    SELECT MAX(recorded_at)
                    FROM WeatherReadings w2
                    WHERE w2.location_name = WeatherReadings.location_name
                )
                ORDER BY location_name
            """)

        rows = cursor.fetchall()
        conn.close()
        readings = [
            {
                "location_name":    r[0],
                "latitude":         r[1],
                "longitude":        r[2],
                "wind_speed":       r[3],
                "wind_direction":   r[4],
                "sea_surface_temp": r[5],
                "solar_radiation":  r[6],
                "wave_height":      r[7],
                "recorded_at":      r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ]
        return {
            "readings":     readings,
            "last_updated": meta["last_updated"],
            "data_source":  "live" if rows else "empty",
        }
    except Exception:
        return {"readings": [], "last_updated": None, "data_source": "error"}


# ════════════════════════════════════
# ENDPOINT 5 — 72hr forecast
# ════════════════════════════════════
@app.get("/api/forecast/72hr")
def forecast_72hr():
    path = root_path("data", "forecasts", "forecast_latest.json")
    meta = _meta("particle_tracker", path)
    logging.warning(f"[forecast] Looking for forecast at: {path}")
    logging.warning(f"[forecast] File exists: {os.path.exists(path)}")
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            return {
                "generated_at": data.get("generated_at"),
                "snapshots":    data.get("snapshots", {}),
                "alerts":       data.get("alerts", []),
                "last_updated": meta["last_updated"],
                "data_source":  "particle_tracker",
            }
        except Exception as e:
            logging.warning(f"[forecast] JSON load error: {e}")
    return {
        "generated_at": None,
        "snapshots":    {},
        "alerts":       [],
        "last_updated": None,
        "data_source":  "fallback",
        "message":      "Forecast file not yet generated — run particle_tracker.py",
    }


# ════════════════════════════════════
# ENDPOINT 6 — Alerts
# ════════════════════════════════════
@app.get("/api/alerts")
def alerts():
    path   = root_path("data", "forecasts", "forecast_latest.json")
    active = []
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            for a in data.get("alerts", []):
                active.append({
                    "zone_name":      a["zone"],
                    "predicted_hour": a["hour"],
                    "particles":      a["particles"],
                    "severity":       "High",
                    "generated_at":   data.get("generated_at"),
                })
        except Exception:
            pass
    return {
        "total_alerts": len(active),
        "checked_at":   datetime.now().isoformat(),
        "alerts":       active,
    }


# ════════════════════════════════════
# ENDPOINT 7 — Beach safety scores
# ════════════════════════════════════
def _cell_count_to_score(cell_count):
    """Simplified SA Health threshold scoring."""
    if cell_count >= 50000:
        return 20.0, "Danger",  "#d32f2f"
    elif cell_count >= 10000:
        return 42.0, "Warning", "#f57c00"
    elif cell_count >= 1000:
        return 65.0, "Caution", "#fbc02d"
    else:
        return 85.0, "Safe",    "#388e3c"


@app.get("/api/beach-safety")
def beach_safety():
    meta = _meta("beach_safety", root_path("data", "beach_safety_scores.json"))

    # ── Primary: compute live from Supabase KareniaReadings ──
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(adapt_sql("""
            SELECT TOP 20
                beach_name,
                latitude,
                longitude,
                cell_count_per_litre,
                severity
            FROM KareniaReadings
            ORDER BY cell_count_per_litre DESC
        """))
        rows = cursor.fetchall()
        conn.close()

        if rows:
            scores = []
            for r in rows:
                cell_count = r[3] or 0
                score, label, color = _cell_count_to_score(cell_count)
                scores.append({
                    "beach":       r[0],
                    "lat":         r[1],
                    "lon":         r[2],
                    "score":       score,
                    "label":       label,
                    "color":       color,
                    "cell_count":  cell_count,
                    "wind_speed":  0,
                    "wind_dir":    0,
                    "sfabi":       0,
                    "data_source": "KareniaReadings",
                })
            return {
                "generated_at": datetime.now().isoformat(),
                "scores":       scores,
                "last_updated": meta["last_updated"],
                "data_source":  "live",
            }
    except Exception:
        pass

    # ── Fallback: read committed JSON file ──
    path = root_path("data", "beach_safety_scores.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["last_updated"] = data.get("generated_at")
            data["data_source"]  = "cached_file"
            return data
        except Exception:
            pass

    return {
        "generated_at": datetime.now().isoformat(),
        "scores":       [],
        "last_updated": None,
        "data_source":  "empty_fallback",
    }


# ════════════════════════════════════
# ENDPOINT 8 — ML prediction
# ════════════════════════════════════
@app.get("/api/predict")
def predict(
    sfabi: float = 0.1,
    sst:   float = 22.0,
    wind:  float = 10.0
):
    if not MODEL:
        return {"error": "Model not loaded"}
    X          = np.array([[wind, 180, sst, 300, 0.5, sfabi, sfabi * 0.8, -34.9, 138.6]])
    pred       = MODEL.predict(X)[0]
    proba      = MODEL.predict_proba(X)[0]
    confidence = round(float(proba.max()) * 100, 1)
    severity   = ENCODER.inverse_transform([pred])[0]
    return {
        "severity":   severity,
        "confidence": confidence,
        "sfabi":      sfabi,
        "sst":        sst,
        "wind":       wind,
    }


# ════════════════════════════════════
# ENDPOINT 9 — Trigger data refresh
# POST /api/refresh
# Header: X-Refresh-Key: <value>
# ════════════════════════════════════
@app.post("/api/refresh")
def trigger_refresh(x_refresh_key: str = Header(default="")):
    if not REFRESH_KEY:
        return {
            "status":  "error",
            "message": "REFRESH_KEY environment variable is not set on this server",
        }
    if x_refresh_key != REFRESH_KEY:
        return {
            "status":  "error",
            "message": "Invalid X-Refresh-Key header",
        }
    if not _REFRESH_AVAILABLE:
        return {
            "status":  "error",
            "message": "refresh_data module not found — check refresh_data.py exists in project root",
        }
    try:
        result = _refresh_module.run_refresh()
        return {"status": "completed", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ════════════════════════════════════
# ENDPOINT 11 — Algal Assistant
# POST /api/algal-assistant
# ════════════════════════════════════
class AssistantRequest(BaseModel):
    question: str


@app.post("/api/algal-assistant")
def algal_assistant(req: AssistantRequest):
    """RAG-powered algal bloom assistant using OpenAI GPT-4o."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {
            "answer": (
                "OPENAI_API_KEY is not set. Please set it as an environment "
                "variable to use the Algal Assistant."
            ),
            "live_data_fetched": False,
        }

    try:
        from algal_assistant.rag_engine import (
            retrieve_context, get_live_context, build_prompt,
        )
        from openai import OpenAI
    except ImportError as e:
        return {
            "answer": (
                f"Algal Assistant dependencies not installed: {e}. "
                "Run: pip install openai chromadb"
            ),
            "live_data_fetched": False,
        }

    live_data = ""
    live_data_fetched = False
    try:
        live_data = get_live_context()
        live_data_fetched = bool(live_data)
    except Exception as e:
        logging.warning(f"[algal-assistant] Live context error: {e}")

    chunks: list = []
    try:
        chunks = retrieve_context(req.question, n=3)
    except Exception as e:
        logging.warning(f"[algal-assistant] RAG retrieval error: {e}")

    try:
        messages = build_prompt(req.question, live_data, chunks)
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=800,
        )
        answer = response.choices[0].message.content
        return {"answer": answer, "live_data_fetched": live_data_fetched}
    except Exception as e:
        logging.error(f"[algal-assistant] OpenAI API error: {e}")
        return {
            "answer": f"The Algal Assistant encountered an error: {e}",
            "live_data_fetched": live_data_fetched,
        }


# ════════════════════════════════════
# ENDPOINT 10 — Refresh status
# GET /api/refresh-status  (public, no auth)
# ════════════════════════════════════
@app.get("/api/refresh-status")
def refresh_status():
    log_path = root_path("data", "refresh_log.json")
    if not os.path.exists(log_path):
        return {
            "last_refresh_attempt": None,
            "sources":              {},
            "checked_at":           datetime.now().isoformat(),
            "message":              "No refresh has run yet",
        }
    try:
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
    except Exception as e:
        return {
            "last_refresh_attempt": None,
            "sources":              {},
            "checked_at":           datetime.now().isoformat(),
            "message":              f"Could not read refresh log: {e}",
        }

    now = datetime.now()
    sources_out = {}
    for key, src in log.get("sources", {}).items():
        entry = {k: v for k, v in src.items() if k != "csv_hash"}  # hide internal hash
        last_success = src.get("last_success")
        if last_success:
            try:
                age_sec = (now - datetime.fromisoformat(last_success)).total_seconds()
                entry["data_age_hours"] = round(age_sec / 3600, 1)
            except Exception:
                entry["data_age_hours"] = None
        sources_out[key] = entry

    return {
        "last_refresh_attempt": log.get("last_refresh_attempt"),
        "sources":              sources_out,
        "checked_at":           now.isoformat(),
    }
