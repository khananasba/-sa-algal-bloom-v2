import numpy as np
import json
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, adapt_sql
import joblib
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder

os.makedirs("ml_engine", exist_ok=True)

def load_db_data():
    """Load weather and karenia data from SQL Server"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(adapt_sql("""
        SELECT TOP 1000
            w.wind_speed,
            w.wind_direction,
            w.sea_surface_temp,
            w.solar_radiation,
            w.wave_height,
            k.cell_count_per_litre,
            k.severity,
            k.latitude,
            k.longitude
        FROM WeatherReadings w
        CROSS JOIN KareniaReadings k
        WHERE w.wind_speed IS NOT NULL
          AND k.severity IS NOT NULL
    """))

    rows = cursor.fetchall()
    conn.close()
    return rows

def load_geojson_indices():
    """Load SFABI and NDCI from the geojson file"""
    path = "data/indices/bloom_heatmap_latest.geojson"
    with open(path) as f:
        data = json.load(f)

    sfabi_vals = []
    ndci_vals  = []
    for feature in data["features"]:
        props = feature["properties"]
        sfabi_vals.append(props.get("sfabi", 0))
        ndci_vals.append(props.get("ndci", 0))

    return sfabi_vals, ndci_vals

def build_training_data(db_rows, sfabi_vals, ndci_vals):
    """
    Combine database readings with satellite indices
    to build the full feature matrix
    """
    np.random.seed(42)
    X = []
    y = []

    # Use real DB rows as base
    for i, row in enumerate(db_rows):
        wind_speed   = row[0] or 0
        wind_dir     = row[1] or 0
        sst          = row[2] or 20
        solar        = row[3] or 200
        wave_height  = row[4] or 0.5
        cell_count   = row[5] or 0
        severity     = row[6]
        lat          = row[7] or -34.9
        lon          = row[8] or 138.6

        # Match nearest SFABI value by index
        idx   = i % len(sfabi_vals)
        sfabi = sfabi_vals[idx]
        ndci  = ndci_vals[idx]

        X.append([
            wind_speed, wind_dir, sst, solar,
            wave_height, sfabi, ndci, lat, lon
        ])
        y.append(severity)

    # Boost with synthetic data to get 800+ samples
    severity_params = {
        "Low":      {"sfabi": (0.05, 0.14), "sst": (18, 22), "cells": (200,  999)},
        "Medium":   {"sfabi": (0.14, 0.24), "sst": (20, 24), "cells": (1000, 9999)},
        "High":     {"sfabi": (0.24, 0.34), "sst": (22, 26), "cells": (10000,49999)},
        "Critical": {"sfabi": (0.34, 0.50), "sst": (24, 28), "cells": (50000,120000)},
    }

    for severity, params in severity_params.items():
        for _ in range(200):
            sfabi = np.random.uniform(*params["sfabi"])
            ndci  = sfabi * np.random.uniform(0.6, 1.2)
            sst   = np.random.uniform(*params["sst"])
            X.append([
                np.random.uniform(5, 35),    # wind_speed
                np.random.uniform(0, 360),   # wind_dir
                sst,
                np.random.uniform(100, 800), # solar
                np.random.uniform(0.2, 2.5), # wave_height
                sfabi,
                ndci,
                np.random.uniform(-36.5, -33.0),  # lat
                np.random.uniform(135.0, 140.5),  # lon
            ])
            y.append(severity)

    return np.array(X), np.array(y)

def train_model(X, y):
    """Train RandomForest classifier"""
    le = LabelEncoder()
    y_encoded = le.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
    )

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        random_state=42,
        class_weight="balanced"
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print("\nClassification Report:")
    print(classification_report(
        y_test, y_pred,
        target_names=le.classes_,
        zero_division=0
    ))

    return model, le

def predict_severity(model, le, features_dict):
    """
    Predict severity for a single location.
    features_dict keys: wind_speed, wind_direction, sea_surface_temp,
                        solar_radiation, wave_height, sfabi, ndci, lat, lon
    """
    X = np.array([[
        features_dict.get("wind_speed",      10),
        features_dict.get("wind_direction",  180),
        features_dict.get("sea_surface_temp", 22),
        features_dict.get("solar_radiation", 300),
        features_dict.get("wave_height",     0.5),
        features_dict.get("sfabi",           0.1),
        features_dict.get("ndci",            0.05),
        features_dict.get("lat",           -34.9),
        features_dict.get("lon",           138.6),
    ]])
    pred       = model.predict(X)[0]
    proba      = model.predict_proba(X)[0]
    confidence = round(float(proba.max()) * 100, 1)
    severity   = le.inverse_transform([pred])[0]
    return severity, confidence

def run():
    print("=== Training Bloom Severity ML Classifier ===\n")

    print("Step 1: Loading data from SQL Server...")
    db_rows = load_db_data()
    print(f"  Loaded {len(db_rows)} rows from database")

    print("Step 2: Loading satellite indices...")
    sfabi_vals, ndci_vals = load_geojson_indices()
    print(f"  Loaded {len(sfabi_vals)} SFABI/NDCI values")

    print("Step 3: Building training dataset...")
    X, y = build_training_data(db_rows, sfabi_vals, ndci_vals)
    print(f"  Training samples: {len(X)}")

    unique, counts = np.unique(y, return_counts=True)
    for cls, cnt in zip(unique, counts):
        print(f"    {cls}: {cnt} samples")

    print("\nStep 4: Training RandomForest model...")
    model, le = train_model(X, y)

    print("Step 5: Saving model...")
    joblib.dump(model, "ml_engine/bloom_model.pkl")
    joblib.dump(le,    "ml_engine/label_encoder.pkl")
    print("  Saved ml_engine/bloom_model.pkl")
    print("  Saved ml_engine/label_encoder.pkl")

    print("\nStep 6: Test prediction for Adelaide coast...")
    test_input = {
        "wind_speed":      22.5,
        "wind_direction":  195,
        "sea_surface_temp": 24.3,
        "solar_radiation": 520,
        "wave_height":     1.2,
        "sfabi":           0.31,
        "ndci":            0.22,
        "lat":            -34.9,
        "lon":            138.6
    }
    severity, confidence = predict_severity(model, le, test_input)
    print(f"  Input SFABI=0.31, SST=24.3°C, Wind=22.5 km/h")
    print(f"  Predicted: {severity}  (confidence: {confidence}%)")

    print("\n=== ML Classifier DONE ===")
    print("Ready for Step 8 — Particle Tracker")

if __name__ == "__main__":
    run()
