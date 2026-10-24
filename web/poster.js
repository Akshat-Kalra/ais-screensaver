// Poster view: all of a region's tracks from the last 12 hours on one chart.
// /poster.html?region=salish
import { buildStyle, addPatterns, INK, PAPER } from './map-style.js';

const params = new URLSearchParams(location.search);
const regionId = params.get('region') || 'rotterdam';
const api = params.get('api') || '';

const map = new maplibregl.Map({
  container: 'map',
  style: buildStyle(),
  interactive: false,
  attributionControl: false,
  fadeDuration: 0,
  preserveDrawingBuffer: true,
  renderWorldCopies: false,
  center: [0, 20],
  zoom: 2,
});
map.on('styleimagemissing', (e) => { if (e.id.startsWith('land') && !map.hasImage('land-dots')) addPatterns(map); });

const fmtCoord = (v, pos, neg) => {
  const a = Math.abs(v);
  return `${String(Math.floor(a)).padStart(2, '0')}°${String(Math.round((a % 1) * 60)).padStart(2, '0')}′${v >= 0 ? pos : neg}`;
};

async function main() {
  const [data] = await Promise.all([
    fetch(`${api}/api/tracks?region=${encodeURIComponent(regionId)}`).then((r) => r.json()),
    new Promise((r) => map.on('load', r)),
  ]);
  if (!map.hasImage('land-dots')) addPatterns(map);

  const lines = [];
  const ends = [];
  let points = 0;
  let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const t of data.tracks) {
    for (const seg of t.segments) {
      lines.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: seg } });
      points += seg.length;
      for (const [x, y] of seg) {
        w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
      }
    }
    // Only ships that went somewhere (~500 m) get an end marker; ships at anchor would just speckle the bay.
    const moved = t.segments.flat().some(([x, y]) => Math.hypot(x - t.last[0], y - t.last[1]) > 0.005);
    if (moved) ends.push({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: t.last } });
  }

  map.addSource('tracks', { type: 'geojson', data: { type: 'FeatureCollection', features: lines } });
  map.addSource('ends', { type: 'geojson', data: { type: 'FeatureCollection', features: ends } });
  // Charted ferry routes would read as tracks; the real ones are drawn instead.
  map.setLayoutProperty('ferry', 'visibility', 'none');
  // Slightly transparent ink so busy lanes darken where tracks pile up.
  map.addLayer({
    id: 'tracks', type: 'line', source: 'tracks',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': INK, 'line-width': 1.2, 'line-opacity': 0.75 },
  });
  map.addLayer({
    id: 'ends', type: 'circle', source: 'ends',
    paint: { 'circle-radius': 2, 'circle-color': INK },
  });

  const [bw, bs, be, bn] = data.bbox;
  const bounds = Number.isFinite(w) ? [[w, s], [e, n]] : [[bw, bs], [be, bn]];
  map.fitBounds(bounds, { padding: 60, animate: false });

  const vessels = data.tracks.filter((t) => t.segments.length).length;
  const date = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
    .format(new Date());
  const c = document.getElementById('cartouche');
  c.innerHTML = `
    <div class="cartouche-inner">
      <h1>${data.region.name}</h1>
      <p class="sub">Twelve hours of traffic</p>
      <dl>
        <dt>Vessels</dt><dd>${vessels.toLocaleString('en-US')}</dd>
        <dt>Positions</dt><dd>${points.toLocaleString('en-US')}</dd>
        <dt>Charted</dt><dd>${date}</dd>
        <dt>Centre</dt><dd>${fmtCoord((bs + bn) / 2, 'N', 'S')} ${fmtCoord((bw + be) / 2, 'E', 'W')}</dd>
      </dl>
    </div>`;
  c.hidden = false;

  await new Promise((r) => map.once('idle', r));
  await document.fonts.ready;
  document.body.dataset.ready = '1';
}

main();
