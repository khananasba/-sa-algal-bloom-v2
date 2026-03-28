import numpy as np
import json
import os
from datetime import datetime, timedelta

os.makedirs("data/ocean", exist_ok=True)

# SA coastline grid
LAT_MIN, LAT_MAX = -37.0, -32.0
LON_MIN, LON_MAX = 135.0, 141.0
LAT_POINTS  = 50
LON_POINTS  = 60
TIME_STEPS  = 120  # 5 days x 24 hours

def generate_ocean_currents():
    """
    Generates realistic SA gulf ocean current data.
    Simulates Spencer Gulf and St Vincent Gulf circulation patterns.
    """
    np.random.seed(99)

    lats = np.linspace(LAT_MIN, LAT_MAX, LAT_POINTS)
    lons = np.linspace(LON_MIN, LON_MAX, LON_POINTS)

    # U = eastward velocity (m/s), V = northward velocity (m/s)
    U = np.zeros((TIME_STEPS, LAT_POINTS, LON_POINTS))
    V = np.zeros((TIME_STEPS, LAT_POINTS, LON_POINTS))

    for t in range(TIME_STEPS):
        # Base tidal oscillation
        tidal_phase = 2 * np.pi * t / 12.4  # 12.4 hour tidal cycle
        tidal_u = 0.15 * np.sin(tidal_phase)
        tidal_v = 0.10 * np.cos(tidal_phase)

        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                # Spencer Gulf — northward flow
                if 136.5 <= lon <= 137.5 and -35.5 <= lat <= -33.0:
                    U[t,i,j] = tidal_u + np.random.normal(0.02, 0.05)
                    V[t,i,j] = tidal_v + 0.08 + np.random.normal(0, 0.04)

                # St Vincent Gulf — variable flow near Adelaide
                elif 138.0 <= lon <= 138.8 and -35.5 <= lat <= -34.5:
                    U[t,i,j] = tidal_u - 0.05 + np.random.normal(0, 0.04)
                    V[t,i,j] = tidal_v + np.random.normal(0.02, 0.03)

                # Open coast — southward coastal current
                elif lon >= 138.5:
                    U[t,i,j] = tidal_u + 0.04 + np.random.normal(0, 0.03)
                    V[t,i,j] = tidal_v - 0.06 + np.random.normal(0, 0.03)

                # Default open water
                else:
                    U[t,i,j] = tidal_u + np.random.normal(0, 0.03)
                    V[t,i,j] = tidal_v + np.random.normal(0, 0.03)

    return U, V, lats, lons

def save_as_json(U, V, lats, lons):
    """Save as JSON since NetCDF install can be tricky on Windows"""
    now = datetime.now()
    times = [(now - timedelta(hours=TIME_STEPS - t)).isoformat()
             for t in range(TIME_STEPS)]

    data = {
        "metadata": {
            "source":       "eSA-Marine synthetic (replace with OPeNDAP)",
            "generated_at": now.isoformat(),
            "lat_min":  LAT_MIN,  "lat_max":  LAT_MAX,
            "lon_min":  LON_MIN,  "lon_max":  LON_MAX,
            "time_steps": TIME_STEPS,
            "lat_points": LAT_POINTS,
            "lon_points": LON_POINTS
        },
        "lats":  lats.tolist(),
        "lons":  lons.tolist(),
        "times": times,
        "U":     U.tolist(),
        "V":     V.tolist()
    }

    path = "data/ocean/currents.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return path

def print_summary(U, V):
    print(f"  U (eastward)  min={U.min():.3f}  max={U.max():.3f}  mean={U.mean():.3f} m/s")
    print(f"  V (northward) min={V.min():.3f}  max={V.max():.3f}  mean={V.mean():.3f} m/s")

    # Show current direction at Adelaide coast
    # Adelaide ~ lat index 30, lon index 42
    u_adl = U[:, 30, 42].mean()
    v_adl = V[:, 30, 42].mean()
    speed = np.sqrt(u_adl**2 + v_adl**2)
    print(f"\n  Adelaide coastal average current:")
    print(f"    Speed:     {speed:.3f} m/s ({speed*100:.1f} cm/s)")
    print(f"    Direction: U={u_adl:.3f} V={v_adl:.3f}")

def run():
    print("=== Generating SA Ocean Current Data ===\n")

    print("Simulating Spencer Gulf + St Vincent Gulf circulation...")
    print(f"Grid: {TIME_STEPS} time steps x {LAT_POINTS} lat x {LON_POINTS} lon\n")

    U, V, lats, lons = generate_ocean_currents()

    print("Current velocity summary:")
    print_summary(U, V)

    print("\nSaving to data/ocean/currents.json...")
    path = save_as_json(U, V, lats, lons)

    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"Saved {path}  ({size_mb:.1f} MB)")

    print("\n=== Ocean currents DONE ===")
    print("Ready for Step 7 — ML Classifier")

if __name__ == "__main__":
    run()