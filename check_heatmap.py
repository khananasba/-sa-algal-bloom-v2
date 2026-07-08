import json
data = json.load(open('data/indices/bloom_heatmap_latest.geojson'))
feats = data.get('features', [])
meta = data.get('metadata', {})
print(f"Features: {len(feats)}")
print(f"Source: {meta.get('source', 'unknown')}")
print(f"Generated: {meta.get('generated_at', 'unknown')}")
if feats:
    vals = [f['properties'].get('sfabi', 0) for f in feats if f['properties'].get('sfabi') is not None]
    if vals:
        print(f"SFABI: min={min(vals):.4f} max={max(vals):.4f} mean={sum(vals)/len(vals):.4f}")
