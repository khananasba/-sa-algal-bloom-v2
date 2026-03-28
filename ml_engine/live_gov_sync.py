import requests
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, ph
import json
from datetime import datetime

def test_full_fetch():
    print('--- TARGETING WHOLE DATASET (V2) ---')
    url = 'https://services6.arcgis.com/WS2XycMNFieWAsfS/arcgis/rest/services/HarmfulAlgalBloom_MonitoringSites/FeatureServer/0/query'
    params = {'f': 'json', 'where': "Status = 'Sampled'", 'outFields': '*', 'returnGeometry': 'false'}
    try:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        features = data.get('features', [])
        if not features:
            print('Fail: No data found.'); return

        print(f'Success! Found {len(features)} records.')
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM KareniaReadings')
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for feat in features:
            a = feat['attributes']
            # Map ArcGIS fields: Note 'Site_Name' might be 'SiteName' or 'Location'
            name = a.get('Site_Name') or a.get('SiteName') or 'Unknown Site'
            count = a.get('Karenia_spp_Cells_L') or 0
            lat = a.get('Latitude') or 0
            lon = a.get('Longitude') or 0
            
            # Added recorded_at to satisfy your DB constraint
            cur.execute(f"INSERT INTO KareniaReadings (beach_name, cell_count_per_litre, latitude, longitude, recorded_at) VALUES ({ph(5)})",
                (name, count, lat, lon, now))

        conn.commit()
        conn.close()
        print(f'DONE: Updated {len(features)} records in AlgalBloomDB.')
    except Exception as e:
        print(f'Critical Error: {e}')

if __name__ == '__main__':
    test_full_fetch()
