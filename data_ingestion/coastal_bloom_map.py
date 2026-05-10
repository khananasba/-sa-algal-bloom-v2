import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, adapt_sql
import json
import numpy as np
from scipy.interpolate import RBFInterpolator
from datetime import datetime

os.makedirs('data/indices', exist_ok=True)

def run() -> None:
    """
    Generate bloom_heatmap_latest.geojson using RBF interpolation.

    Queries the latest reading PER BEACH from KareniaReadings (all 509 sites),
    interpolates onto 52 coastal grid points covering Adelaide metro coast,
    Fleurieu Peninsula, and Spencer Gulf (Port Hughes / Port Lincoln area).
    """
    print('Loading latest cell count per beach from database...')
    conn = get_connection()
    cursor = conn.cursor()
    # Get latest reading per beach — not just the global MAX(recorded_at)
    # which would return only the 3 beaches sampled on the most recent day.
    cursor.execute(adapt_sql("""
        SELECT r.beach_name, r.latitude, r.longitude, r.cell_count_per_litre
        FROM KareniaReadings r
        INNER JOIN (
            SELECT beach_name, MAX(recorded_at) AS max_date
            FROM KareniaReadings
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            GROUP BY beach_name
        ) latest
          ON r.beach_name = latest.beach_name
         AND r.recorded_at = latest.max_date
        WHERE r.latitude IS NOT NULL AND r.longitude IS NOT NULL
    """))
    rows = cursor.fetchall()
    conn.close()
    print(f'Loaded {len(rows)} beach readings (latest per beach)')

    if not rows:
        print('ERROR: no readings returned — aborting')
        return

    beach_lats = [float(r[1]) for r in rows]
    beach_lons = [float(r[2]) for r in rows]
    beach_vals = [float(r[3]) for r in rows]

    # 52 coastal grid points — Adelaide metro + Fleurieu + Spencer Gulf
    COASTAL_POINTS = [
        # ── Adelaide metro coast (north → south) ──────────────────────────────
        (-34.780, 138.489), (-34.804, 138.479), (-34.805, 138.515),
        (-34.838, 138.482), (-34.858, 138.487), (-34.875, 138.490),
        (-34.905, 138.495), (-34.921, 138.497), (-34.940, 138.502),
        (-34.980, 138.516), (-35.005, 138.519), (-35.033, 138.517),
        (-35.069, 138.504), (-35.090, 138.499), (-35.110, 138.485),
        (-35.142, 138.467), (-35.180, 138.462), (-35.229, 138.463),
        (-35.278, 138.456), (-35.338, 138.449), (-35.390, 138.440),
        # ── Fleurieu / Goolwa ─────────────────────────────────────────────────
        (-35.440, 138.316), (-35.500, 138.320), (-35.552, 138.617),
        (-35.529, 138.683), (-35.515, 138.700), (-35.501, 138.743),
        (-35.480, 138.760), (-35.460, 138.780), (-35.550, 138.500),
        (-35.580, 138.480),
        # ── Spencer Gulf — Yorke Peninsula (east) coast ───────────────────────
        (-33.926, 137.618), (-34.075, 137.540), (-34.250, 137.550),
        (-34.495, 137.480), (-34.700, 137.380), (-35.000, 137.200),
        (-35.200, 137.150), (-35.350, 136.900),
        # ── Spencer Gulf — Eyre Peninsula (west) coast ────────────────────────
        (-34.730, 135.860), (-34.600, 135.950), (-34.450, 136.100),
        (-34.200, 136.400), (-34.000, 136.900),
        # ── Upper Spencer Gulf ─────────────────────────────────────────────────
        (-33.800, 137.800), (-33.650, 137.900), (-33.500, 137.700),
        (-33.200, 137.800),
        # ── Kangaroo Island channel ────────────────────────────────────────────
        (-35.650, 138.100), (-35.700, 137.800), (-35.750, 137.400),
    ]

    points = np.array([[lat, lon] for lat, lon in zip(beach_lats, beach_lons)])
    values = np.array(beach_vals)
    query  = np.array(COASTAL_POINTS)

    print(f'Running RBF interpolation ({len(COASTAL_POINTS)} grid points, {len(rows)} input sites)...')
    rbf = RBFInterpolator(points, values, kernel='thin_plate_spline', smoothing=1.0)
    interpolated = rbf(query)

    def get_severity(v: float) -> str:
        """Map cell count to SA Health severity label."""
        if v >= 50000:
            return 'Critical'
        elif v >= 10000:
            return 'High'
        elif v >= 1000:
            return 'Medium'
        return 'Low'

    features = []
    for i, (lat, lon) in enumerate(COASTAL_POINTS):
        v    = max(0.0, float(interpolated[i]))
        sev  = get_severity(v)
        sfabi = min(0.8, v / 100000)
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [round(lon, 5), round(lat, 5)],
            },
            'properties': {
                'sfabi':      round(sfabi, 4),
                'ndci':       round(sfabi * 0.8, 4),
                'severity':   sev,
                'cell_count': round(v, 0),
                'lat':        round(lat, 5),
                'lon':        round(lon, 5),
                'date':       datetime.now().strftime('%Y-%m-%d'),
            },
        })

    geojson = {
        'type': 'FeatureCollection',
        'features': features,
        'metadata': {
            'generated_at':  datetime.now().isoformat(),
            'source':        'RBF interpolation from SA Government beach readings',
            'input_beaches': len(rows),
            'total_cells':   len(features),
        },
    }
    out_path = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..')),
        'data', 'indices', 'bloom_heatmap_latest.geojson',
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as fp:
        json.dump(geojson, fp)

    print(f'Done. Generated {len(features)} coastal bloom grid points.')
    print(f'Output: {out_path}')
    print('Severity breakdown:')
    from collections import Counter
    sevs = Counter(ft['properties']['severity'] for ft in features)
    for k, v_count in sorted(sevs.items()):
        print(f'  {k}: {v_count}')
    vals = [ft['properties']['cell_count'] for ft in features]
    print(f'Cell count range: {min(vals):.0f} – {max(vals):.0f} cells/L')


if __name__ == '__main__':
    run()
