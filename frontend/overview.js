import {createWireframeGlobe, dashboardColor, eventDetailsHtml} from './wireframe-globe.js';

const readPreference=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}};
const store=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch{}};

export async function renderOverview({api,view,esc,safeUrl,sparkline,trendBadge,every}) {
  const savedWindow=readPreference('overview-window','7d');
  let windowSize=['24h','7d','30d','90d'].includes(savedWindow)?savedWindow:'7d';
  const savedHidden=readPreference('overview-hidden',[]),hidden=new Set(Array.isArray(savedHidden)?savedHidden.filter(Number.isInteger):[]);
  let data,disposed=false,requestId=0;
  const labels={'24h':'Last 24 hours','7d':'Last week','30d':'Last month','90d':'Last quarter'};
  view.innerHTML=`<div class="dash-head"><div><h1>Main dashboard</h1><p class="muted small">Toggle dashboard overlays to explore their reporting on the globe. Periods cover the last 24 hours, 7, 30 or 90 days.</p></div><span class="spacer"></span>
    <div class="seg" id="overview-window">${Object.entries(labels).map(([w,l])=>`<button data-window="${w}" class="${w===windowSize?'on':''}" aria-pressed="${w===windowSize}">${l}</button>`).join('')}</div><button id="overview-refresh">Refresh</button></div>
    <div class="overview-grid"><section class="card globe-card"><div class="row pad globe-toolbar"><h2>Global reporting</h2><span class="spacer"></span>
      <button data-globe-action="left" aria-label="Rotate globe left">←</button><button data-globe-action="right" aria-label="Rotate globe right">→</button>
      <button data-globe-action="in" aria-label="Zoom in on globe">+</button><button data-globe-action="out" aria-label="Zoom out on globe">−</button><button data-globe-action="reset">Reset view</button></div>
      <div id="overview-globe" class="wireframe-globe" role="img" aria-label="Interactive wireframe globe on a starfield; coloured dots show geolocated articles per dashboard. Drag to rotate, scroll to zoom, or use the buttons above."></div>
      <div class="pad"><p id="globe-status" class="small muted" role="status">Loading reporting…</p><label class="inline"><input type="checkbox" id="globe-rotate"> Slowly rotate globe</label>
      <p class="small faint">Dot colours identify dashboards. Numbers show how many articles are grouped at a place; dots grow up to a fixed size, then only the number increases. Zoom in to separate nearby locations. Locations are model-estimated and approximate. The period buttons change both the graphs and the dots.</p>
      <div id="globe-selection" class="small globe-selection" aria-live="polite">Click a dot to inspect its source reports. Reports without coordinates remain included in the graphs.</div></div></section>
      <aside class="overview-trends" aria-label="Dashboard article counts and trends"><div class="row"><h2>Dashboard overlays</h2><span class="spacer"></span><button id="overlays-all">All</button><button id="overlays-none">None</button></div>
      <p class="small muted">Unique articles per PIR set, compared with the preceding equal period. Graphs show hourly counts for 24 hours and daily counts otherwise. Small samples are labelled Low volume.</p><div id="overview-cards" class="stack"></div></aside></div>`;
  const host=view.querySelector('#overview-globe'),status=view.querySelector('#globe-status'),cards=view.querySelector('#overview-cards'),selection=view.querySelector('#globe-selection'),controls=view.querySelector('#globe-rotate');
  const paintStatus=({points,reportCount})=>{
    if(!data||disposed) return;
    const visible=data.dashboards.filter(d=>!hidden.has(d.id)),limited=visible.some(d=>d.points_truncated);
    status.textContent=`${labels[data.window]}: ${reportCount} geolocated articles at ${points.length} map dots from ${visible.length} dashboard${visible.length===1?'':'s'}.${limited?` Very large period: the globe shows the latest ${data.point_limit_per_dashboard.toLocaleString()} geolocated articles per dashboard; graphs count all.`:''}${!visible.length?' Enable a dashboard overlay to plot articles.':''}`;
  };
  const map=createWireframeGlobe(host,{esc,onChange:paintStatus,
    onSelect:point=>{selection.innerHTML=eventDetailsHtml(point,esc,safeUrl);},
    onError:()=>{controls.disabled=true;}});
  const updatePoints=()=>{
    if(!data||disposed) return;
    map.setDashboards(data.dashboards,hidden);
    cards.querySelectorAll('[data-dashboard]').forEach(card=>{
      const enabled=!hidden.has(Number(card.dataset.dashboard));card.classList.toggle('overlay-off',!enabled);card.querySelector('input').checked=enabled;
    });
    selection.textContent='Click a dot to inspect its source reports. Reports without coordinates remain included in the graphs.';
  };
  const drawCards=()=>{
    cards.innerHTML=data.dashboards.map(d=>`<section class="card pad overview-card" data-dashboard="${d.id}" style="--dashboard-color:${dashboardColor(d.id)}">
      <label class="inline overview-toggle"><input type="checkbox" ${hidden.has(d.id)?'':'checked'} aria-label="Show ${esc(d.name)} on globe"><span class="dashboard-swatch"></span><b>${esc(d.name)}</b></label>
      <div class="row"><span class="overview-count">${d.count}</span><span class="spacer"></span>${trendBadge(d)}</div>
      <p class="small muted">articles · ${labels[data.window].toLowerCase()} · previous ${d.previous_count} · ${d.pir_count} active PIRs</p>
      <div class="spark"></div><p class="small faint">${d.geolocated_count} geolocated · ${d.unlocated_count} without coordinates${d.points_truncated?' · globe partially shown':''}</p><a class="small" href="#/dash/${d.id}">Open dashboard →</a></section>`).join('')||'<div class="card pad"><p>No dashboards yet.</p><a href="#/ingestion">Configure a stream</a>, then <a href="#/setup">set up your first dashboard</a>.</div>';
    cards.querySelectorAll('[data-dashboard]').forEach((card,index)=>{
      sparkline(card.querySelector('.spark'),data.dashboards[index].series);
      card.querySelector('input').onchange=e=>{
        const id=Number(card.dataset.dashboard);if(e.target.checked) hidden.delete(id);else hidden.add(id);
        store('overview-hidden',[...hidden]);updatePoints();
      };
    });
    updatePoints();
  };
  const load=async()=>{
    const version=++requestId;status.textContent=`Loading ${labels[windowSize].toLowerCase()}…`;
    try {
      const result=await api(`/api/overview?window=${windowSize}`);
      if(disposed||!host.isConnected||version!==requestId) return;
      data=result;drawCards();
    } catch(err) {if(!disposed&&host.isConnected&&version===requestId) status.textContent=`Could not refresh reporting: ${err.message}`;}
  };
  view.querySelectorAll('[data-window]').forEach(button=>button.onclick=()=>{
    windowSize=button.dataset.window;store('overview-window',windowSize);
    view.querySelectorAll('[data-window]').forEach(b=>{b.classList.toggle('on',b===button);b.setAttribute('aria-pressed',String(b===button));});load();
  });
  view.querySelector('#overview-refresh').onclick=load;
  view.querySelector('#overlays-all').onclick=()=>{hidden.clear();store('overview-hidden',[]);updatePoints();};
  view.querySelector('#overlays-none').onclick=()=>{data?.dashboards.forEach(d=>hidden.add(d.id));store('overview-hidden',[...hidden]);updatePoints();};
  view.querySelectorAll('[data-globe-action]').forEach(button=>button.onclick=()=>map.action(button.dataset.globeAction));
  controls.onchange=()=>map.setAutoRotate(controls.checked);
  load();every(60000,load);
  return ()=>{disposed=true;requestId++;map.dispose();};
}
