import requests
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, adapt_sql, ph
import json
from datetime import datetime

print('Fetching real SA Government algal bloom data...')
url='https://services6.arcgis.com/WS2XycMNFieWAsfS/arcgis/rest/services/HarmfulAlgalBloom_MonitoringSites/FeatureServer/0/query'
params={'where':'1=1','outFields':'*','f':'json','resultRecordCount':1000}
r=requests.get(url,params=params,timeout=30)
data=r.json()
features=data.get('features',[])
print(f'Got {len(features)} sites from SA Government API')

if features:
    print('Sample fields:',list(features[0]['properties'].keys() if 'properties' in features[0] else features[0]['attributes'].keys()))

conn=get_connection()
cursor=conn.cursor()
cursor.execute('DELETE FROM KareniaReadings')
print('Cleared old readings')

count=0
for ft in features:
    a=ft.get('attributes',ft.get('properties',{}))
    g=ft.get('geometry',{})
    try:
        site_name=str(a.get('SiteName',a.get('Site_Name',a.get('SITENAME','Unknown'))))
        lon=float(a.get('Longitude',a.get('longitude',g.get('x',0))))
        lat=float(a.get('Latitude',a.get('latitude',g.get('y',0))))
        karenia=a.get('Karenia_spp',a.get('KareniaSpp',a.get('karenia_count',a.get('Karenia',0)))) or 0
        karenia=float(karenia)
        if karenia<0:karenia=0
        if karenia>=50000:sev='Critical'
        elif karenia>=10000:sev='High'
        elif karenia>=1000:sev='Medium'
        else:sev='Low'
        cursor.execute(f'INSERT INTO KareniaReadings(recorded_at,beach_name,latitude,longitude,cell_count_per_litre,severity,source) VALUES({ph(7)})',datetime.now(),site_name,lat,lon,int(karenia),sev,'SA_Gov_ArcGIS_Live')
        count+=1
    except Exception as e:
        continue

conn.commit()
conn.close()
print(f'Inserted {count} real sites into database')

print('\nSeverity breakdown:')
conn2=get_connection()
cursor2=conn2.cursor()
cursor2.execute('SELECT severity,COUNT(*) FROM KareniaReadings GROUP BY severity ORDER BY COUNT(*) DESC')
[print(f'  {r[0]}: {r[1]} sites') for r in cursor2.fetchall()]
conn2.close()

print('\nTop 10 highest Karenia readings:')
conn3=get_connection()
cursor3=conn3.cursor()
cursor3.execute(adapt_sql('SELECT TOP 10 beach_name,cell_count_per_litre,severity FROM KareniaReadings ORDER BY cell_count_per_litre DESC'))
[print(f'  {r[0]}: {r[1]} cells/L - {r[2]}') for r in cursor3.fetchall()]
conn3.close()
