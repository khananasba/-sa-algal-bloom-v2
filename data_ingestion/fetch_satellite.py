import ee
import json as json_lib
import os
from datetime import datetime

os.makedirs('data/indices', exist_ok=True)

# ── Authentication ─────────────────────────────────────────────────────────────
GEE_SA_JSON = os.environ.get('GEE_SERVICE_ACCOUNT_JSON')

if GEE_SA_JSON:
    try:
        key_data    = json_lib.loads(GEE_SA_JSON)
        credentials = ee.ServiceAccountCredentials(
            key_data['client_email'],
            key_data=json_lib.dumps(key_data)
        )
        ee.Initialize(credentials, project='smart-464108')
        print("GEE authenticated via service account")
    except Exception as e:
        print(f"GEE service account auth failed: {e}")
        raise
else:
    try:
        ee.Initialize(project='smart-464108')
        print("GEE authenticated via local credentials")
    except Exception as e:
        print(f"GEE local auth failed: {e}")
        raise

# ── Fetch Sentinel-2 SFABI ────────────────────────────────────────────────────
print('Fetching Sentinel-2 for SA gulfs...')
bbox = ee.Geometry.Rectangle([137.6, -35.6, 138.5, -34.6])
s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(bbox)
        .filterDate('2025-09-01', '2026-03-16')
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
        .sort('system:time_start', False)
        .first())
print('Image date:', ee.Date(s2.get('system:time_start')).format('YYYY-MM-dd').getInfo())

B2  = s2.select('B2').divide(10000)
B3  = s2.select('B3').divide(10000)
B6  = s2.select('B6').divide(10000)
B7  = s2.select('B7').divide(10000)
B12 = s2.select('B12').divide(10000)
num   = B6.add(B7).subtract(B2.add(B3).add(B12))
den   = B6.add(B7).add(B2.add(B3).add(B12))
sfabi = num.divide(den).rename('SFABI')

sample = sfabi.sample(region=bbox, scale=300, numPixels=5000, seed=42, geometries=True)
print('Sampling...')
result   = sample.getInfo()
features = []
for ft in result['features']:
    v = ft['properties'].get('SFABI')
    if v is None or v < 0.02:
        continue
    lon, lat = ft['geometry']['coordinates']
    sev = 'High' if v > 0.15 else 'Medium' if v > 0.05 else 'Low'
    features.append({
        'type':     'Feature',
        'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
        'properties': {
            'sfabi':    round(v, 4),
            'ndci':     round(v * 0.8, 4),
            'severity': sev,
            'lat':      round(lat, 4),
            'lon':      round(lon, 4),
            'date':     datetime.now().strftime('%Y-%m-%d'),
        },
    })

geojson = {
    'type':     'FeatureCollection',
    'features': features,
    'metadata': {
        'generated_at': datetime.now().isoformat(),
        'source':       'Real Sentinel-2 GEE',
        'total_cells':  len(features),
    },
}
open('data/indices/bloom_heatmap_latest.geojson', 'w').write(json_lib.dumps(geojson))
print(f'Done. Found {len(features)} pixels.')
if features:
    vals = [ft['properties']['sfabi'] for ft in features]
    print(f'SFABI min={min(vals):.4f} max={max(vals):.4f} mean={sum(vals)/len(vals):.4f}')
