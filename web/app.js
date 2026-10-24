import { buildStyle, addPatterns, PAPER, INK, GREY } from './map-style.js';
import { shipArt, MARKER } from './ships.js';
import { portName } from './ports.js';

// ---------------------------------------------------------------- config

const params = new URLSearchParams(location.search);
const flag = (k) => params.has(k) && params.get(k) !== '0';
const PREVIEW = flag('preview');
const CFG = {
  dwell: Math.max(10, Number(params.get('dwell')) || (PREVIEW ? 90 : 45)) * 1000,
  partial: 15_000,
  retry: 20_000,
  flash: !PREVIEW && params.get('flash') !== '0',
  api: params.get('api') || '',
};

const OLD_TRACK_S = 6 * 3600;
const GAP_S = 30 * 60;
const RECENT_MAX = 20;
const NM = 1852;

const $ = (id) => document.getElementById(id);
const els = {
  app: $('app'), card: $('card'), region: $('region'), utc: $('clock-utc'), local: $('clock-local'),
  count: $('count'), signal: $('signal'), graticule: $('graticule'), scale: $('scale'),
  flash: $('flash'), ghost: $('ghost'), sleep: $('sleep'), sleepArt: $('sleep-art'),
  sleepTitle: $('sleep-title'), sleepText: $('sleep-text'),
};

const state = { vessel: null, recent: [], cardNo: 0, health: null };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The screensaver has no console, so errors and milestones are sent to the collector's log.
function report(kind, detail = {}) {
  const body = JSON.stringify({ kind, t: Math.round(performance.now()), saver: flag('saver'), ...detail });
  fetch(`${CFG.api}/api/log`, { method: 'POST', body, keepalive: true }).catch(() => {});
}
window.addEventListener('error', (e) => report('error', { msg: e.message, src: `${e.filename}:${e.lineno}` }));
window.addEventListener('unhandledrejection', (e) => report('rejection', { msg: String(e.reason?.stack || e.reason) }));

// ---------------------------------------------------------------- api

async function api(path) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 8000);
  try {
    const res = await fetch(CFG.api + path, { signal: ctl.signal, cache: 'no-store' });
    const body = await res.json().catch(() => null);
    return { ok: res.ok, status: res.status, body };
  } finally {
    clearTimeout(t);
  }
}

// ---------------------------------------------------------------- formatting

const pad = (n, w = 2) => String(n).padStart(w, '0');

function dm(value, pos, neg, degWidth) {
  const hemi = value >= 0 ? pos : neg;
  const v = Math.abs(value);
  let d = Math.floor(v);
  let m = (v - d) * 60;
  if (Number(m.toFixed(1)) >= 60) { d += 1; m = 0; }
  return `${pad(d, degWidth)}°${m.toFixed(1).padStart(4, '0')}′${hemi}`;
}
const fmtPos = (lat, lon) => `${dm(lat, 'N', 'S', 2)} ${dm(lon, 'E', 'W', 3)}`;

function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${(s / 3600).toFixed(1)} h ago`;
}

function until(iso) {
  const s = (Date.parse(iso) - Date.now()) / 1000;
  if (!Number.isFinite(s)) return '';
  if (s < -3600) return 'overdue';
  if (s < 3600) return 'within the hour';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return d ? `in ${d}d ${h}h` : `in ${h}h`;
}

function fmtEta(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  return `${day} · ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;
}

function timeIn(tz) {
  try {
    return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: tz, hour12: false });
  } catch {
    return null;
  }
}

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const CATEGORY_LABEL = {
  cargo: 'Cargo', tanker: 'Tanker', passenger: 'Passenger', fishing: 'Fishing', tug: 'Tug',
  pleasure: 'Pleasure craft', sailing: 'Sailing', highspeed: 'High-speed craft', military: 'Military',
  special: 'Service', other: 'Vessel',
};

// ---------------------------------------------------------------- status bar

function renderStatus() {
  const now = new Date();
  els.utc.textContent = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())} UTC`;
  const tz = state.vessel?.region?.tz;
  const local = tz && timeIn(tz);
  els.local.textContent = local ? `Local ${local}` : '';
  const h = state.health;
  els.count.textContent = h ? `${h.vessels.toLocaleString('en-US')} ships` : '';
  const rate = h?.connected ? h.msgs_per_min : 0;
  const bars = !h ? 0 : !h.connected ? 0 : rate > 1500 ? 4 : rate > 500 ? 3 : rate > 60 ? 2 : 1;
  els.signal.innerHTML = [0.35, 0.55, 0.78, 1]
    .map((f, i) => `<i class="${i < bars ? 'on' : ''}" style="height:${f * 100}%"></i>`).join('');
}

async function refreshHealth() {
  try {
    const r = await api('/api/health');
    state.health = r.ok ? r.body : null;
  } catch {
    state.health = null;
  }
  renderStatus();
}

function startClock() {
  renderStatus();
  // E-ink style: the clock only changes on the minute.
  const tick = () => {
    renderStatus();
    setTimeout(tick, 60_000 - (Date.now() % 60_000) + 50);
  };
  setTimeout(tick, 60_000 - (Date.now() % 60_000) + 50);
  refreshHealth();
  setInterval(refreshHealth, 30_000);
}

// ---------------------------------------------------------------- card

function bar(fraction) {
  const n = fraction == null ? 0 : Math.max(fraction > 0 ? 1 : 0, Math.min(10, Math.round(fraction * 10)));
  return Array.from({ length: 10 }, (_, i) => `<i class="${i < n ? 'on' : ''}"></i>`).join('');
}

function statRows(v) {
  const s = v.stats || {};
  const rows = [
    ['length', 'Length', v.length_m, 400, 0, 'm'],
    ['beam', 'Beam', v.beam_m, 60, 0, 'm'],
    ['draught', 'Draught', v.draught_m, 20, 1, 'm'],
    ['speed', 'Speed', v.last?.sog, 25, 1, 'kn'],
    ['distance', 'Logged', s.distance_nm, 200, 0, 'nm'],
  ];
  return rows.map(([key, label, value, max, digits, unit]) => {
    const known = value != null && value > 0 || (key === 'speed' && value === 0);
    const val = known ? `${Number(value).toFixed(digits)}<small>${unit}</small>` : '—';
    return `<li class="stat ${known ? '' : 'unknown'}" data-key="${key}">
      <span class="label">${label}</span>
      <span class="bar">${bar(known ? value / max : null)}</span>
      <span class="val">${val}</span></li>`;
  }).join('');
}

function voyageRows(v) {
  const port = portName(v.destination);
  const course = v.last?.cog ?? v.last?.heading;
  const hours = v.stats?.track_hours;
  return `
    <div class="dest" data-key="dest">
      <span class="k">Bound for</span>
      <span class="v">${port ? esc(port.name) : 'Unknown'}</span>
      <span class="code">${port?.code ? esc(port.code) : ''}</span>
    </div>
    <div class="vrow" data-key="eta">
      <span class="k">ETA</span>
      <span>${v.eta ? esc(fmtEta(v.eta)) : '—'}</span>
      <span class="aux">${v.eta ? esc(until(v.eta)) : ''}</span>
    </div>
    <div class="vrow" data-key="status">
      <span class="k">Status</span>
      <span>${esc(v.nav_status || (v.last?.sog > 0.5 ? 'Under way' : '—'))}</span>
      <span class="aux">${course != null ? `${pad(Math.round(course) % 360, 3)}°` : ''}</span>
    </div>
    <div class="vrow" data-key="track">
      <span class="k">Tracked</span>
      <span>${hours ? `${hours.toFixed(1)} h` : '—'}</span>
      <span class="aux">${v.stats?.avg_sog != null ? `avg ${v.stats.avg_sog.toFixed(1)} kn` : ''}</span>
    </div>`;
}

function footRow(v) {
  return `<span data-key="pos">${fmtPos(v.last.lat, v.last.lon)}</span>
    <span class="dim" data-key="seen">heard ${ago(v.last.ts)}</span>`;
}

function renderCard(v) {
  const name = v.name || `MMSI ${v.mmsi}`;
  const size = name.length > 24 ? 1.75 : name.length > 18 ? 2.05 : name.length > 13 ? 2.35 : 2.7;
  const flagName = v.flag?.name || 'Unknown flag';
  els.card.innerHTML = `
    <div class="card-inner">
      <header class="card-head">
        <span class="no">No. ${pad(state.cardNo)}</span>
        <span class="cat">${esc(CATEGORY_LABEL[v.category] || 'Vessel')}</span>
      </header>
      <figure class="art">${shipArt(v.category, v.mmsi)}</figure>
      <h1 class="name" style="--name-size:${size}rem">${esc(name)}</h1>
      <p class="ident">
        <span>${esc(flagName)}</span>
        ${v.callsign ? `<span>${esc(v.callsign)}</span>` : ''}
        ${v.imo ? `<span>IMO ${v.imo}</span>` : `<span class="dim">MMSI ${v.mmsi}</span>`}
      </p>
      <ul class="stats">${statRows(v)}</ul>
      <section class="voyage">${voyageRows(v)}</section>
      <footer class="card-foot">${footRow(v)}</footer>
    </div>`;
}

// Partial refresh: patch only the bits that changed, and blink them.
function patchCard(v) {
  const swap = (container, html) => {
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    for (const fresh of tmp.querySelectorAll('[data-key]')) {
      const old = container.querySelector(`[data-key="${fresh.dataset.key}"]`);
      if (old && old.innerHTML.trim() !== fresh.innerHTML.trim()) {
        old.innerHTML = fresh.innerHTML;
        old.className = fresh.className;
        old.classList.remove('blink');
        void old.offsetWidth;
        old.classList.add('blink');
      }
    }
  };
  const card = els.card;
  swap(card.querySelector('.stats'), statRows(v));
  swap(card.querySelector('.voyage'), voyageRows(v));
  swap(card.querySelector('.card-foot'), footRow(v));
}

// ---------------------------------------------------------------- map

let map;
let mapReady = false;

function markerImage(shape, { size, fill, stroke, strokeWidth }) {
  const dpr = Math.max(1, Math.round(devicePixelRatio || 1));
  const px = size * dpr;
  const c = document.createElement('canvas');
  c.width = c.height = px;
  const g = c.getContext('2d');
  g.translate(px / 2, px / 2);
  const r = (px / 2) - strokeWidth * dpr;
  g.beginPath();
  shape.forEach(([x, y], i) => (i ? g.lineTo(x * r, y * r) : g.moveTo(x * r, y * r)));
  g.closePath();
  g.lineJoin = 'miter';
  if (stroke) { g.lineWidth = strokeWidth * 2 * dpr; g.strokeStyle = stroke; g.stroke(); }
  g.fillStyle = fill;
  g.fill();
  return { image: g.getImageData(0, 0, px, px), pixelRatio: dpr };
}

function squareImage(size) {
  const dpr = Math.max(1, Math.round(devicePixelRatio || 1));
  const px = size * dpr;
  const c = document.createElement('canvas');
  c.width = c.height = px;
  const g = c.getContext('2d');
  g.fillStyle = INK;
  g.fillRect(0, 0, px, px);
  g.fillStyle = PAPER;
  g.fillRect(1.5 * dpr, 1.5 * dpr, px - 3 * dpr, px - 3 * dpr);
  return { image: g.getImageData(0, 0, px, px), pixelRatio: dpr };
}

const EMPTY = { type: 'FeatureCollection', features: [] };

function initMap() {
  return new Promise((resolve) => {
    map = new maplibregl.Map({
      container: 'map',
      style: buildStyle(),
      interactive: false,
      attributionControl: false,
      fadeDuration: 0,
      preserveDrawingBuffer: true,
      renderWorldCopies: false,
      center: [0, 20],
      zoom: 2,
      maxZoom: 14,
    });
    window.aisDebug = { map };
    const ensurePatterns = () => {
      if (map.hasImage('land-dots')) return;
      try {
        addPatterns(map);
      } catch (err) {
        (window.__errs ||= []).push(String(err));
      }
    };
    map.on('styleimagemissing', (e) => { if (e.id.startsWith('land')) ensurePatterns(); });
    map.on('error', (e) => report('map-error', { msg: String(e.error?.message || e.error || e) }));
    map.on('load', () => {
      ensurePatterns();
      const ship = markerImage(MARKER.ship, { size: 26, fill: INK, stroke: PAPER, strokeWidth: 1.5 });
      const other = markerImage(MARKER.other, { size: 13, fill: PAPER, stroke: INK, strokeWidth: 1 });
      map.addImage('ship', ship.image, { pixelRatio: ship.pixelRatio });
      map.addImage('other', other.image, { pixelRatio: other.pixelRatio });
      const sq = squareImage(9);
      map.addImage('start', sq.image, { pixelRatio: sq.pixelRatio });

      for (const id of ['others', 'track', 'projection', 'ticks', 'start', 'ship']) {
        map.addSource(id, { type: 'geojson', data: EMPTY });
      }
      map.addLayer({
        id: 'others-still', type: 'circle', source: 'others', filter: ['!', ['get', 'moving']],
        paint: { 'circle-radius': 2.4, 'circle-color': PAPER, 'circle-stroke-color': INK, 'circle-stroke-width': 1 },
      });
      map.addLayer({
        id: 'others-moving', type: 'symbol', source: 'others', filter: ['get', 'moving'],
        layout: {
          'icon-image': 'other', 'icon-rotate': ['get', 'rot'], 'icon-rotation-alignment': 'map',
          'icon-allow-overlap': true, 'icon-ignore-placement': true,
        },
      });
      map.addLayer({
        id: 'track-halo', type: 'line', source: 'track',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': PAPER, 'line-width': 6 },
      });
      map.addLayer({
        id: 'track-old', type: 'line', source: 'track', filter: ['==', ['get', 'age'], 'old'],
        layout: { 'line-join': 'round' },
        paint: { 'line-color': INK, 'line-width': 1.6, 'line-dasharray': [2, 2] },
      });
      map.addLayer({
        id: 'track-recent', type: 'line', source: 'track', filter: ['==', ['get', 'age'], 'recent'],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': INK, 'line-width': 2.2 },
      });
      map.addLayer({
        id: 'projection', type: 'line', source: 'projection',
        paint: { 'line-color': INK, 'line-width': 1.2, 'line-dasharray': [1, 2.5] },
      });
      map.addLayer({
        id: 'ticks', type: 'circle', source: 'ticks',
        paint: { 'circle-radius': 2.6, 'circle-color': PAPER, 'circle-stroke-color': INK, 'circle-stroke-width': 1.3 },
      });
      map.addLayer({
        id: 'tick-labels', type: 'symbol', source: 'ticks', filter: ['!=', ['get', 'label'], ''],
        layout: {
          'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 10.5,
          'text-letter-spacing': 0.06, 'text-anchor': ['get', 'anchor'], 'text-offset': ['get', 'offset'],
          'text-allow-overlap': false,
        },
        paint: { 'text-color': INK, 'text-halo-color': PAPER, 'text-halo-width': 2 },
      });
      map.addLayer({
        id: 'start', type: 'symbol', source: 'start',
        layout: { 'icon-image': 'start', 'icon-allow-overlap': true },
      });
      map.addLayer({
        id: 'ship-disc', type: 'circle', source: 'ship',
        paint: {
          'circle-radius': 17, 'circle-color': PAPER, 'circle-stroke-color': INK, 'circle-stroke-width': 1,
        },
      });
      map.addLayer({
        id: 'ship', type: 'symbol', source: 'ship',
        layout: {
          'icon-image': 'ship', 'icon-rotate': ['get', 'rot'], 'icon-rotation-alignment': 'map',
          'icon-allow-overlap': true, 'icon-ignore-placement': true,
        },
      });
      mapReady = true;
      resolve();
    });
  });
}

function mapIdle(timeout = 4500) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    map.once('idle', finish);
    setTimeout(finish, timeout);
  });
}

function trackFeatures(track, lastTs) {
  // Split at reception gaps; colour by age (recent = solid, older = dashed).
  const features = [];
  let seg = [];
  let segAge = null;
  const push = () => {
    if (seg.length > 1) features.push({ type: 'Feature', properties: { age: segAge }, geometry: { type: 'LineString', coordinates: seg } });
  };
  for (let i = 0; i < track.length; i++) {
    const [lon, lat, ts] = track[i];
    const age = lastTs - ts > OLD_TRACK_S ? 'old' : 'recent';
    if (i > 0 && ts - track[i - 1][2] > GAP_S) { push(); seg = []; segAge = null; }
    if (segAge && age !== segAge) {
      seg.push([lon, lat]);
      push();
      seg = [[lon, lat]];
    } else {
      seg.push([lon, lat]);
    }
    segAge = age;
  }
  push();
  return features;
}

function positionAt(track, t) {
  // Returns [point, segment direction] at time t, or null inside a reception gap.
  for (let i = 1; i < track.length; i++) {
    const [lon1, lat1, t1] = track[i - 1];
    const [lon2, lat2, t2] = track[i];
    if (t1 <= t && t <= t2) {
      if (t2 - t1 > GAP_S) return null;
      const f = (t - t1) / Math.max(1, t2 - t1);
      const dx = (lon2 - lon1) * Math.cos((lat1 * Math.PI) / 180);
      return [[lon1 + (lon2 - lon1) * f, lat1 + (lat2 - lat1) * f], [dx, lat2 - lat1]];
    }
  }
  return null;
}

function tickFeatures(track) {
  if (track.length < 2) return [];
  const last = track[track.length - 1][2];
  const span = last - track[0][2];
  const hours = Math.floor(span / 3600);
  const every = hours > 8 ? 3 : hours > 4 ? 2 : 1;
  const out = [];
  for (let h = 1; h <= hours; h++) {
    const at = positionAt(track, last - h * 3600);
    if (!at) continue;
    const [p, [dx, dy]] = at;
    // Put the label beside the line, never on it: below a horizontal track, right of a vertical one.
    const horizontal = Math.abs(dx) > Math.abs(dy);
    out.push({
      type: 'Feature',
      properties: {
        label: h % every === 0 ? `−${h}h` : '',
        anchor: horizontal ? 'top' : 'left',
        offset: horizontal ? [0, 0.7] : [0.8, 0],
      },
      geometry: { type: 'Point', coordinates: p },
    });
  }
  return out;
}

function destPoint(lon, lat, bearingDeg, distM) {
  const R = 6371e3;
  const b = (bearingDeg * Math.PI) / 180;
  const p1 = (lat * Math.PI) / 180;
  const l1 = (lon * Math.PI) / 180;
  const d = distM / R;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [(l2 * 180) / Math.PI, (p2 * 180) / Math.PI];
}

function shipRotation(last) {
  return last.heading ?? last.cog ?? 0;
}

function projection(v) {
  const { lon, lat, sog, cog } = v.last;
  if (!sog || sog < 0.5 || cog == null) return null;
  const to = destPoint(lon, lat, cog, sog * NM * (20 / 60)); // 20 minutes ahead
  return { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[lon, lat], to] } };
}

function setMapData(v, nearby) {
  const fc = (features) => ({ type: 'FeatureCollection', features });
  const last = v.track.length ? v.track[v.track.length - 1][2] : v.last.ts;
  map.getSource('track').setData(fc(trackFeatures(v.track, last)));
  map.getSource('ticks').setData(fc(tickFeatures(v.track)));
  const proj = projection(v);
  map.getSource('projection').setData(fc(proj ? [proj] : []));
  map.getSource('start').setData(fc(v.track.length > 1
    ? [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: v.track[0].slice(0, 2) } }] : []));
  map.getSource('ship').setData(fc([{
    type: 'Feature', properties: { rot: shipRotation(v.last) },
    geometry: { type: 'Point', coordinates: [v.last.lon, v.last.lat] },
  }]));
  if (nearby) {
    map.getSource('others').setData(fc(nearby.filter((o) => o.mmsi !== v.mmsi).map((o) => ({
      type: 'Feature',
      properties: { rot: o.heading ?? o.cog ?? 0, moving: (o.sog ?? 0) >= 0.5 && (o.cog != null || o.heading != null) },
      geometry: { type: 'Point', coordinates: [o.lon, o.lat] },
    }))));
  }
}

function frameVessel(v) {
  const pts = v.track.map((p) => [p[0], p[1]]);
  pts.push([v.last.lon, v.last.lat]);
  const proj = projection(v);
  if (proj) pts.push(proj.geometry.coordinates[1]);
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of pts) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  // Never zoom in too far: keep some coast in view. Ships that barely moved get a wider view.
  const still = Math.max(maxX - minX, maxY - minY) < 0.01;
  const minSpan = still ? 0.07 : 0.03;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const hx = Math.max((maxX - minX) / 2, minSpan / Math.cos((cy * Math.PI) / 180));
  const hy = Math.max((maxY - minY) / 2, minSpan);
  const box = map.getContainer().getBoundingClientRect();
  const pad = Math.round(Math.min(box.width, box.height) * 0.14);
  map.fitBounds([[cx - hx, cy - hy], [cx + hx, cy + hy]], { padding: pad, maxZoom: 13.5, animate: false });
}

// ---------------------------------------------------------------- graticule + scale

const MINUTE_STEPS = [0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600];

function renderGraticule() {
  const b = map.getBounds();
  const box = map.getContainer().getBoundingClientRect();
  const spanMin = Math.max(b.getEast() - b.getWest(), b.getNorth() - b.getSouth()) * 60;
  const step = MINUTE_STEPS.find((s) => spanMin / s <= 6) || 600;
  const label = (deg, pos, neg, w) => {
    const hemi = deg >= 0 ? pos : neg;
    const v = Math.abs(deg);
    let d = Math.floor(v + 1e-9);
    const m = Math.round((v - d) * 60 * 10) / 10;
    const mm = m >= 60 ? 0 : m;
    if (m >= 60) d += 1;
    const mStr = Number.isInteger(mm) ? pad(mm) : mm.toFixed(1).padStart(4, '0');
    return `${pad(d, w)}°${mStr}′${hemi}`;
  };
  let html = '';
  const s = step / 60;
  for (let lon = Math.ceil(b.getWest() / s) * s; lon < b.getEast(); lon += s) {
    const x = map.project([lon, b.getCenter().lat]).x;
    if (x < 30 || x > box.width - 30) continue;
    html += `<i class="tick v" style="left:${x}px"></i><i class="tick v b" style="left:${x}px"></i>`;
    html += `<span class="lbl v" style="left:${x}px">${label(lon, 'E', 'W', 3)}</span>`;
  }
  for (let lat = Math.ceil(b.getSouth() / s) * s; lat < b.getNorth(); lat += s) {
    const y = map.project([b.getCenter().lng, lat]).y;
    if (y < 40 || y > box.height - 80) continue; // keep clear of the scale bar
    html += `<i class="tick h" style="top:${y}px"></i><i class="tick h r" style="top:${y}px"></i>`;
    html += `<span class="lbl h" style="top:${y}px">${label(lat, 'N', 'S', 2)}</span>`;
  }
  els.graticule.innerHTML = html;
}

function renderScale() {
  const c = map.getCenter();
  const mpp = (40075016.686 * Math.cos((c.lat * Math.PI) / 180)) / (512 * 2 ** map.getZoom());
  const target = (map.getContainer().clientWidth * 0.14) * mpp / NM;
  const nice = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100].reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
  const px = (nice * NM) / mpp;
  els.scale.innerHTML = `<div class="bar" style="width:${px}px"><i></i><i></i><i></i><i></i></div>
    <div class="labels"><span>0</span><span>${nice} nm</span></div>`;
}

// ---------------------------------------------------------------- refresh effects

function setFlash(mode) {
  els.flash.className = `flash${mode ? ` ${mode}` : ''}`;
}

function captureGhost() {
  if (!state.vessel) return null;
  const nodes = [];
  try {
    const canvas = map.getCanvas();
    const r = canvas.getBoundingClientRect();
    const img = new Image();
    img.src = canvas.toDataURL('image/jpeg', 0.6);
    Object.assign(img.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
    nodes.push(img);
  } catch { /* canvas may be tainted or lost; skip the map ghost */ }
  const cr = els.card.getBoundingClientRect();
  const clone = els.card.cloneNode(true);
  clone.removeAttribute('id');
  Object.assign(clone.style, { left: `${cr.left}px`, top: `${cr.top}px`, width: `${cr.width}px`, height: `${cr.height}px`, display: 'flex' });
  nodes.push(clone);
  return nodes;
}

async function playGhost(nodes) {
  if (!nodes) return;
  els.ghost.replaceChildren(...nodes);
  // Residual image from the previous frame, fading in discrete steps.
  for (const o of [0.075, 0.045, 0.02, 0]) {
    els.ghost.style.opacity = String(o);
    await sleep(650);
  }
  els.ghost.replaceChildren();
}

function jitter() {
  const r = () => Math.round(Math.random() * 6 - 3);
  els.app.style.transform = `translate(${r()}px, ${r()}px)`;
}

async function fullRefresh(vessel, nearby) {
  const ghost = captureGhost();
  if (CFG.flash) {
    setFlash('ink');
    await sleep(140);
  }
  setFlash('paper');

  els.sleep.hidden = true;
  els.app.classList.remove('sleeping');
  state.cardNo += 1;
  state.vessel = vessel;
  jitter();
  renderCard(vessel);
  els.region.textContent = vessel.region?.name || 'Open water';
  renderStatus();
  if (mapReady) {
    frameVessel(vessel);
    setMapData(vessel, nearby);
    await Promise.all([mapIdle(), document.fonts.ready]);
    renderGraticule();
    renderScale();
  } else {
    await document.fonts.ready; // the card still works without a map
  }

  if (CFG.flash) {
    // The new frame flashes in negative, then settles: the classic e-ink full refresh.
    await sleep(120);
    els.app.classList.add('inverted');
    setFlash(null);
    await sleep(110);
    els.app.classList.remove('inverted');
    setFlash('paper');
    await sleep(70);
  }
  setFlash(null);
  playGhost(ghost);
  if (state.cardNo === 1) report('first-card', { mmsi: vessel.mmsi });
}

async function partialRefresh() {
  const v = state.vessel;
  if (!v) return false;
  const r = await api(`/api/vessel/${v.mmsi}`).catch(() => null);
  if (!r?.ok) return false;
  const fresh = r.body;
  if (Date.now() / 1000 - fresh.last.ts > 15 * 60) return false; // went quiet: move on
  state.vessel = fresh;
  if (mapReady) setMapData(fresh, null);
  patchCard(fresh);
  return true;
}

// ---------------------------------------------------------------- sleep screen

function showSleep(kind) {
  els.sleep.hidden = false;
  els.app.classList.add('sleeping');
  els.sleepArt.innerHTML = shipArt(kind === 'offline' ? 'other' : 'cargo', 7);
  els.region.textContent = kind === 'offline' ? 'Offline' : 'Listening';
  state.vessel = null;
  renderStatus();
  if (kind === 'offline') {
    els.sleepTitle.textContent = 'The collector is asleep';
    els.sleepText.innerHTML = 'Start it with <code>scripts/install-agent.sh</code>';
  } else {
    const n = state.health?.vessels ?? 0;
    els.sleepTitle.textContent = 'Listening for ships';
    els.sleepText.textContent = n
      ? `${n.toLocaleString('en-US')} heard so far · gathering their tracks`
      : 'Waiting for the first signals';
  }
}

// ---------------------------------------------------------------- main loop

async function next() {
  const exclude = state.recent.join(',');
  let r;
  try {
    r = await api(`/api/pick?exclude=${exclude}`);
  } catch {
    return { kind: 'offline' };
  }
  if (r.status === 404 && state.recent.length) {
    state.recent = []; // small fleet: allow repeats rather than going to sleep
    r = await api('/api/pick').catch(() => null);
  }
  if (!r?.ok) return { kind: r?.status === 404 ? 'empty' : 'offline' };
  const v = r.body;
  let nearby = [];
  try {
    const n = await api(`/api/nearby?lat=${v.last.lat}&lon=${v.last.lon}&radius_km=60&exclude=${v.mmsi}`);
    if (n.ok) nearby = n.body;
  } catch { /* context dots are optional */ }
  return { kind: 'vessel', vessel: v, nearby };
}

async function run() {
  for (;;) {
    const n = await next();
    if (n.kind !== 'vessel') {
      await refreshHealth();
      showSleep(n.kind);
      await sleep(CFG.retry);
      continue;
    }
    state.recent = [n.vessel.mmsi, ...state.recent.filter((m) => m !== n.vessel.mmsi)].slice(0, RECENT_MAX);
    await fullRefresh(n.vessel, n.nearby);

    const end = Date.now() + CFG.dwell;
    while (Date.now() < end) {
      await sleep(Math.min(CFG.partial, end - Date.now()));
      if (Date.now() >= end || PREVIEW) continue;
      if (!(await partialRefresh())) break;
    }
  }
}

async function probe() {
  let frames = 0;
  const count = () => { frames += 1; if (frames < 1000) requestAnimationFrame(count); };
  requestAnimationFrame(count);
  await sleep(2000);
  const gl = document.createElement('canvas').getContext('webgl2');
  report('probe', {
    ua: navigator.userAgent.slice(-60), visibility: document.visibilityState, hidden: document.hidden,
    rafIn2s: frames, webgl2: !!gl, size: `${innerWidth}x${innerHeight}@${devicePixelRatio}`,
  });
}

async function boot() {
  report('boot');
  probe();
  startClock();
  const loaded = await Promise.race([initMap().then(() => true), sleep(15_000).then(() => false)]);
  report(loaded ? 'map-loaded' : 'map-timeout', loaded ? {} : {
    styleLoaded: map?.isStyleLoaded?.() ?? null, tilesLoaded: map?.areTilesLoaded?.() ?? null,
  });
  run();
}

boot();
