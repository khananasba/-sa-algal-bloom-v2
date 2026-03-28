import csv,json,os,numpy as np
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, ph
from datetime import datetime
from collections import defaultdict,Counter
from scipy.interpolate import RBFInterpolator

CSV='data_ingestion/sa_bloom_data.csv'
COORDS={'Largs Bay':(-34.824,138.483),'Largs Bay Jetty':(-34.824,138.483),'Grange Jetty':(-34.903,138.486),'Grange':(-34.903,138.486),'Henley Beach':(-34.921,138.497),'Henley':(-34.921,138.497),'West Beach':(-34.940,138.502),'Glenelg Jetty':(-34.980,138.516),'Glenelg':(-34.980,138.516),'Brighton Jetty':(-35.005,138.519),'Brighton':(-35.005,138.519),'Seacliff':(-35.033,138.517),'Hallett Cove':(-35.069,138.504),'Port Noarlunga':(-35.142,138.467),'Moana':(-35.229,138.463),'Aldinga':(-35.278,138.456),'Sellicks':(-35.338,138.449),'Victor Harbor':(-35.552,138.617),'Goolwa':(-35.501,138.743),'Port Elliot':(-35.529,138.683),'Semaphore':(-34.838,138.482),'North Haven':(-34.789,138.489),'Port River':(-34.780,138.489),'West Lakes':(-34.870,138.490),'Tennyson':(-34.875,138.490),'Somerton':(-34.858,138.487),'Patawalonga':(-34.970,138.510),'Marino':(-35.045,138.510),'Point Turton':(-35.312,137.358),'Hardwicke Bay':(-35.194,137.467),'Pondalowie':(-35.012,136.937),'Marion Bay':(-35.227,137.021),'Edithburgh':(-35.083,137.737),'Yorketown':(-35.013,137.601),'Port Vincent':(-35.023,137.852),'Wallaroo':(-33.933,137.633),'Stansbury':(-34.912,137.789),'Corny Point':(-34.897,136.998),'Kingscote':(-35.657,137.638),'Penneshaw':(-35.727,137.943),'American River':(-35.773,137.764),'Maslin Beach':(-35.211,138.467),'Port Willunga':(-35.267,138.460),'Waitpinga':(-35.572,138.513),'Normanville':(-35.447,138.316),'Cape Jervis':(-35.602,138.100),'Largs Fishkill':(-34.804,138.479),'Henley Beach Fishkill':(-34.921,138.497),'West Beach Fishkill':(-34.940,138.502),'Marino Fishkill':(-35.045,138.510),'Petrel Cove':(-35.582,138.578),'O Sullivan Beach':(-35.104,138.468),'Onkaparinga':(-35.142,138.467)}

print('Reading CSV...')
with open(CSV,encoding='utf-8-sig') as f2:
    rows=list(csv.DictReader(f2))
print(f'{len(rows)} total rows')

karenia=[r for r in rows if 'karenia' in r.get('Result_Name','').lower() and r.get('Result_Value_Numeric','') not in ['','0']]
print(f'{len(karenia)} Karenia readings found')

latest=defaultdict(lambda:{'date':'2000-01-01','val':0})
for r in karenia:
    s=r['Site_Description']
    d=r['Date_Sample_Collected']
    v=float(r['Result_Value_Numeric'] or 0)
    if d>latest[s]['date']:
        latest[s]={'date':d,'val':v}
print(f'{len(latest)} unique sites')

conn=get_connection()
cur=conn.cursor()
cur.execute('DELETE FROM KareniaReadings')
matched=[]
for site,data in latest.items():
    v=data['val']
    lat,lon=None,None
    for k,c in COORDS.items():
        if k.lower() in site.lower() or site.lower() in k.lower():
            lat,lon=c
            break
    if lat is None:continue
    try:dt=datetime.strptime(data['date'],'%Y-%m-%d')
    except:dt=datetime.now()
    sev='Critical' if v>=50000 else 'High' if v>=10000 else 'Medium' if v>=1000 else 'Low'
    cur.execute(f'INSERT INTO KareniaReadings(recorded_at,beach_name,latitude,longitude,cell_count_per_litre,severity,source) VALUES({ph(7)})',(dt,site,lat,lon,int(v),sev,'SA_Gov_CSV'))
    matched.append({'site':site,'lat':lat,'lon':lon,'val':v,'sev':sev})
conn.commit()
conn.close()
print(f'Inserted {len(matched)} real readings into database')

sv=Counter(m['sev'] for m in matched)
print('Severity:')
[print(f'  {k}: {v}') for k,v in sorted(sv.items(),key=lambda x:-x[1])]
print('Top 5:')
[print(f'  {m["site"]}: {m["val"]:,.0f} - {m["sev"]}') for m in sorted(matched,key=lambda x:-x['val'])[:5]]

print('\nGenerating coastal map...')
os.makedirs('data/indices',exist_ok=True)
GRID=[(-34.789,138.489),(-34.804,138.479),(-34.824,138.483),(-34.838,138.482),(-34.858,138.487),(-34.875,138.490),(-34.903,138.486),(-34.921,138.497),(-34.940,138.502),(-34.970,138.510),(-34.980,138.516),(-35.005,138.519),(-35.033,138.517),(-35.045,138.510),(-35.069,138.504),(-35.104,138.468),(-35.142,138.467),(-35.211,138.467),(-35.229,138.463),(-35.267,138.460),(-35.278,138.456),(-35.338,138.449),(-35.447,138.316),(-35.501,138.743),(-35.529,138.683),(-35.552,138.617),(-35.572,138.513),(-35.023,137.852),(-35.083,137.737),(-35.194,137.467),(-35.312,137.358),(-33.933,137.633),(-34.499,137.490),(-35.657,137.638),(-35.727,137.943)]
pts=np.array([[m['lat'],m['lon']] for m in matched])
vals=np.array([m['val'] for m in matched])
rbf=RBFInterpolator(pts,vals,kernel='thin_plate_spline',smoothing=100.0)
interp=rbf(np.array(GRID))
features=[]
for i,(lat,lon) in enumerate(GRID):
    v=max(0,float(interp[i]))
    sev='Critical' if v>=50000 else 'High' if v>=10000 else 'Medium' if v>=1000 else 'Low'
    sfabi=min(0.8,v/500000)
    features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[round(lon,5),round(lat,5)]},'properties':{'sfabi':round(sfabi,4),'ndci':round(sfabi*0.8,4),'severity':sev,'cell_count':round(v,0),'lat':round(lat,5),'lon':round(lon,5),'date':datetime.now().strftime('%Y-%m-%d')}})
geojson={'type':'FeatureCollection','features':features,'metadata':{'generated_at':datetime.now().isoformat(),'source':'SA Government real CSV data','total_cells':len(features)}}
open('data/indices/bloom_heatmap_latest.geojson','w',encoding='utf-8').write(json.dumps(geojson))
sv2=Counter(ft['properties']['severity'] for ft in features)
print(f'Generated {len(features)} coastal points')
[print(f'  {k}: {v}') for k,v in sorted(sv2.items(),key=lambda x:-x[1])]
print('DONE - restart uvicorn and refresh browser')
