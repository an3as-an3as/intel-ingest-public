import test from 'node:test';
import assert from 'node:assert/strict';
import {dashboardColor, globePoints, eventPaths, surfaceCircle, countryPaths, wireframePaths, majorCities, clusterBaseRadius, clusterDistance, angularDistance} from '../wireframe-globe.js';
import {readFileSync} from 'node:fs';
const report = (id,lat=10,lon=20) => ({id,lat,lon,title:`Report ${id}`});

test('dashboard colours are stable across order, reloads and toggles', () => {
  assert.equal(dashboardColor(7),dashboardColor('7'));
  const colours = Array.from({length:50},(_,i)=>dashboardColor(i+1));
  assert.equal(new Set(colours).size,50);
  assert.match(colours[0],/^hsl\([\d.]+, 78%, 62%\)$/);
});

test('overlays group coincident reports per dashboard without moving coordinates', () => {
  const dashboards = [{id:1,name:'A',points:[report(1),report(1),report(2)]},
    {id:2,name:'B',points:[report(1),report(3,30,40)]}];
  const points = globePoints(dashboards);
  assert.equal(points.length,3);
  const a = points.find(p=>p.dashboard_id===1);
  const b = points.find(p=>p.dashboard_id===2&&p.lat===10);
  assert.equal(a.count,2);assert.equal(b.count,1);
  assert.equal(a.lat,10);assert.equal(a.lng,20);
  assert.ok(a.radius>b.radius);assert.ok(a.altitude>b.altitude);
  assert.notEqual(a.color,b.color);
  const visible = globePoints(dashboards,new Set([1]));
  assert.equal(visible.length,2);assert.ok(visible.every(p=>p.dashboard_id===2));
  assert.deepEqual(globePoints(dashboards,new Set([1,2])),[]);
});

test('invalid coordinates are excluded while equator and prime meridian remain valid', () => {
  const points = globePoints([{id:1,name:'A',points:[report(1,0,0),report(2,null,0),report(3,95,20),report(4,10,200),report(5,NaN,20)]}]);
  assert.equal(points.length,1);assert.equal(points[0].reports[0].id,1);
});

test('events are unfilled surface circles and straight radial stems', () => {
  const points = globePoints([{id:1,name:'A',points:[report(1)]}]);
  const paths = eventPaths(points);
  assert.equal(paths.length,2);
  const base = paths.find(p=>p.part==='base'), stem = paths.find(p=>p.part==='stem');
  assert.equal(base.coordinates.length,41);
  assert.deepEqual(base.coordinates[0],base.coordinates.at(-1));
  assert.equal(stem.coordinates.length,2);
  assert.deepEqual(stem.coordinates[0].slice(0,2),stem.coordinates[1].slice(0,2));
  assert.equal(stem.coordinates[0][2],.004);
  assert.ok(stem.coordinates[1][2]>.1);
  assert.equal(stem.color,points[0].color);
  assert.equal(stem.event,points[0]);
});

test('surface circles remain finite and small at poles and across the date line', () => {
  for(const [lat,lng] of [[90,0],[-90,0],[0,179.9],[0,-179.9],[52,23]]) {
    const circle=surfaceCircle(lat,lng,.5);
    assert.equal(circle.length,41);
    for(const [latitude,longitude,altitude] of circle) {
      assert.ok(Number.isFinite(latitude)&&Math.abs(latitude)<=90);
      assert.ok(Number.isFinite(longitude)&&Math.abs(longitude)<=180);
      assert.equal(altitude,.004);
    }
    if(Math.abs(lat)===90) assert.ok(new Set(circle.slice(0,-1).map(p=>p[1].toFixed(1))).size>30);
  }
});

test('basemap has grayscale outline paths, including polygon holes and separate islands', () => {
  const ring=[[0,0],[1,0],[0,1],[0,0]];
  const paths=countryPaths([{geometry:{type:'Polygon',coordinates:[ring,ring]}},{geometry:{type:'MultiPolygon',coordinates:[[ring],[ring]]}}]);
  assert.equal(paths.length,4);
  assert.deepEqual(paths[0].coordinates[1],[0,1,.002]);
  assert.ok(paths.every(p=>p.kind==='country'&&p.color==='#858585'));
  const grid=wireframePaths();assert.equal(grid.length,17);
  assert.ok(grid.every(p=>p.kind==='grid'&&p.color==='#303030'));
});

test('geographic context labels only major cities and becomes more detailed on zoom', () => {
  const geography=JSON.parse(readFileSync(new URL('../globe-geography.json',import.meta.url)));
  assert.ok(geography.countries.length>=170);
  assert.ok(geography.cities.length>100);
  const far=majorCities(geography.cities,2.2), near=majorCities(geography.cities,.4);
  assert.ok(far.length<=35&&far.every(c=>c.population>=5_000_000));
  assert.ok(near.length<=100&&near.every(c=>c.population>=1_000_000));
  assert.ok(near.length>far.length);
  assert.ok(far.some(c=>c.name==='Tokyo'));
});

test('base circles grow with cluster size while remaining bounded', () => {
  const radii=[1,2,5,10,50,100].map(clusterBaseRadius);
  assert.ok(radii.every((radius,index)=>index===0||radius>radii[index-1]));
  assert.ok(clusterBaseRadius(100000)<=2.6);
  const points=globePoints([{id:1,name:'A',points:Array.from({length:10},(_,i)=>report(i+1))}]);
  assert.equal(points[0].count,10);
  assert.equal(points[0].radius,clusterBaseRadius(10));
});

test('nearby reports cluster at overview zoom and separate when zoomed in', () => {
  const dashboards=[{id:1,name:'A',points:[report(1,0,0),report(2,0,.7),report(3,0,2)]}];
  const far=globePoints(dashboards,new Set(),clusterDistance(2.2));
  const near=globePoints(dashboards,new Set(),clusterDistance(.3));
  assert.equal(far.length,1);assert.equal(far[0].count,3);assert.ok(far[0].clustered);
  assert.equal(near.length,3);assert.ok(near.every(p=>p.count===1));
  assert.ok(far[0].radius>near[0].radius);
  assert.equal(far.reduce((sum,p)=>sum+p.count,0),near.reduce((sum,p)=>sum+p.count,0));
});

test('clustering handles the date line, is order-stable and never mixes dashboard identities', () => {
  const reports=[report(1,0,179.8),report(2,0,-179.8)];
  const first=globePoints([{id:1,name:'A',points:reports}],new Set(),1);
  const reverse=globePoints([{id:1,name:'A',points:[...reports].reverse()}],new Set(),1);
  assert.equal(first.length,1);assert.equal(first[0].count,2);
  assert.ok(Math.abs(first[0].lng)>179);
  assert.deepEqual(first,reverse);
  const both=globePoints([{id:1,name:'A',points:reports},{id:2,name:'B',points:reports}],new Set(),1);
  assert.equal(both.length,2);assert.notEqual(both[0].color,both[1].color);
  assert.equal(angularDistance({lat:90,lon:0},{lat:90,lon:180}),0);
});

test('clusters use bounded seeds, rather than a chain spanning unrelated cities', () => {
  const points=globePoints([{id:1,name:'A',points:[report(1,0,0),report(2,0,1),report(3,0,1.9)]}],new Set(),1.1);
  assert.equal(points.length,2);
  assert.equal(points.reduce((sum,p)=>sum+p.count,0),3);
});

test('many coincident overlays do not create continent-sized markers', () => {
  const points = globePoints(Array.from({length:100},(_,i)=>({id:i+1,name:String(i),points:[report(1)]})));
  assert.equal(points.length,100);
  assert.ok(points.every(p=>p.radius<3&&p.altitude<=.261));
});

import {dotSize, dotLabel, frontPoints, DOT_MAX, DOT_MIN} from '../wireframe-globe.js';

test('event dots grow with count up to a cap, then only the number grows', () => {
  assert.equal(dotSize(1), DOT_MIN);
  assert.ok(dotSize(4) > dotSize(2) && dotSize(2) > dotSize(1));
  assert.equal(dotSize(1000), DOT_MAX);
  assert.equal(dotSize(100000), DOT_MAX);
  assert.deepEqual([dotLabel(1), dotLabel(7), dotLabel(150), dotLabel(2500)], ['', '7', '150', '2k+']);
  const points=[{lat:48,lng:2},{lat:34,lng:-118}];
  assert.equal(frontPoints(points,{lat:25,lng:15}).length,1);
});

import {frontCities} from '../wireframe-globe.js';
test('far-side city labels are hidden', () => {
  const cities=[{name:'Paris',lat:48.9,lng:2.4},{name:'Los Angeles',lat:34,lng:-118}];
  assert.deepEqual(frontCities(cities,{lat:25,lng:15}).map(c=>c.name),['Paris']);
});
