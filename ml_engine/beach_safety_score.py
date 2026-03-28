import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db_config import get_connection
import json
import requests
from datetime import datetime
from math import radians,cos,sin,sqrt,atan2

# SA Health published thresholds - source: algalbloom.sa.gov.au
SAFE_THRESHOLD=1000
CAUTION_THRESHOLD=10000
WARNING_THRESHOLD=50000

# SA beaches with coordinates
BEACHES=[
{'name':'Semaphore','lat':-34.838,'lon':138.482},
{'name':'Largs Bay','lat':-34.824,'lon':138.483},
{'name':'North Haven','lat':-34.789,'lon':138.489},
{'name':'Grange','lat':-34.903,'lon':138.486},
{'name':'Henley','lat':-34.921,'lon':138.497},
{'name':'West Beach','lat':-34.940,'lon':138.502},
{'name':'Glenelg','lat':-34.980,'lon':138.516},
{'name':'Brighton','lat':-35.005,'lon':138.519},
{'name':'Seacliff','lat':-35.033,'lon':138.517},
{'name':'Hallett Cove','lat':-35.069,'lon':138.504},
{'name':'Port Noarlunga','lat':-35.142,'lon':138.467},
{'name':'Moana','lat':-35.229,'lon':138.463},
{'name':'Aldinga','lat':-35.278,'lon':138.456},
{'name':'Sellicks','lat':-35.338,'lon':138.449},
{'name':'Victor Harbor','lat':-35.552,'lon':138.617},
{'name':'Goolwa','lat':-35.501,'lon':138.743},
{'name':'Port Elliot','lat':-35.529,'lon':138.683},
]

def haversine(lat1,lon1,lat2,lon2):
    R=6371
    dlat=radians(lat2-lat1)
    dlon=radians(lon2-lon1)
    a=sin(dlat/2)**2+cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R*2*atan2(sqrt(a),sqrt(1-a))

def get_nearest_cell_count(beach_lat,beach_lon,readings):
    best=None
    best_dist=999
    for r in readings:
        d=haversine(beach_lat,beach_lon,r['lat'],r['lon'])
        if d<best_dist:
            best_dist=d
            best=r
    if best and best_dist<50:
        return best['count'],best_dist,best['name']
    return 0,999,'No nearby reading'

def get_wind_data(lat,lon):
    try:
        url='https://api.open-meteo.com/v1/forecast'
        params={'latitude':lat,'longitude':lon,'current':'wind_speed_10m,wind_direction_10m','timezone':'Australia/Adelaide'}
        r=requests.get(url,params=params,timeout=10)
        data=r.json()
        ws=data['current']['wind_speed_10m']
        wd=data['current']['wind_direction_10m']
        return ws,wd
    except:
        return 0,0

def wind_onshore_factor(wind_dir):
    # SA metro beaches face west - onshore wind = 270 degrees (westerly)
    # Wind from 225-315 degrees pushes bloom onto beaches
    diff=abs((wind_dir-270+180)%360-180)
    if diff<45:return 1.0  # directly onshore
    elif diff<90:return 0.5  # partially onshore
    return 0.0  # offshore wind = less risk

def calculate_safety_score(cell_count,wind_speed,wind_dir,sfabi):
    # Component 1: Cell count (0-60 points deducted)
    # Source: SA Health published thresholds
    if cell_count>=WARNING_THRESHOLD:
        cell_penalty=60
    elif cell_count>=CAUTION_THRESHOLD:
        cell_penalty=40+((cell_count-CAUTION_THRESHOLD)/(WARNING_THRESHOLD-CAUTION_THRESHOLD))*20
    elif cell_count>=SAFE_THRESHOLD:
        cell_penalty=10+((cell_count-SAFE_THRESHOLD)/(CAUTION_THRESHOLD-SAFE_THRESHOLD))*30
    else:
        cell_penalty=min(10,cell_count/100)
    # Component 2: Wind risk (0-20 points deducted)
    # Source: Open-Meteo BOM real-time
    onshore=wind_onshore_factor(wind_dir)
    wind_penalty=onshore*(min(wind_speed,30)/30)*20
    # Component 3: Satellite SFABI (0-20 points deducted)
    # Source: Sentinel-2 GEE real calculation
    sfabi_penalty=min(20,sfabi*100)
    score=100-cell_penalty-wind_penalty-sfabi_penalty
    return max(0,round(score,1))

def score_to_label(score):
    if score>=80:return 'Safe','#388e3c'
    elif score>=50:return 'Caution','#fbc02d'
    elif score>=20:return 'Warning','#f57c00'
    return 'Danger','#d32f2f'

def run():
    print('=== Beach Safety Score Calculator ===')
    print('Data sources: SA Gov cell counts + Open-Meteo BOM + Sentinel-2 GEE')
    print()
    conn=get_connection()
    cur=conn.cursor()
    cur.execute('SELECT beach_name,latitude,longitude,cell_count_per_litre FROM KareniaReadings')
    readings=[{'name':r[0],'lat':r[1],'lon':r[2],'count':r[3]} for r in cur.fetchall()]
    conn.close()
    print(f'Loaded {len(readings)} cell count readings from database')
    sfabi_data={}
    try:
        with open('data/indices/bloom_heatmap_latest.geojson',encoding='utf-8') as f2:
            gj=json.load(f2)
        for ft in gj['features']:
            p=ft['properties']
            sfabi_data[(round(p['lat'],2),round(p['lon'],2))]=p['sfabi']
        print(f'Loaded {len(sfabi_data)} SFABI values from satellite')
    except:
        print('No SFABI data found - using 0')
    results=[]
    for beach in BEACHES:
        cell_count,dist,source=get_nearest_cell_count(beach['lat'],beach['lon'],readings)
        wind_speed,wind_dir=get_wind_data(beach['lat'],beach['lon'])
        nearest_sfabi=0
        best_sfabi_dist=999
        for (slat,slon),sv in sfabi_data.items():
            d=haversine(beach['lat'],beach['lon'],slat,slon)
            if d<best_sfabi_dist:
                best_sfabi_dist=d
                nearest_sfabi=sv
        score=calculate_safety_score(cell_count,wind_speed,wind_dir,nearest_sfabi)
        label,color=score_to_label(score)
        results.append({'beach':beach['name'],'lat':beach['lat'],'lon':beach['lon'],'score':score,'label':label,'color':color,'cell_count':cell_count,'wind_speed':round(wind_speed,1),'wind_dir':round(wind_dir,1),'sfabi':round(nearest_sfabi,4),'data_source':source})
    results.sort(key=lambda x:x['score'])
    print()
    print(f'{'Beach':<22} {'Score':>6} {'Label':<10} {'Cells/L':>10} {'Wind':>8} {'SFABI':>7}')
    print('-'*70)
    for r in results:
        print(f"{r['beach']:<22} {r['score']:>6.1f} {r['label']:<10} {r['cell_count']:>10,.0f} {r['wind_speed']:>6.1f}km/h {r['sfabi']:>7.4f}")
    os.makedirs('data',exist_ok=True)
    with open('data/beach_safety_scores.json','w',encoding='utf-8') as f3:
        json.dump({'generated_at':datetime.now().isoformat(),'methodology':'SA Health thresholds + Open-Meteo BOM + Sentinel-2 SFABI','scores':results},f3)
    print()
    print(f'Saved to data/beach_safety_scores.json')
    print('=== DONE ===')
    return results

if __name__=='__main__':
    run()
