import React,{useState,useEffect}from 'react';
import{MapContainer,TileLayer,CircleMarker,Polygon,Popup}from 'react-leaflet';
import axios from 'axios';
import 'leaflet/dist/leaflet.css';
import './App.css';
const API=process.env.REACT_APP_API_URL||'http://localhost:8000/api';
const SC={Critical:'#d32f2f',High:'#f57c00',Medium:'#fbc02d',Low:'#388e3c',no_bloom:'transparent'};
const ZONES=[{name:'Adelaide metro beaches',coords:[[-35.05,138.35],[-35.05,138.65],[-35.45,138.65],[-35.45,138.35]]},{name:'Port Lincoln tuna farm',coords:[[-34.60,135.80],[-34.60,135.98],[-34.80,135.98],[-34.80,135.80]]},{name:'Goolwa desalination',coords:[[-35.45,138.75],[-35.45,138.92],[-35.60,138.92],[-35.60,138.75]]}];
export default function App(){
const[layer,setLayer]=useState('heatmap');
const[heatmap,setHeatmap]=useState(null);
const[cells,setCells]=useState([]);
const[forecast,setForecast]=useState(null);
const[alerts,setAlerts]=useState({total_alerts:0,alerts:[]});
const[weather,setWeather]=useState([]);
const[safety,setSafety]=useState([]);
const[hour,setHour]=useState('0');
useEffect(()=>{fetchAll();},[]);
async function fetchAll(){
const ok=r=>r.status==='fulfilled'&&r.value;
const[h,c,f2,a,w,bs]=await Promise.allSettled([
axios.get(API+'/bloom-heatmap'),
axios.get(API+'/cell-counts'),
axios.get(API+'/forecast/72hr'),
axios.get(API+'/alerts'),
axios.get(API+'/weather'),
axios.get(API+'/beach-safety'),
]);
if(ok(h))setHeatmap(h.value.data);
if(ok(c)&&Array.isArray(c.value.data))setCells(c.value.data);
if(ok(f2))setForecast(f2.value.data);
if(ok(a))setAlerts(a.value.data);
if(ok(w)&&Array.isArray(w.value.data))setWeather(w.value.data);
if(ok(bs)){const d=bs.value.data;if(Array.isArray(d))setSafety(d);else if(d&&d.scores)setSafety(d.scores);}
}
const particles=forecast?.snapshots?.[hour]?.features||[];
const op={'0':0.9,'6':0.75,'12':0.6,'24':0.45,'48':0.3,'72':0.15};
return(<div style={{height:'100vh',display:'flex',flexDirection:'column',fontFamily:'Arial'}}>
<div style={{background:'#1a237e',color:'#fff',padding:'0 20px',height:56,display:'flex',alignItems:'center',gap:16,flexShrink:0}}>
<span style={{fontSize:18,fontWeight:'bold'}}>SA Algal Bloom Monitor</span>
{['heatmap','forecast','cellcounts'].map(l=>(<button key={l} onClick={()=>setLayer(l)} style={{padding:'6px 14px',borderRadius:20,border:'none',cursor:'pointer',background:layer===l?'#fff':'rgba(255,255,255,0.15)',color:layer===l?'#1a237e':'#fff'}}>{l==='heatmap'?'Bloom Heatmap':l==='forecast'?'72hr Forecast':'Ground Truth'}</button>))}
<div style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:8}}><span style={{width:10,height:10,borderRadius:'50%',background:alerts.total_alerts>0?'#ff5252':'#69f0ae',display:'inline-block'}}/><span style={{fontSize:13}}>{alerts.total_alerts>0?alerts.total_alerts+' ALERT':'ALL CLEAR'}</span></div></div>
<div style={{flex:1,display:'flex',overflow:'hidden'}}>
<div style={{flex:1}}><MapContainer center={[-35.3,138.5]} zoom={7} style={{height:'100%',width:'100%'}}>
<TileLayer url='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png' attribution='CartoDB'/>
{ZONES.map(z=>(<Polygon key={z.name} positions={z.coords} pathOptions={{color:'#d32f2f',weight:2,fill:false,dashArray:'6 4'}}><Popup>{z.name}</Popup></Polygon>))}
{layer==='heatmap'&&heatmap?.features?.map((ft,i)=>{const{lat,lon,severity}=ft.properties;if(severity==='no_bloom')return null;return<CircleMarker key={i} center={[lat,lon]} radius={6} pathOptions={{fillColor:SC[severity],color:'none',fillOpacity:0.6}}><Popup><b>{severity}</b><br/>SFABI:{ft.properties.sfabi}<br/>Cells:{ft.properties.cell_count?.toLocaleString()}</Popup></CircleMarker>;})}
{layer==='forecast'&&particles.map((ft,i)=>{const[lon,lat]=ft.geometry.coordinates;return<CircleMarker key={i} center={[lat,lon]} radius={3} pathOptions={{fillColor:'#1565c0',color:'none',fillOpacity:op[hour]||0.5}}/>;})}
{layer==='cellcounts'&&cells.map((c,i)=>(<CircleMarker key={i} center={[c.latitude,c.longitude]} radius={10} pathOptions={{fillColor:SC[c.severity]||'#888',color:'#fff',weight:1.5,fillOpacity:0.85}}><Popup><b>{c.beach_name}</b><br/>{c.cell_count_per_litre?.toLocaleString()} cells/L<br/><span style={{background:SC[c.severity],color:'#fff',padding:'2px 8px',borderRadius:10,fontSize:12}}>{c.severity}</span></Popup></CircleMarker>))}
</MapContainer></div>
<div style={{width:320,background:'#f5f5f5',overflowY:'auto',borderLeft:'1px solid #ddd',padding:16,flexShrink:0}}>
<h3 style={{margin:'0 0 8px',color:'#1a237e',fontSize:14}}>Active Alerts</h3>
{alerts.total_alerts===0?<div style={{background:'#e8f5e9',padding:10,borderRadius:8,color:'#2e7d32',fontSize:13}}>All zones clear</div>:alerts.alerts.map((a,i)=>(<div key={i} style={{background:'#fff',borderLeft:'5px solid #d32f2f',borderRadius:8,padding:10,marginBottom:8}}><b style={{fontSize:13}}>{a.zone_name}</b><br/><span style={{background:'#d32f2f',color:'#fff',padding:'1px 8px',borderRadius:10,fontSize:11}}>{a.severity}</span><div style={{fontSize:12,color:'#555',marginTop:4}}>Bloom in {a.predicted_hour}h</div></div>))}
{layer==='forecast'&&(<div style={{marginTop:16,background:'#fff',padding:12,borderRadius:8}}><h3 style={{margin:'0 0 8px',color:'#1a237e',fontSize:14}}>Forecast hour</h3><select value={hour} onChange={e=>setHour(e.target.value)} style={{width:'100%',padding:6,borderRadius:6,border:'1px solid #ccc'}}>{['0','6','12','24','48','72'].map(h=><option key={h} value={h}>T+{h} hours</option>)}</select><div style={{fontSize:12,color:'#666',marginTop:6}}>Particles: {particles.length}</div></div>)}
<h3 style={{margin:'16px 0 4px',color:'#1a237e',fontSize:14}}>Beach Safety Score</h3>
<div style={{fontSize:10,color:'#888',marginBottom:8}}>SA Gov counts + BOM wind + Sentinel-2</div>
{safety.length>0?safety.slice(0,10).map((s,i)=>(<div key={i} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'5px 0',borderBottom:'1px solid #eee',fontSize:12}}><span style={{flex:1}}>{s.beach}</span><span style={{background:s.color,color:'#fff',padding:'2px 8px',borderRadius:10,fontWeight:'bold',fontSize:11}}>{s.score}</span></div>)):<div style={{fontSize:12,color:'#999'}}>Loading scores...</div>}
<h3 style={{margin:'16px 0 8px',color:'#1a237e',fontSize:14}}>Coastal Weather</h3>
{weather.slice(0,3).map((w,i)=>(<div key={i} style={{background:'#fff',borderRadius:8,padding:10,marginBottom:6,border:'1px solid #e0e0e0'}}><b style={{fontSize:13}}>{w.location_name}</b><div style={{fontSize:12,color:'#555'}}>Wind:{w.wind_speed?.toFixed(1)}km/h SST:{w.sea_surface_temp?.toFixed(1)}C</div></div>))}
<h3 style={{margin:'16px 0 8px',color:'#1a237e',fontSize:14}}>Top Beach Readings</h3>
{[...cells].sort((a,b)=>b.cell_count_per_litre-a.cell_count_per_litre).slice(0,8).map((c,i)=>(<div key={i} style={{display:'flex',justifyContent:'space-between',padding:'6px 0',borderBottom:'1px solid #eee',fontSize:12}}><span>{c.beach_name}</span><span style={{background:SC[c.severity],color:'#fff',padding:'2px 7px',borderRadius:10}}>{c.cell_count_per_litre?.toLocaleString()}</span></div>))}
</div></div></div>);}
