import ee
import json as json_lib
import os
from datetime import datetime, date, timedelta

os.makedirs('data/indices', exist_ok=True)

# ── Authentication ─────────────────────────────────────────────────────────────
GEE_SA_JSON = os.environ.get('GEE_SERVICE_ACCOUNT_JSON')

print(f"GEE_SERVICE_ACCOUNT_JSON present: {bool(GEE_SA_JSON)}")

if GEE_SA_JSON:
    try:
        key_data = json_lib.loads(GEE_SA_JSON)
        print(f"JSON parsed OK. client_email: {key_data.get('client_email')}")
        print(f"JSON preview (first 50 chars): {GEE_SA_JSON[:50]}")
        credentials = ee.ServiceAccountCredentials(
            key_data['client_email'],
            key_data=json_lib.dumps(key_data)
        )
        ee.Initialize(credentials, project='smart-464108')
        print("GEE authenticated via service account")
    except Exception as e:
        print(f"GEE service account auth failed: {type(e).__name__}: {e}")
        raise
else:
    try:
        ee.Initialize(project='smart-464108')
        print("GEE authenticated via local credentials")
    except Exception as e:
        print(f"GEE local auth failed: {type(e).__name__}: {e}")
        raise

# ── Fetch Sentinel-2 SFABI ────────────────────────────────────────────────────
print('Fetching Sentinel-2 for SA gulfs...')
start_date = (date.today() - timedelta(days=180)).strftime('%Y-%m-%d')
end_date = date.today().strftime('%Y-%m-%d')
print(f'Date range: {start_date} to {end_date}')

# Full SA coastline: covers Spencer Gulf, Port Lincoln, Adelaide coast, Goolwa
bbox = ee.Geometry.Rectangle([135.3, -36.2, 139.0, -33.8])

# We get candidate images with up to 70% clouds, sorted by date (newest first)
collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(bbox)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 70))
        .sort('system:time_start', False))

img_count = collection.size().getInfo()
print(f'Found {img_count} images in collection with <70% cloud cover')

if img_count == 0:
    print('No images found with <70% cloud cover — raising threshold to 90%')
    collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(bbox)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 90))
            .sort('system:time_start', False))
    img_count = collection.size().getInfo()
    print(f'Found {img_count} images with <90% cloud cover')

# Limit scanning to the 20 most recent images to find one with high-quality bloom data (>= 30 pixels)
candidate_list = collection.limit(20).getInfo().get('features', [])
print(f'Scanning up to {len(candidate_list)} recent images for cloud-free water pixels...')

best_features = []
best_image_date = None
best_image_id = None

for img_meta in candidate_list:
    img_id = img_meta['id']
    img_time = datetime.fromtimestamp(img_meta['properties']['system:time_start'] / 1000)
    img_date_str = img_time.strftime('%Y-%m-%d')
    cloud_pct = img_meta['properties']['CLOUDY_PIXEL_PERCENTAGE']
    
    print(f"Checking image {img_id} from {img_date_str} (Cloud cover: {cloud_pct:.1f}%)")
    
    try:
        s2 = ee.Image(img_id)
        B2  = s2.select('B2').divide(10000)
        B3  = s2.select('B3').divide(10000)
        B6  = s2.select('B6').divide(10000)
        B7  = s2.select('B7').divide(10000)
        B12 = s2.select('B12').divide(10000)
        
        num   = B6.add(B7).subtract(B2.add(B3).add(B12))
        den   = B6.add(B7).add(B2.add(B3).add(B12))
        sfabi = num.divide(den).rename('SFABI')
        
        B8 = s2.select('B8').divide(10000)
        ndwi = B3.subtract(B8).divide(B3.add(B8))
        water_mask = ndwi.gt(-0.15)
        sfabi = sfabi.updateMask(water_mask)
        
        sample = sfabi.sample(region=bbox, scale=300, numPixels=5000, seed=42, geometries=True)
        result = sample.getInfo()
        
        img_features = []
        for ft in result['features']:
            v = ft['properties'].get('SFABI')
            if v is None or v < 0.01:
                continue
            lon, lat = ft['geometry']['coordinates']
            sev = 'High' if v > 0.15 else 'Medium' if v > 0.05 else 'Low'
            img_features.append({
                'type':     'Feature',
                'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                'properties': {
                    'sfabi':    round(v, 4),
                    'ndci':     round(v * 0.8, 4),
                    'severity': sev,
                    'lat':      round(lat, 4),
                    'lon':      round(lon, 4),
                    'date':     img_date_str,
                },
            })
            
        print(f"  -> Found {len(img_features)} pixels")
        
        # Track the image with the most pixels in case we don't hit the threshold
        if len(img_features) > len(best_features):
            best_features = img_features
            best_image_date = img_date_str
            best_image_id = img_id
            
        # If we found a good clear image with >= 30 pixels, stop searching!
        if len(img_features) >= 30:
            print(f"  -> Found clear image with {len(img_features)} pixels. Stopping search.")
            break
            
    except Exception as e:
        print(f"  -> Failed to process image: {e}")
        continue

# Fallback: if no individual image had >= 30 pixels but we found a 30-day median composite
if len(best_features) < 10:
    print(f"All individual images had very few clear pixels (max: {len(best_features)}). Creating 30-day median composite...")
    try:
        composite_start = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
        s2 = collection.filterDate(composite_start, end_date).median()
        
        B2  = s2.select('B2').divide(10000)
        B3  = s2.select('B3').divide(10000)
        B6  = s2.select('B6').divide(10000)
        B7  = s2.select('B7').divide(10000)
        B12 = s2.select('B12').divide(10000)
        
        num   = B6.add(B7).subtract(B2.add(B3).add(B12))
        den   = B6.add(B7).add(B2.add(B3).add(B12))
        sfabi = num.divide(den).rename('SFABI')
        
        B8 = s2.select('B8').divide(10000)
        ndwi = B3.subtract(B8).divide(B3.add(B8))
        water_mask = ndwi.gt(-0.15)
        sfabi = sfabi.updateMask(water_mask)
        
        sample = sfabi.sample(region=bbox, scale=300, numPixels=5000, seed=42, geometries=True)
        result = sample.getInfo()
        
        comp_features = []
        for ft in result['features']:
            v = ft['properties'].get('SFABI')
            if v is None or v < 0.01:
                continue
            lon, lat = ft['geometry']['coordinates']
            sev = 'High' if v > 0.15 else 'Medium' if v > 0.05 else 'Low'
            comp_features.append({
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
        print(f"Composite yielded {len(comp_features)} pixels.")
        if len(comp_features) > len(best_features):
            best_features = comp_features
            best_image_date = datetime.now().strftime('%Y-%m-%d')
            best_image_id = "30-day composite"
    except Exception as e:
        print(f"Composite build failed: {e}")

features = best_features
selected_date = best_image_date or datetime.now().strftime('%Y-%m-%d')

# Safeguard: Do not overwrite with a low-quality/cloudy run if we have a better existing heatmap
out_path = 'data/indices/bloom_heatmap_latest.geojson'
if os.path.exists(out_path):
    try:
        existing_data = json_lib.loads(open(out_path).read())
        existing_features = existing_data.get('features', [])
        # If existing has at least 15 pixels and new has fewer than 15, retain existing
        if len(existing_features) >= 15 and len(features) < 15:
            print(f"[SAFEGUARD] Retaining existing heatmap ({len(existing_features)} pixels from {existing_data.get('metadata', {}).get('last_pass', 'unknown')}) instead of overwriting with cloudy run ({len(features)} pixels).")
            # We exit successfully without overwriting the file
            import sys
            sys.exit(0)
    except Exception as e:
        print(f"Error checking existing heatmap safeguard: {e}")

geojson = {
    'type':     'FeatureCollection',
    'features': features,
    'metadata': {
        'generated_at': datetime.now().isoformat(),
        'source':       'Real Sentinel-2 GEE',
        'total_cells':  len(features),
        'last_pass':    selected_date,
        'image_id':     best_image_id or "unknown"
    },
}

open(out_path, 'w').write(json_lib.dumps(geojson))
print(f'Done. Saved {len(features)} pixels from pass date {selected_date}.')
if features:
    vals = [ft['properties']['sfabi'] for ft in features]
    print(f'SFABI min={min(vals):.4f} max={max(vals):.4f} mean={sum(vals)/len(vals):.4f}')
