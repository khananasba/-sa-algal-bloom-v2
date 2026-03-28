import numpy as np
import json
import os
from datetime import datetime

# Create output folders
os.makedirs("data/satellite", exist_ok=True)
os.makedirs("data/indices",   exist_ok=True)

# SA Coastline bounding box
LAT_MIN, LAT_MAX = -36.5, -33.0
LON_MIN, LON_MAX = 135.0, 140.5
GRID_ROWS, GRID_COLS = 50, 60

def generate_dummy_bands():
    """
    Generates realistic Sentinel-2 band arrays for SA coastline.
    Simulates the actual 2024-2026 bloom pattern near Adelaide metro coast.
    """
    np.random.seed(42)
    shape = (GRID_ROWS, GRID_COLS)

    # Base water reflectance
    B2  = np.random.uniform(0.02, 0.06, shape)  # Blue
    B3  = np.random.uniform(0.03, 0.07, shape)  # Green
    B4  = np.random.uniform(0.02, 0.05, shape)  # Red
    B6  = np.random.uniform(0.01, 0.04, shape)  # Red Edge 1
    B7  = np.random.uniform(0.01, 0.04, shape)  # Red Edge 2
    B8  = np.random.uniform(0.01, 0.03, shape)  # NIR
    B8A = np.random.uniform(0.01, 0.03, shape)  # Narrow NIR
    B11 = np.random.uniform(0.01, 0.02, shape)  # SWIR1
    B12 = np.random.uniform(0.01, 0.02, shape)  # SWIR2

    # Inject bloom signal near Adelaide metro coast
    # Adelaide is roughly at lat -34.9, lon 138.6
    # In our grid: row ~30, cols 40-55
    for row in range(25, 42):
        for col in range(38, 58):
            intensity = np.random.uniform(0.4, 0.9)
            B6[row, col]  += 0.25 * intensity
            B7[row, col]  += 0.28 * intensity
            B8[row, col]  += 0.20 * intensity
            B8A[row, col] += 0.22 * intensity
            B2[row, col]  -= 0.01 * intensity
            B3[row, col]  += 0.03 * intensity

    # Smaller bloom patch near Victor Harbor (row ~38, col 42-50)
    for row in range(36, 42):
        for col in range(40, 50):
            intensity = np.random.uniform(0.2, 0.5)
            B6[row, col]  += 0.12 * intensity
            B7[row, col]  += 0.14 * intensity

    return B2, B3, B4, B6, B7, B8, B8A, B11, B12

def compute_sfabi(B2, B3, B6, B7, B12):
    """
    Sentinel-2 Floating Algal Bloom Index
    High values = floating algal bloom present
    """
    numerator   = (B6 + B7) - (B2 + B3 + B12)
    denominator = (B6 + B7) + (B2 + B3 + B12)
    denominator = np.where(denominator == 0, 1e-10, denominator)
    return numerator / denominator

def compute_ndci(B4, B8A):
    """
    Normalized Difference Chlorophyll Index
    High values = high chlorophyll = bloom
    """
    numerator   = B8A - B4
    denominator = B8A + B4
    denominator = np.where(denominator == 0, 1e-10, denominator)
    return numerator / denominator

def classify_severity(sfabi_value):
    if sfabi_value < 0.05:
        return "no_bloom"
    elif sfabi_value < 0.15:
        return "Low"
    elif sfabi_value < 0.30:
        return "Medium"
    else:
        return "High"

def arrays_to_geojson(sfabi, ndci):
    """Convert index arrays to GeoJSON for the dashboard"""
    lats = np.linspace(LAT_MIN, LAT_MAX, GRID_ROWS)
    lons = np.linspace(LON_MIN, LON_MAX, GRID_COLS)

    features = []
    cell_lat = (LAT_MAX - LAT_MIN) / GRID_ROWS
    cell_lon = (LON_MAX - LON_MIN) / GRID_COLS

    for i in range(GRID_ROWS):
        for j in range(GRID_COLS):
            sfabi_val = float(sfabi[i, j])
            ndci_val  = float(ndci[i, j])
            severity  = classify_severity(sfabi_val)

            if severity == "no_bloom":
                continue  # skip empty cells to keep file small

            lat = float(lats[i])
            lon = float(lons[j])

            # Make a small polygon for each cell
            polygon_coords = [[
                [lon,            lat],
                [lon + cell_lon, lat],
                [lon + cell_lon, lat + cell_lat],
                [lon,            lat + cell_lat],
                [lon,            lat]
            ]]

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": polygon_coords
                },
                "properties": {
                    "sfabi":    round(sfabi_val, 4),
                    "ndci":     round(ndci_val, 4),
                    "severity": severity,
                    "lat":      round(lat, 4),
                    "lon":      round(lon, 4),
                    "date":     datetime.now().strftime("%Y-%m-%d")
                }
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "source": "Sentinel-2 SFABI (dummy data — replace with GEE)",
            "total_cells": len(features)
        }
    }

def run():
    print("=== Computing Satellite Spectral Indices ===\n")

    print("Generating SA coastline band arrays...")
    B2, B3, B4, B6, B7, B8, B8A, B11, B12 = generate_dummy_bands()

    # Save raw bands
    np.savez(
        "data/satellite/bands_latest.npz",
        B2=B2, B3=B3, B4=B4,
        B6=B6, B7=B7, B8=B8,
        B8A=B8A, B11=B11, B12=B12
    )
    print("Raw bands saved to data/satellite/bands_latest.npz")

    print("Computing SFABI...")
    sfabi = compute_sfabi(B2, B3, B6, B7, B12)
    print(f"  SFABI min={sfabi.min():.4f}  max={sfabi.max():.4f}  mean={sfabi.mean():.4f}")

    print("Computing NDCI...")
    ndci = compute_ndci(B4, B8A)
    print(f"  NDCI  min={ndci.min():.4f}  max={ndci.max():.4f}  mean={ndci.mean():.4f}")

    print("Classifying severity grid...")
    severity_counts = {}
    for val in sfabi.flatten():
        s = classify_severity(val)
        severity_counts[s] = severity_counts.get(s, 0) + 1

    for sev, cnt in sorted(severity_counts.items()):
        pct = cnt / sfabi.size * 100
        print(f"  {sev}: {cnt} cells ({pct:.1f}%)")

    print("\nConverting to GeoJSON...")
    geojson = arrays_to_geojson(sfabi, ndci)
    out_path = "data/indices/bloom_heatmap_latest.geojson"
    with open(out_path, "w") as f:
        json.dump(geojson, f)
    print(f"Saved {len(geojson['features'])} bloom cells to {out_path}")

    print("\n=== Spectral indices DONE ===")
    print("Ready for Step 6 — Ocean Currents")

if __name__ == "__main__":
    run()