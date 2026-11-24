# Shared wireframe dashboard maps

All dashboard maps use `frontend/wireframe-globe.js`, including Main dashboard and
individual PIR dashboards. They share country outlines, a latitude/longitude grid,
major-city labels, event markers and clustering behaviour. No terrain textures,
Leaflet libraries or map tile requests are used.

## Dependencies and geographic context

- [globe.gl](https://github.com/vasturiano/globe.gl), MIT licensed, pinned to `2.46.2`:
  https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js
  The bundle includes Three.js/three-globe and loads only when a dashboard map opens.
- `frontend/globe-geography.json` is derived from Natural Earth's public-domain
  1:110m country and populated-place data:
  - https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson
  - https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_populated_places_simple.geojson
  - Terms: https://www.naturalearthdata.com/about/terms-of-use/
- Country outlines are approximate geographic context, not authoritative boundaries.
  Historical population rankings prioritise city labels; they are not current
  demographic estimates. Labels become more detailed when zooming in. Only major
  cities appear (source population thresholds of 5M, 2M and 1M), with decluttering.

## Events and clusters

Markers use one-pixel line geometry: a hollow circle just above the surface and a
straight radial stem. Base-circle radius grows with the mapped-article count and
is bounded so busy clusters do not hide the map. Colours identify dashboards.
Shared coordinates have concentric bases; stem height is decorative, not severity.
Hover/click a circle or stem to inspect the count and source reports.

Nearby reports cluster independently per dashboard. Seed-distance thresholds are
4°, 2.5°, 1.2°, 0.45° and 0.15° as the camera approaches the surface. Fixed seeds
avoid long chains merging unrelated regions. Cluster centres use spherical
coordinates (including across the date line) and are approximate summaries, not
exact event sites. Identical coordinates stay clustered at any zoom. Unique
article IDs count once within each overlay, but can occur in several overlays.

Individual dashboards initially focus on their reporting region. PIR/time filters
update the plotted reports; ordinary refresh preserves the camera position. The
main view supports toggled overlays, and both views resize with the sidebar. Counts
refer to articles, not independently verified or deduplicated real-world events.

Renderer resources, animation, resize observers and zoom listeners are disposed
when leaving a map. JavaScript modules, including transitive shared-renderer imports,
are versioned together to prevent mixing deployment versions.

All geographic context is served locally; event data comes from authenticated app
APIs. There are no external geocoding calls or event-data uploads. WebGL and access
to the globe library CDN are required; reporting and graphs remain usable otherwise.

API reference: https://github.com/vasturiano/globe.gl#api-reference
