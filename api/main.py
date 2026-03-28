import json
import os
import sys
import joblib
import numpy as np
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db_config import get_connection, adapt_sql

app = FastAPI(title="SA Algal Bloom Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Load ML model once at startup ──
MODEL = None
ENCODER = None

def load_model():
    global MODEL, ENCODER
    try:
        MODEL   = joblib.load("ml_engine/bloom_model.pkl")
        ENCODER = joblib.load("ml_engine/label_encoder.pkl")
        print("ML model loaded OK")
    except Exception as e:
        print(f"Model load warning: {e}")

load_model()

# ════════════════════════════════════
# ENDPOINT 1 — Health check
# ════════════════════════════════════
@app.get("/api/health")
def health():
    return {
        "status":    "ok",
        "timestamp": datetime.now().isoformat(),
        "model":     "loaded" if MODEL else "not loaded"
    }

# ════════════════════════════════════
# ENDPOINT 2 — Bloom heatmap
# ════════════════════════════════════
@app.get("/api/bloom-heatmap")
def bloom_heatmap():
    path = "data/indices/bloom_heatmap_latest.geojson"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"type": "FeatureCollection", "features": []}

# ════════════════════════════════════
# ENDPOINT 3 — Cell counts
# ════════════════════════════════════
@app.get("/api/cell-counts")
def cell_counts():
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
        return [
            {
                "beach_name":          r[0],
                "latitude":            r[1],
                "longitude":           r[2],
                "cell_count_per_litre": r[3],
                "severity":            r[4],
                "recorded_at":         r[5].isoformat() if r[5] else None
            }
            for r in rows
        ]
    except Exception as e:
        return {"error": str(e)}

# ════════════════════════════════════
# ENDPOINT 4 — Weather
# ════════════════════════════════════
@app.get("/api/weather")
def weather():
    try:
        conn   = get_connection()
        cursor = conn.cursor()
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
        return [
            {
                "location_name":   r[0],
                "latitude":        r[1],
                "longitude":       r[2],
                "wind_speed":      r[3],
                "wind_direction":  r[4],
                "sea_surface_temp": r[5],
                "solar_radiation": r[6],
                "wave_height":     r[7],
                "recorded_at":     r[8].isoformat() if r[8] else None
            }
            for r in rows
        ]
    except Exception as e:
        return {"error": str(e)}

# ════════════════════════════════════
# ENDPOINT 5 — 72hr forecast
# ════════════════════════════════════
@app.get("/api/forecast/72hr")
def forecast_72hr():
    path = "data/forecasts/forecast_latest.json"
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        return {
            "generated_at": data.get("generated_at"),
            "snapshots":    data.get("snapshots", {}),
            "alerts":       data.get("alerts", [])
        }
    return {"error": "No forecast available yet"}

# ════════════════════════════════════
# ENDPOINT 6 — Alerts
# ════════════════════════════════════
@app.get("/api/alerts")
def alerts():
    path = "data/forecasts/forecast_latest.json"
    active = []

    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        raw_alerts = data.get("alerts", [])
        for a in raw_alerts:
            active.append({
                "zone_name":       a["zone"],
                "predicted_hour":  a["hour"],
                "particles":       a["particles"],
                "severity":        "High",
                "generated_at":    data.get("generated_at")
            })

    return {
        "total_alerts": len(active),
        "checked_at":   datetime.now().isoformat(),
        "alerts":       active
    }

# ════════════════════════════════════
# ENDPOINT 7 — Predict severity
# ════════════════════════════════════
@app.get("/api/beach-safety")
def beach_safety():
    import os
    path="data/beach_safety_scores.json"
    if os.path.exists(path):
        with open(path,encoding='utf-8') as f:
            return json.load(f)
    return {"error":"Run beach_safety_score.py first"}

@app.get("/api/predict")
def predict(
    sfabi: float = 0.1,
    sst:   float = 22.0,
    wind:  float = 10.0
):
    if not MODEL:
        return {"error": "Model not loaded"}
    X = np.array([[wind, 180, sst, 300, 0.5, sfabi, sfabi*0.8, -34.9, 138.6]])
    pred       = MODEL.predict(X)[0]
    proba      = MODEL.predict_proba(X)[0]
    confidence = round(float(proba.max()) * 100, 1)
    severity   = ENCODER.inverse_transform([pred])[0]
    return {
        "severity":   severity,
        "confidence": confidence,
        "sfabi":      sfabi,
        "sst":        sst,
        "wind":       wind
    }