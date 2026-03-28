import csv
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection, adapt_sql, ph
from datetime import datetime
from collections import defaultdict

CSV='data_ingestion/sa_bloom_data.csv'
CUTOFF='2025-09-01'

COORDS={'Largs Bay Jetty':(-34.824,138.483),'Largs Bay':(-34.824,138.483),'Grange Jetty':(-34.903,138.486),'Grange':(-34.903,138.486),'Henley Beach Jetty':(-34.921,138.497),'Henley Beach':(-34.921,138.497),'Henley':(-34.921,138.497),'West Beach Boat Ramp':(-34.940,138.502),'West Beach':(-34.940,138.502),'Glenelg Jetty':(-34.980,138.516),'Glenelg':(-34.980,138.516),'Brighton Jetty':(-35.005,138.519),'Brighton':(-35.005,138.519),'Seacliff':(-35.033,138.517),'Hallett Cove':(-35.069,138.504),'Port Noarlunga':(-35.142,138.467),'Moana':(-35.229,138.463),'Aldinga Beach':(-35.278,138.456),'Aldinga':(-35.278,138.456),'Sellicks Beach':(-35.338,138.449),'Sellicks':(-35.338,138.449),'Victor Harbor':(-35.552,138.617),'Goolwa':(-35.501,138.743),'Port Elliot':(-35.529,138.683),'Semaphore':(-34.838,138.482),'North Haven':(-34.789,138.489),'Tennyson':(-34.875,138.490),'Somerton':(-34.858,138.487),'Point Turton':(-35.312,137.358),'Hardwicke Bay':(-35.194,137.467),'Pondalowie':(-35.012,136.937),'Marion Bay':(-35.227,137.021),'Edithburgh':(-35.083,137.737),'Port Vincent':(-35.023,137.852),'Wallaroo Jetty':(-33.933,137.633),'Wallaroo':(-33.933,137.633),'Stansbury':(-34.912,137.789),'Corny Point':(-34.897,136.998),'Kingscote':(-35.657,137.638),'Penneshaw':(-35.727,137.943),'American River':(-35.773,137.764),'Normanville':(-35.447,138.316),'Cape Jervis':(-35.602,138.100),'Waitpinga':(-35.572,138.513),'Petrel Cove':(-35.582,138.578),'O Sullivan Beach':(-35.104,138.468),'Onkaparinga':(-35.142,138.467),'Patawalonga':(-34.970,138.510),'West Lakes':(-34.870,138.490),'Port River':(-34.780,138.489)}


def find_coords(site_name):
    for key,coords in COORDS.items():
        if key.lower() in site_name.lower() or site_name.lower() in key.lower():
            return coords
    return None

print('Reading CSV - filtering from',CUTOFF,'onwards only...')
with open(CSV,encoding='utf-8-sig') as f2:
    rows=list(csv.DictReader(f2))

karenia=[r for r in rows
    if 'karenia' in r.get('Result_Name','').lower()
    and r.get('Result_Value_Numeric','') not in ['','0','None']
    and r.get('Date_Sample_Collected','') >= CUTOFF]
print(f'Found {len(karenia)} Karenia readings from {CUTOFF} onwards')

latest=defaultdict(lambda:{'date':'2000-01-01','val':0})
for r in karenia:
    site=r['Site_Description']
    date=r['Date_Sample_Collected']
    try:val=float(r['Result_Value_Numeric'])
    except:continue
    if val<=0:continue
    if date>latest[site]['date']:
        latest[site]={'date':date,'val':val}

print(f'Unique sites with recent Karenia data: {len(latest)}')

conn=get_connection()
cur=conn.cursor()
cur.execute('DELETE FROM KareniaReadings')

inserted=0
skipped=0
for site,data in latest.items():
    coords=find_coords(site)
    if coords is None:
        skipped+=1
        continue
    lat,lon=coords
    val=data['val']
    try:dt=datetime.strptime(data['date'],'%Y-%m-%d')
    except:dt=datetime.now()
    if val>=50000:sev='Critical'
    elif val>=10000:sev='High'
    elif val>=1000:sev='Medium'
    else:sev='Low'
    cur.execute(f'INSERT INTO KareniaReadings(recorded_at,beach_name,latitude,longitude,cell_count_per_litre,severity,source) VALUES({ph(7)})',
        (dt,site,lat,lon,int(val),sev,'SA_Gov_Live_Feb2026'))
    inserted+=1

conn.commit()
conn.close()

print(f'Inserted: {inserted} readings')
print(f'Skipped (no coords): {skipped}')
print()

conn2=get_connection()
cur2=conn2.cursor()
cur2.execute('SELECT severity,COUNT(*) FROM KareniaReadings GROUP BY severity ORDER BY COUNT(*) DESC')
print('Severity breakdown:')
for r in cur2.fetchall():print(f'  {r[0]}: {r[1]}')
print()
cur2.execute(adapt_sql('SELECT TOP 10 beach_name,cell_count_per_litre,severity,recorded_at FROM KareniaReadings ORDER BY cell_count_per_litre DESC'))
print('Top 10 real readings (Feb 2026 onwards):')
for r in cur2.fetchall():print(f'  {r[0]}: {r[1]:,} cells/L - {r[2]} - {str(r[3])[:10]}')
conn2.close()
print()
print('Ground Truth layer updated. Other layers not affected.')
