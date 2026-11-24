// Shared geography, clustering and renderer for every dashboard map.
const GLOBE_URL = 'https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js';
const TEXTURES = 'https://cdn.jsdelivr.net/npm/three-globe@2.45.0/example/img/';
let globeLoader, geographyLoader;

// Event dots: one per dashboard cluster, coloured by dashboard. Diameter grows with the
// article count up to a cap; beyond the cap only the number keeps growing.
export const DOT_MIN=10, DOT_MAX=30;
export function dotSize(count) { return Math.round(Math.min(DOT_MAX, DOT_MIN + 5*Math.log2(Math.max(1,count)))); }
export function dotLabel(count) { return count>1 ? (count>999 ? `${Math.floor(count/1000)}k+` : String(count)) : ''; }
// Clusters on the far side of the globe are hidden (HTML overlays are not depth-occluded).
export function frontPoints(points,pov,limit=80) {
  return points.filter(p=>angularDistance({lat:p.lat,lon:p.lng},{lat:pov.lat,lon:pov.lng})<limit);
}
export function dashboardColor(id) { return `hsl(${(Number(id)*137.508%360).toFixed(2)}, 78%, 62%)`; }
export function clusterBaseRadius(count) { return count <= 1 ? .48 : Math.min(2.6, .8 + .26*Math.log2(count)); }
export function clusterDistance(altitude) { return altitude>1.8 ? 4 : altitude>1.1 ? 2.5 : altitude>.65 ? 1.2 : altitude>.35 ? .45 : .15; }
export const validLocation = p => Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&Math.abs(p.lat)<=90&&Math.abs(p.lon)<=180;
const radians = Math.PI/180;
export function angularDistance(a,b) {
  const cosine=Math.sin(a.lat*radians)*Math.sin(b.lat*radians)+Math.cos(a.lat*radians)*Math.cos(b.lat*radians)*Math.cos((a.lon-b.lon)*radians);
  return Math.acos(Math.max(-1,Math.min(1,cosine)))/radians;
}

export function sphericalCentre(reports) {
  const first=reports[0];
  if(reports.every(p=>p.lat===first.lat&&p.lon===first.lon)) return {lat:first.lat,lon:first.lon};
  const [x,y,z]=reports.reduce((sum,p)=>{
    const lat=p.lat*radians,lon=p.lon*radians;
    return [sum[0]+Math.cos(lat)*Math.cos(lon),sum[1]+Math.cos(lat)*Math.sin(lon),sum[2]+Math.sin(lat)];
  },[0,0,0]);
  if(Math.hypot(x,y,z)<1e-8) return {lat:first.lat,lon:first.lon};
  return {lat:Math.atan2(z,Math.hypot(x,y))/radians,lon:Math.atan2(y,x)/radians};
}

export function globePoints(dashboards, hidden=new Set(), distance=0) {
  const locations=new Map();
  for(const dashboard of dashboards) {
    if(hidden.has(dashboard.id)) continue;
    const seen=new Set(),groups=[];
    // Fixed seeds avoid joining a long chain of neighbouring cities into one huge cluster.
    for(const article of [...dashboard.points].sort((a,b)=>Number(a.id)-Number(b.id))) {
      if(seen.has(article.id)||!validLocation(article)) continue;
      seen.add(article.id);
      let group=groups.find(g=>distance ? angularDistance(article,g[0])<=distance : article.lat===g[0].lat&&article.lon===g[0].lon);
      if(!group) groups.push(group=[]);
      group.push(article);
    }
    for(const places of groups) {
      // A point may be a single article or a server-aggregated place {count, reports}.
      const centre=sphericalCentre(places),key=`${centre.lat.toFixed(7)}|${centre.lon.toFixed(7)}`;
      const reports=places.flatMap(p=>Array.isArray(p.reports)?p.reports:[p]);
      const count=places.reduce((sum,p)=>sum+(Number.isInteger(p.count)?p.count:1),0);
      if(!locations.has(key)) locations.set(key,[]);
      locations.get(key).push({lat:centre.lat,lng:centre.lon,dashboard_id:dashboard.id,dashboard_name:dashboard.name,
        color:dashboardColor(dashboard.id),reports,count,
        clustered:places.some(p=>p.lat!==places[0].lat||p.lon!==places[0].lon)});
    }
  }
  const points=[];
  for(const groups of locations.values()) {
    groups.sort((a,b)=>a.dashboard_id-b.dashboard_id).forEach((point,index)=>points.push({...point,
      radius:clusterBaseRadius(point.count)+index*.15/Math.max(1,groups.length-1),
      altitude:.16+(groups.length-1-index)*Math.min(.018,.1/Math.max(1,groups.length-1))}));
  }
  return points;
}

export function countryPaths(countries) {
  return countries.flatMap(country=>{
    const g=country.geometry,polygons=g.type==='Polygon'?[g.coordinates]:g.type==='MultiPolygon'?g.coordinates:[];
    return polygons.flatMap(polygon=>polygon.map(ring=>({kind:'country',color:'#858585',coordinates:ring.map(([lng,lat])=>[lat,lng,.002])})));
  });
}
export function wireframePaths() {
  const paths=[];
  for(let lng=-180;lng<180;lng+=30) paths.push({kind:'grid',color:'#303030',coordinates:Array.from({length:61},(_,i)=>[-90+i*3,lng,.001])});
  for(let lat=-60;lat<=60;lat+=30) paths.push({kind:'grid',color:'#303030',coordinates:Array.from({length:121},(_,i)=>[lat,-180+i*3,.001])});
  return paths;
}
export function surfaceCircle(lat,lng,radius,segments=40) {
  const phi=lat*radians,lambda=lng*radians,delta=radius*radians;
  const centre=[Math.cos(phi)*Math.cos(lambda),Math.sin(phi),Math.cos(phi)*Math.sin(lambda)];
  const north=[-Math.sin(phi)*Math.cos(lambda),Math.cos(phi),-Math.sin(phi)*Math.sin(lambda)],east=[-Math.sin(lambda),0,Math.cos(lambda)];
  const coordinates=Array.from({length:segments},(_,i)=>{
    const bearing=i/segments*2*Math.PI;
    const p=centre.map((value,axis)=>Math.cos(delta)*value+Math.sin(delta)*(Math.cos(bearing)*north[axis]+Math.sin(bearing)*east[axis]));
    return [Math.asin(Math.max(-1,Math.min(1,p[1])))/radians,((Math.atan2(p[2],p[0])/radians+540)%360)-180,.004];
  });
  return [...coordinates,coordinates[0]];
}
export function eventPaths(points) {
  return points.flatMap(event=>[
    {kind:'event',part:'base',event,color:event.color,coordinates:surfaceCircle(event.lat,event.lng,event.radius)},
    {kind:'event',part:'stem',event,color:event.color,coordinates:[[event.lat,event.lng,.004],[event.lat,event.lng,event.altitude]]},
  ]);
}
// Cities within ~80° of the view centre face the camera.
export function frontCities(cities,pov,limit=80) {
  return cities.filter(c=>angularDistance({lat:c.lat,lon:c.lng},{lat:pov.lat,lon:pov.lng})<limit);
}
export function cityDetailLevel(altitude) { return altitude>1.3 ? 0 : altitude>.7 ? 1 : 2; }
export function majorCities(cities,altitude=2.2) {
  const level=cityDetailLevel(altitude),minPopulation=[5_000_000,2_000_000,1_000_000][level],minDistance=[12,7,3.5][level],maxCount=[35,65,100][level],selected=[];
  for(const city of [...cities].sort((a,b)=>b.population-a.population)) {
    if(city.population<minPopulation) continue;
    if(selected.every(other=>angularDistance({lat:city.lat,lon:city.lng},{lat:other.lat,lon:other.lng})>=minDistance)) selected.push(city);
    if(selected.length>=maxCount) break;
  }
  // The renderer binds Three.js objects onto records; never mutate cached geography.
  return selected.map(city=>({...city}));
}

function loadGlobe() {
  if(window.Globe) return Promise.resolve();
  if(!globeLoader) globeLoader=new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src=GLOBE_URL;script.async=true;
    script.onload=resolve;
    script.onerror=()=>{script.remove();globeLoader=null;reject(new Error('Could not load globe library'));};
    document.head.append(script);
  });
  return globeLoader;
}
function loadGeography() {
  if(!geographyLoader) geographyLoader=fetch('/static/globe-geography.json').then(response=>{
    if(!response.ok) throw new Error('Geographic context unavailable');
    return response.json();
  }).catch(error=>{geographyLoader=null;throw error;});
  return geographyLoader;
}

export function eventDetailsHtml(point,esc,safeUrl) {
  const reports=[...point.reports].sort((a,b)=>String(b.published_at).localeCompare(String(a.published_at)));
  return `<h3 style="color:${point.color}">${esc(point.dashboard_name)} · ${point.count} mapped article${point.count===1?'':'s'}</h3>
    ${point.clustered?'<p>Nearby locations are grouped at this zoom level. Zoom in to separate them.</p>':''}
    <ul>${reports.slice(0,20).map(a=>`<li><a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a> <span class="faint">${esc(String(a.published_at||'').slice(0,10))} · ${esc(a.location_name||'Location approximate')} · ${esc(a.geo_precision||'approximate')}</span></li>`).join('')}</ul>
    ${point.count>reports.length||reports.length>20?`<p>Showing the latest ${Math.min(20,reports.length)} of ${point.count} reports here.</p>`:''}${point.dashboard_id!=null?`<a href="#/dash/${point.dashboard_id}">Open dashboard</a>`:''}`;
}

export function createWireframeGlobe(host,{esc,onSelect=()=>{},onChange=()=>{},onError=()=>{}}={}) {
  let globe,observer,labelTimer,geography,basePaths=[],dashboards=[],hidden=new Set(),disposed=false,cityLevel,currentDistance,rotate=false,pendingFocus=false;
  let resetView={lat:25,lng:15,altitude:2.2};
  const duration=matchMedia('(prefers-reduced-motion: reduce)').matches?0:400;
  const fit=()=>{
    const reports=dashboards.filter(d=>!hidden.has(d.id)).flatMap(d=>d.points).filter(validLocation);
    if(!reports.length) return;
    const centre=sphericalCentre(reports),extent=Math.max(...reports.map(p=>angularDistance(p,centre)));
    resetView=extent>85?{lat:25,lng:15,altitude:2.2}:{lat:Math.max(-70,Math.min(70,centre.lat-12)),lng:centre.lon,altitude:Math.max(.8,Math.min(2.2,.8+extent/30))};
    globe?.pointOfView(resetView,0);
  };
  let clusters=[];
  // One HTML layer holds both city labels and event dots. Data is replaced only when the
  // clustering or the dashboards change; rotation just toggles element visibility.
  let idleTimer=null,frame=null,cityRecords=[],eventRecords=[];
  const elements=new Map();
  const render=()=>{elements.clear();globe?.htmlElementsData([...cityRecords,...eventRecords]);applyVisibility();};
  const applyVisibility=()=>{
    if(!globe) return;
    const pov=globe.pointOfView();
    for(const [record,element] of elements) {
      const show=angularDistance({lat:record.lat,lon:record.lng},{lat:pov.lat,lon:pov.lng})<80;
      if(element.hidden===show) element.hidden=!show;
    }
  };
  const update=()=>{
    if(disposed) return;
    const altitude=globe?.pointOfView().altitude??resetView.altitude, distance=clusterDistance(altitude);
    currentDistance=distance;
    clusters=globePoints(dashboards,hidden,distance);
    // Several dashboards at the same spot sit side by side instead of hiding each other.
    const stacks=new Map();
    for(const point of clusters) {const key=`${point.lat.toFixed(4)}|${point.lng.toFixed(4)}`;stacks.set(key,(stacks.get(key)||0)+1);point.stack=stacks.get(key)-1;point.stackSize=0;}
    for(const point of clusters) point.stackSize=stacks.get(`${point.lat.toFixed(4)}|${point.lng.toFixed(4)}`);
    eventRecords=clusters.map(point=>({...point,kind:'event'}));
    render();
    onChange({points:clusters,reportCount:clusters.reduce((sum,p)=>sum+p.count,0),distance});
  };
  const cameraChange=()=>{
    if(!globe||disposed||frame) return;
    frame=requestAnimationFrame(()=>{
      frame=null;
      if(!globe||disposed) return;
      const pov=globe.pointOfView(),level=cityDetailLevel(pov.altitude);
      if(level!==cityLevel) {cityLevel=level;cityRecords=majorCities(geography.cities,pov.altitude).map(c=>({...c,kind:'city'}));render();}
      else applyVisibility();
      // Re-cluster only after the camera settles.
      if(clusterDistance(pov.altitude)!==currentDistance) {clearTimeout(idleTimer);idleTimer=setTimeout(update,250);}
    });
  };
  const controller={
    setDashboards(value,excluded=new Set(),{focus=false}={}) {
      dashboards=value;hidden=new Set(excluded);pendingFocus=focus||pendingFocus;
      if(pendingFocus&&globe) {fit();pendingFocus=false;}
      update();
    },
    action(action) {
      if(!globe) return;
      const pov=globe.pointOfView();
      if(action==='reset') globe.pointOfView(resetView,duration);
      else if(action==='left'||action==='right') globe.pointOfView({lng:pov.lng+(action==='left'?-30:30)},duration);
      else globe.pointOfView({altitude:Math.max(.2,Math.min(5,pov.altitude*(action==='in' ? .75 : 1.3)))},duration);
    },
    setAutoRotate(value) {rotate=value;if(globe) globe.controls().autoRotate=rotate;},
    dispose() {
      disposed=true;observer?.disconnect();clearInterval(labelTimer);clearTimeout(idleTimer);if(frame) cancelAnimationFrame(frame);
      globe?.controls().removeEventListener('change',cameraChange);globe?._destructor?.();globe=null;
    },
  };
  controller.ready=(async()=>{
    try {
      const [,asset]=await Promise.all([loadGlobe(),loadGeography()]);
      if(disposed||!host.isConnected) return null;
      geography=asset;basePaths=[...wireframePaths(),...countryPaths(geography.countries)];
      // Dark wireframe globe on a starfield with dashboard-coloured event dots.
      globe=new window.Globe(host,{animateIn:duration>0}).width(host.clientWidth).height(host.clientHeight)
        .backgroundImageUrl(TEXTURES+'night-sky.png').backgroundColor('#000000')
        .globeImageUrl(null).bumpImageUrl(null).showAtmosphere(false).showGraticules(false)
        .pathsData(basePaths).pathPoints('coordinates').pathPointLat(p=>p[0]).pathPointLng(p=>p[1]).pathPointAlt(p=>p[2]+.006)
        .pathColor('color').pathStroke(null).pathResolution(2).pathTransitionDuration(0)
        .enablePointerInteraction(true).pointerEventsFilter(()=>false)
        // Far-side labels/dots are hidden by our own front-facing check (applyVisibility).
        .htmlElementVisibilityModifier(element=>{element.style.display='';})
        .htmlAltitude(record=>record.kind==='event'?.01:.006)
        .htmlLat('lat').htmlLng('lng').htmlTransitionDuration(0)
        .htmlElement(record=>{
          let element;
          if(record.kind==='event') {
            const size=dotSize(record.count),label=dotLabel(record.count);
            element=document.createElement('button');element.type='button';element.className='globe-dot';
            element.style.setProperty('--dot-color',record.color);element.style.setProperty('--dot-size',`${size}px`);
            // Side-by-side offset for several dashboards at the same place.
            element.style.setProperty('--dot-offset',`${(record.stack-(record.stackSize-1)/2)*(size*.8)}px`);
            element.textContent=label;element.classList.toggle('has-count',Boolean(label));
            element.title=`${record.dashboard_name}: ${record.count} article${record.count===1?'':'s'}${record.clustered?' (nearby locations grouped)':''}`;
            element.setAttribute('aria-label',`${element.title}. Show sources`);
            element.onclick=event=>{event.stopPropagation();onSelect(record);};
          } else {
            element=document.createElement('span');element.className='globe-city';element.setAttribute('aria-hidden','true');
            const dot=document.createElement('span');dot.className='globe-city-dot';
            const name=document.createElement('span');name.className='globe-city-name';name.textContent=record.name;element.append(dot,name);
          }
          elements.set(record,element);return element;
        });
      // Cap Retina rendering cost; visually indistinguishable for thin lines.
      globe.renderer().setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));
      const material=globe.globeMaterial();material.color.set('#111111');material.emissive.set('#050505');material.specular.set('#000000');material.shininess=0;
      globe.controls().autoRotate=rotate;globe.controls().autoRotateSpeed=.35;globe.controls().enablePan=false;
      globe.pointOfView(resetView);
      if(pendingFocus) {fit();pendingFocus=false;}
      globe.controls().addEventListener('change',cameraChange);cameraChange();update();
      // Programmatic camera moves/animations don't always emit control events; re-check labels periodically.
      labelTimer=setInterval(cameraChange,500);
      observer=new ResizeObserver(()=>{if(!disposed&&host.clientWidth) globe.width(host.clientWidth).height(host.clientHeight);});observer.observe(host);
      return globe;
    } catch(error) {
      observer?.disconnect();clearInterval(labelTimer);globe?._destructor?.();globe=null;
      if(!disposed&&host.isConnected) {
        host.innerHTML='<div class="globe-unavailable">The globe requires WebGL, the geographic context file and the globe library/starfield CDN. Try hardware acceleration and reload. Reports and graphs remain available.</div>';
        onError(error);
      }
      return null;
    }
  })();
  return controller;
}
