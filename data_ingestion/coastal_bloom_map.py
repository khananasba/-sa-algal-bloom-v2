import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection
import json
import numpy as np
from scipy.interpolate import RBFInterpolator
from datetime import datetime

os.makedirs('data/indices',exist_ok=True)

print('Loading cell counts from SQL Server...')
conn=get_connection()
cursor=conn.cursor()
cursor.execute('SELECT beach_name,latitude,longitude,cell_count_per_litre FROM KareniaReadings WHERE recorded_at=(SELECT MAX(recorded_at) FROM KareniaReadings)')
rows=cursor.fetchall()
conn.close()
print(f'Loaded {len(rows)} beach readings')

beach_lats=[r[1] for r in rows]
beach_lons=[r[2] for r in rows]
beach_vals=[float(r[3]) for r in rows]

COASTAL_POINTS=[
(-34.805,138.515),(-34.838,138.482),(-34.875,138.490),(-34.905,138.495),
(-34.921,138.497),(-34.940,138.502),(-34.980,138.516),(-35.005,138.519),
(-35.033,138.517),(-35.069,138.504),(-35.090,138.499),(-35.110,138.485),
(-35.142,138.467),(-35.180,138.462),(-35.229,138.463),(-35.278,138.456),
(-35.338,138.449),(-35.390,138.440),(-35.440,138.316),(-35.500,138.320),
(-35.552,138.617),(-35.529,138.683),(-35.515,138.700),(-35.501,138.743),
(-35.480,138.760),(-35.460,138.780),(-35.550,138.500),(-35.580,138.480),
(-34.780,138.489),(-34.804,138.479),(-34.789,138.489),(-34.858,138.487),
]

points=np.array([[lat,lon] for lat,lon in zip(beach_lats,beach_lons)])
values=np.array(beach_vals)
query=np.array(COASTAL_POINTS)

print('Running RBF interpolation...')
rbf=RBFInterpolator(points,values,kernel='thin_plate_spline',smoothing=1.0)
interpolated=rbf(query)

def get_severity(v):
    if v>=50000:return 'Critical'
    elif v>=10000:return 'High'
    elif v>=1000:return 'Medium'
    return 'Low'

features=[]
for i,(lat,lon) in enumerate(COASTAL_POINTS):
    v=max(0,float(interpolated[i]))
    sev=get_severity(v)
    sfabi=min(0.8,v/100000)
    features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[round(lon,5),round(lat,5)]},'properties':{'sfabi':round(sfabi,4),'ndci':round(sfabi*0.8,4),'severity':sev,'cell_count':round(v,0),'lat':round(lat,5),'lon':round(lon,5),'date':datetime.now().strftime('%Y-%m-%d')}})

geojson={'type':'FeatureCollection','features':features,'metadata':{'generated_at':datetime.now().isoformat(),'source':'Interpolated from SA Government beach readings','total_cells':len(features)}}
open('data/indices/bloom_heatmap_latest.geojson','w',encoding='utf-8').write(json.dumps(geojson))

print(f'Done. Generated {len(features)} coastal bloom points.')
print('Severity breakdown:')
from collections import Counter
sevs=Counter(ft['properties']['severity'] for ft in features)
[print(f'  {k}: {v}') for k,v in sevs.items()]
