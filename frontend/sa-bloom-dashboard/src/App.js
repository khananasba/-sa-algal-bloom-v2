import React,{useState,useEffect,useRef}from 'react';
import{MapContainer,TileLayer,CircleMarker,Polygon,Popup}from 'react-leaflet';
import axios from 'axios';
import 'leaflet/dist/leaflet.css';
import './App.css';
const API='https://sa-algal-bloom-v2.onrender.com/api';
const SC={Critical:'#d32f2f',High:'#f57c00',Medium:'#fbc02d',Low:'#388e3c',no_bloom:'transparent'};
const SFABI_C={High:'#7b1fa2',Medium:'#1565c0',Low:'#0097a7'};
const ZONES=[{name:'Adelaide metro beaches',coords:[[-35.05,138.35],[-35.05,138.65],[-35.45,138.65],[-35.45,138.35]]},{name:'Port Lincoln tuna farm',coords:[[-34.60,135.80],[-34.60,135.98],[-34.80,135.98],[-34.80,135.80]]},{name:'Goolwa desalination',coords:[[-35.45,138.75],[-35.45,138.92],[-35.60,138.92],[-35.60,138.75]]}];
const CAMERAS=[
{name:'Glenelg South Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/glenelg-south-algal-bloom-web-camera'},
{name:'Glenelg Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/glenelg-beach-algal-bloom-web-camera'},
{name:'Glenelg North Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/glenelg-north-beach-algal-bloom-web-camera'},
{name:'North Haven Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/north-haven-beach-algal-bloom-web-camera'},
{name:'Semaphore Park Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/semaphore-park-beach-algal-bloom-web-camera'},
{name:'Moana Beach South',url:'https://www.marinesafety.sa.gov.au/web-cameras/moana-beach-south-algal-bloom-web-camera'},
{name:'Moana Beach North',url:'https://www.marinesafety.sa.gov.au/web-cameras/moana-beach-north-algal-bloom-web-camera'},
{name:'South Port Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/south-port-beach-algal-bloom-web-camera'},
{name:'Port Noarlunga',url:'https://www.marinesafety.sa.gov.au/web-cameras/port-noarlunga-algal-bloom-web-camera'},
{name:"O'Sullivan Beach",url:'https://www.marinesafety.sa.gov.au/web-cameras/o-sullivan-beach-algal-bloom-web-camera'},
{name:'Brighton Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/brighton-beach-algal-bloom-web-camera'},
{name:'Seacliff Beach',url:'https://www.marinesafety.sa.gov.au/web-cameras/seacliff-beach-algal-bloom-web-camera'},
];
const LABELS={heatmap:'Bloom Heatmap',forecast:'72hr Forecast',cellcounts:'Ground Truth',satellite:'🛰️ Satellite',cameras:'Live Cameras','algal-assistant':'Algal Assistant'};
const INIT_MSG={role:'assistant',text:"Hi! I am the Algal Assistant. I can help you with beach safety questions, bloom forecast information, school excursion planning, and aquaculture bloom risk. What would you like to know?",ts:new Date()};
const SUGGESTIONS=["Is it safe to swim today?","Best beaches for school excursion Term 2?","Which beaches are Critical right now?","What does SFABI mean?"];
export default function App(){
const[layer,setLayer]=useState('heatmap');
const[heatmap,setHeatmap]=useState(null);
const[cells,setCells]=useState([]);
const[forecast,setForecast]=useState(null);
const[alerts,setAlerts]=useState({total_alerts:0,alerts:[]});
const[weather,setWeather]=useState([]);
const[safety,setSafety]=useState([]);
const[satData,setSatData]=useState(null);
const[hour,setHour]=useState('0');
const[messages,setMessages]=useState([INIT_MSG]);
const[chatInput,setChatInput]=useState('');
const[chatTyping,setChatTyping]=useState(false);
const chatEndRef=useRef(null);
useEffect(()=>{fetchAll();},[]);
useEffect(()=>{chatEndRef.current?.scrollIntoView({behavior:'smooth'});},[messages,chatTyping]);
async function fetchAll(){
const ok=r=>r.status==='fulfilled'&&r.value;
const[h,c,f2,a,w,bs,sat]=await Promise.allSettled([
axios.get(API+'/bloom-heatmap'),axios.get(API+'/cell-counts'),axios.get(API+'/forecast/72hr'),
axios.get(API+'/alerts'),axios.get(API+'/weather'),axios.get(API+'/beach-safety'),
axios.get(API+'/satellite'),
]);
if(ok(h))setHeatmap(h.value.data);
if(ok(c)){const cr=c.value.data;setCells(Array.isArray(cr)?cr:(cr.readings||[]));}
if(ok(f2))setForecast(f2.value.data);
if(ok(a))setAlerts(a.value.data);
if(ok(w)){const wr=w.value.data;setWeather(Array.isArray(wr)?wr:(wr.readings||[]));}
if(ok(bs)){const d=bs.value.data;if(Array.isArray(d))setSafety(d);else if(d&&d.scores)setSafety(d.scores);}
if(ok(sat))setSatData(sat.value.data);
}
async function sendMessage(text){
const q=(text||chatInput).trim();
if(!q)return;
setChatInput('');
setMessages(m=>[...m,{role:'user',text:q,ts:new Date()}]);
setChatTyping(true);
try{
const r=await axios.post(API+'/algal-assistant',{question:q},{timeout:30000});
setMessages(m=>[...m,{role:'assistant',text:r.data.answer,ts:new Date()}]);
}catch(e){
setMessages(m=>[...m,{role:'assistant',text:"Sorry, I'm unable to connect to the Algal Assistant. Please ensure the API is running.",ts:new Date()}]);
}finally{setChatTyping(false);}
}
const particles=forecast?.snapshots?.[hour]?.features||[];
const op={'0':0.9,'6':0.75,'12':0.6,'24':0.45,'48':0.3,'72':0.15};
function beachScore(name){return safety.find(s=>s.beach&&name.toLowerCase().includes(s.beach.toLowerCase()));}
const sortedCells=[...cells].sort((a,b)=>b.cell_count_per_litre-a.cell_count_per_litre);
const satFeatures=satData?.features||[];
const satStats=satData?.stats||null;
const satAvail=satData?.data_source==='sentinel2'&&satFeatures.length>0;
return(<div className="app-shell">
<div className="navbar">
<span className="nav-title">SA Algal Bloom Monitor</span>
<div className="nav-buttons">{['heatmap','forecast','cellcounts','satellite','cameras','algal-assistant'].map(l=>(<button key={l} onClick={()=>setLayer(l)} style={{padding:'6px 14px',borderRadius:20,border:'none',cursor:'pointer',background:layer===l?'#fff':'rgba(255,255,255,0.15)',color:layer===l?'#1a237e':'#fff'}}>{LABELS[l]}</button>))}</div>
<div className="nav-alert"><span style={{width:10,height:10,borderRadius:'50%',background:alerts.total_alerts>0?'#ff5252':'#69f0ae',display:'inline-block'}}/><span style={{fontSize:13}}>{alerts.total_alerts>0?alerts.total_alerts+' ALERT':'ALL CLEAR'}</span></div>
</div>

{layer==='algal-assistant'?(
<div className="ai-layer">
<div className="ai-chat-col">
<div className="ai-chat-header">
<div style={{fontSize:22,fontWeight:'bold',marginBottom:4}}>🧠 Algal Assistant</div>
<div style={{fontSize:12,opacity:0.85}}>AI-powered coastal safety intelligence for South Australia</div>
</div>
<div className="chat-messages">
{messages.map((m,i)=>(<div key={i} className={`chat-msg chat-${m.role}`}>
<div className="chat-bubble">{m.text}</div>
<div className="chat-ts">{m.ts instanceof Date?m.ts.toLocaleTimeString():''}</div>
{i===0&&(<div className="chat-suggestions">{SUGGESTIONS.map((s,j)=>(<button key={j} onClick={()=>sendMessage(s)} className="suggestion-pill">{s}</button>))}</div>)}
</div>))}
{chatTyping&&(<div className="chat-msg chat-assistant"><div className="chat-bubble typing"><span/><span/><span/></div></div>)}
<div ref={chatEndRef}/>
</div>
<div className="chat-input-area">
<input value={chatInput} onChange={e=>setChatInput(e.target.value)} onKeyDown={e=>e.key==='Enter'&&sendMessage()} placeholder="Ask about beach safety..." className="chat-input"/>
<button onClick={()=>sendMessage()} className="chat-send">Send</button>
</div>
</div>
<div className="ai-data-col">
<div className="ai-section">
<h3 style={{color:'#1a237e',fontSize:14,marginBottom:10}}>🚨 Active Alerts</h3>
{alerts.total_alerts===0?<div style={{background:'#e8f5e9',padding:10,borderRadius:8,color:'#2e7d32',fontSize:13}}>All zones clear</div>:alerts.alerts.map((a,i)=>(<div key={i} style={{background:'#fff',borderLeft:'5px solid #d32f2f',borderRadius:8,padding:10,marginBottom:8}}><b style={{fontSize:13}}>{a.zone_name}</b><br/><span style={{background:'#d32f2f',color:'#fff',padding:'1px 8px',borderRadius:10,fontSize:11}}>{a.severity}</span><div style={{fontSize:12,color:'#555',marginTop:4}}>Bloom in {a.predicted_hour}h</div></div>))}
</div>
<div className="ai-section">
<h3 style={{color:'#1a237e',fontSize:14,marginBottom:10}}>🌤 Coastal Weather</h3>
{weather.map((w,i)=>(<div key={i} style={{background:'#fff',borderRadius:8,padding:10,marginBottom:6,border:'1px solid #e0e0e0'}}><b style={{fontSize:13}}>{w.location_name}</b><div style={{fontSize:12,color:'#555'}}>Wind: {w.wind_speed?.toFixed(1)} km/h &nbsp;|&nbsp; SST: {w.sea_surface_temp?.toFixed(1)}°C</div></div>))}
</div>
<div className="ai-section">
<h3 style={{color:'#1a237e',fontSize:14,marginBottom:10}}>🏖 Top Beach Readings</h3>
{sortedCells.slice(0,8).map((c,i)=>(<div key={i} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'6px 0',borderBottom:'1px solid #eee',fontSize:12}}><span style={{flex:1,paddingRight:8}}>{c.beach_name}</span><span style={{background:SC[c.severity]||'#888',color:'#fff',padding:'2px 7px',borderRadius:10,whiteSpace:'nowrap'}}>{c.cell_count_per_litre?.toLocaleString()}</span></div>))}
</div>
</div>
</div>
):layer==='cameras'?(
<div className="camera-grid-area">
<h2 style={{color:'#1a237e',marginBottom:16,fontSize:18}}>SA Beach Live Cameras</h2>
<div className="camera-grid">{CAMERAS.map((cam,i)=>{const sc=beachScore(cam.name);return(
<div key={i} className="camera-card">
<div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}><b style={{fontSize:13,color:'#1a237e'}}>{cam.name}</b><span style={{display:'flex',alignItems:'center',gap:4}}><span className="live-dot"/><span style={{fontSize:10,color:'#388e3c',fontWeight:'bold'}}>LIVE</span></span></div>
<div style={{fontSize:32,textAlign:'center',padding:'10px 0'}}>📷</div>
{sc&&<div style={{textAlign:'center',marginBottom:8}}><span style={{background:sc.color,color:'#fff',padding:'2px 10px',borderRadius:10,fontSize:11,fontWeight:'bold'}}>{sc.score}/100 · {sc.label}</span></div>}
<a href={cam.url} target="_blank" rel="noopener noreferrer" className="camera-btn">View Live Camera</a>
</div>);})}</div>
</div>
):(
<div className="content-area">
<div className="map-area"><MapContainer center={[-35.3,138.5]} zoom={7} style={{height:'100%',width:'100%'}}>
<TileLayer url='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png' attribution='CartoDB'/>
{ZONES.map(z=>(<Polygon key={z.name} positions={z.coords} pathOptions={{color:'#d32f2f',weight:2,fill:false,dashArray:'6 4'}}><Popup>{z.name}</Popup></Polygon>))}
{layer==='heatmap'&&(!heatmap?.features||heatmap.features.length===0)&&cells.length>0&&(<div style={{position:'absolute',top:8,left:'50%',transform:'translateX(-50%)',background:'rgba(26,35,126,0.88)',color:'#fff',borderRadius:8,padding:'5px 14px',zIndex:1000,fontSize:11,whiteSpace:'nowrap',boxShadow:'0 2px 8px rgba(0,0,0,0.2)'}}>🛰️ Satellite unavailable — showing ground truth cell counts</div>)}
{layer==='heatmap'&&heatmap?.features?.length>0&&heatmap.features.map((ft,i)=>{const{lat,lon,severity}=ft.properties;if(severity==='no_bloom')return null;return<CircleMarker key={i} center={[lat,lon]} radius={6} pathOptions={{fillColor:SC[severity],color:'none',fillOpacity:0.6}}><Popup><b>{severity}</b><br/>SFABI:{ft.properties.sfabi}<br/>Cells:{ft.properties.cell_count?.toLocaleString()}</Popup></CircleMarker>;})}
{layer==='heatmap'&&(!heatmap?.features||heatmap.features.length===0)&&cells.map((c,i)=>(<CircleMarker key={i} center={[c.latitude,c.longitude]} radius={10} pathOptions={{fillColor:SC[c.severity]||'#888',color:'#fff',weight:1.5,fillOpacity:0.85}}><Popup><b>{c.beach_name}</b><br/>{c.cell_count_per_litre?.toLocaleString()} cells/L<br/><span style={{background:SC[c.severity],color:'#fff',padding:'2px 8px',borderRadius:10,fontSize:12}}>{c.severity}</span></Popup></CircleMarker>))}
{layer==='forecast'&&particles.map((ft,i)=>{const[lon,lat]=ft.geometry.coordinates;return<CircleMarker key={i} center={[lat,lon]} radius={3} pathOptions={{fillColor:'#1565c0',color:'none',fillOpacity:op[hour]||0.5}}/>;})};
{layer==='cellcounts'&&cells.map((c,i)=>(<CircleMarker key={i} center={[c.latitude,c.longitude]} radius={10} pathOptions={{fillColor:SC[c.severity]||'#888',color:'#fff',weight:1.5,fillOpacity:0.85}}><Popup><b>{c.beach_name}</b><br/>{c.cell_count_per_litre?.toLocaleString()} cells/L<br/><span style={{background:SC[c.severity],color:'#fff',padding:'2px 8px',borderRadius:10,fontSize:12}}>{c.severity}</span></Popup></CircleMarker>))}
{layer==='satellite'&&satAvail&&satFeatures.map((ft,i)=>{const{lat,lon,severity,sfabi}=ft.properties;if(!lat||!lon)return null;return<CircleMarker key={i} center={[lat,lon]} radius={7} pathOptions={{fillColor:SFABI_C[severity]||'#0097a7',color:'rgba(255,255,255,0.5)',weight:1,fillOpacity:0.75}}><Popup><b>SFABI: {sfabi}</b><br/>Severity: {severity}<br/>Lat:{lat} Lon:{lon}</Popup></CircleMarker>;})}
</MapContainer></div>
<div className="sidebar">
<h3 style={{margin:'0 0 8px',color:'#1a237e',fontSize:14}}>Active Alerts</h3>
{alerts.total_alerts===0?<div style={{background:'#e8f5e9',padding:10,borderRadius:8,color:'#2e7d32',fontSize:13}}>All zones clear</div>:alerts.alerts.map((a,i)=>(<div key={i} style={{background:'#fff',borderLeft:'5px solid #d32f2f',borderRadius:8,padding:10,marginBottom:8}}><b style={{fontSize:13}}>{a.zone_name}</b><br/><span style={{background:'#d32f2f',color:'#fff',padding:'1px 8px',borderRadius:10,fontSize:11}}>{a.severity}</span><div style={{fontSize:12,color:'#555',marginTop:4}}>Bloom in {a.predicted_hour}h</div></div>))}
{layer==='forecast'&&(<div style={{marginTop:16,background:'#fff',padding:12,borderRadius:8}}><h3 style={{margin:'0 0 8px',color:'#1a237e',fontSize:14}}>Forecast hour</h3><select value={hour} onChange={e=>setHour(e.target.value)} style={{width:'100%',padding:6,borderRadius:6,border:'1px solid #ccc'}}>{['0','6','12','24','48','72'].map(h=><option key={h} value={h}>T+{h} hours</option>)}</select><div style={{fontSize:12,color:'#666',marginTop:6}}>Particles: {particles.length}</div></div>)}
{layer==='satellite'&&(
<div style={{marginTop:12}}>
<h3 style={{margin:'0 0 6px',color:'#1a237e',fontSize:14}}>🛰️ Sentinel-2 SFABI</h3>
<div style={{fontSize:10,color:'#888',marginBottom:10}}>Spectral Fluorescence Algal Bloom Index</div>
{satAvail?(
<>
<div style={{background:'#e8eaf6',borderRadius:8,padding:10,marginBottom:8,fontSize:12}}>
<div><b>Last pass:</b> {satData?.last_updated?.slice(0,10)||'unknown'}</div>
<div><b>Pixels sampled:</b> {satStats?.n_pixels}</div>
<div><b>SFABI min:</b> {satStats?.sfabi_min} &nbsp;<b>max:</b> {satStats?.sfabi_max}</div>
<div><b>SFABI mean:</b> {satStats?.sfabi_mean}</div>
</div>
<div style={{fontSize:11,marginBottom:6,fontWeight:'bold',color:'#444'}}>Pixel Severity Breakdown</div>
{[['High (>0.15)','#7b1fa2',satStats?.high_pixels],['Medium (0.05–0.15)','#1565c0',satStats?.medium_pixels],['Low (0.02–0.05)','#0097a7',satStats?.low_pixels]].map(([label,col,count])=>(
<div key={label} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'4px 0',borderBottom:'1px solid #eee',fontSize:11}}>
<span style={{display:'flex',alignItems:'center',gap:6}}><span style={{width:10,height:10,borderRadius:'50%',background:col,display:'inline-block'}}/>{label}</span>
<span style={{background:col,color:'#fff',padding:'1px 8px',borderRadius:10,fontWeight:'bold'}}>{count}</span>
</div>
))}
<div style={{marginTop:10,fontSize:10,color:'#888',lineHeight:1.5}}>
High SFABI indicates bloom signature detected from space. Ground truth cell counts take priority for safety decisions.
</div>
</>
):(
<div style={{background:'#fff3e0',borderRadius:8,padding:12,fontSize:12,color:'#e65100'}}>
<div style={{fontWeight:'bold',marginBottom:4}}>🛰️ Satellite Unavailable</div>
<div>No current Sentinel-2 data. Possible reasons:</div>
<ul style={{margin:'6px 0 0 16px',padding:0,fontSize:11}}>
<li>Cloud cover blocked the latest pass</li>
<li>GEE daily refresh not yet complete</li>
<li>Last pass: {satData?.last_updated?.slice(0,10)||'unknown'}</li>
</ul>
<div style={{marginTop:8,fontSize:11}}>Satellite imagery refreshes daily at 2am UTC via GitHub Actions.</div>
</div>
)}
</div>
)}
{layer!=='satellite'&&(<>
<h3 style={{margin:'16px 0 4px',color:'#1a237e',fontSize:14}}>Beach Safety Score</h3>
<div style={{fontSize:10,color:'#888',marginBottom:8}}>SA Gov counts + BOM wind + Sentinel-2</div>
{safety.length>0?safety.slice(0,10).map((s,i)=>(<div key={i} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'5px 0',borderBottom:'1px solid #eee',fontSize:12}}><span style={{flex:1}}>{s.beach}</span><span style={{background:s.color,color:'#fff',padding:'2px 8px',borderRadius:10,fontWeight:'bold',fontSize:11}}>{s.score}</span></div>)):<div style={{fontSize:12,color:'#999'}}>Loading scores...</div>}
<h3 style={{margin:'16px 0 8px',color:'#1a237e',fontSize:14}}>Coastal Weather</h3>
{weather.slice(0,3).map((w,i)=>(<div key={i} style={{background:'#fff',borderRadius:8,padding:10,marginBottom:6,border:'1px solid #e0e0e0'}}><b style={{fontSize:13}}>{w.location_name}</b><div style={{fontSize:12,color:'#555'}}>Wind:{w.wind_speed?.toFixed(1)}km/h SST:{w.sea_surface_temp?.toFixed(1)}C</div></div>))}
<h3 style={{margin:'16px 0 8px',color:'#1a237e',fontSize:14}}>Top Beach Readings</h3>
{sortedCells.slice(0,8).map((c,i)=>(<div key={i} style={{display:'flex',justifyContent:'space-between',padding:'6px 0',borderBottom:'1px solid #eee',fontSize:12}}><span>{c.beach_name}</span><span style={{background:SC[c.severity],color:'#fff',padding:'2px 7px',borderRadius:10}}>{c.cell_count_per_litre?.toLocaleString()}</span></div>))}
</>)}
</div>
</div>
)}
</div>);}
