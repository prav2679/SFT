// Single shared Leaflet map for all three workspaces.
// The map is created ONCE; its DOM node is moved into whichever <MissionMap> slot is
// mounted, so switching workspaces or receiving telemetry never re-initialises it.
// Layers are keyed ("ws1:actual", "ws2:tawhiri", ...) and only the affected layer is updated.
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

let map = null;
let container = null;
let scope = null;
const layers = new Map();        // key -> { layer, scope, meta, userHidden }
const listeners = new Set();

const BASE = {
  'Street (OSM)': () => L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap' }),
  Satellite: () => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Esri World Imagery' }),
  Terrain: () => L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', { maxZoom: 17, attribution: '© OpenTopoMap' }),
};

function notify() { listeners.forEach((fn) => fn()); }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export function getMap() {
  if (map) return map;
  container = document.createElement('div');
  container.className = 'mission-map-canvas';
  // Must be set inline BEFORE L.map(): Leaflet forces position:relative on a detached
  // container (empty computed style), which would collapse it to zero height.
  container.style.cssText = 'position:absolute;top:0;right:0;bottom:0;left:0;';
  // INITIAL VIEWPORT ONLY (convenience). The map centre / zoom is never read by any simulation or form: every
  // simulation coordinate comes from the user's inputs.
  map = L.map(container, { worldCopyJump: true, preferCanvas: true }).setView([13.08, 80.27], 8);
  const bases = Object.fromEntries(Object.entries(BASE).map(([k, f]) => [k, f()]));
  bases['Street (OSM)'].addTo(map);
  L.control.layers(bases, null, { position: 'topright' }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);
  return map;
}

export function attach(slot) {
  getMap();
  slot.prepend(container);
  requestAnimationFrame(() => map.invalidateSize());
}
export function invalidate() { map && map.invalidateSize(); }

export function setScope(s) {
  scope = s;
  for (const entry of layers.values()) applyVisibility(entry);
  notify();
}
function applyVisibility(e) {
  const visible = e.scope === scope && !e.userHidden;
  if (visible && !map.hasLayer(e.layer)) e.layer.addTo(map);
  if (!visible && map.hasLayer(e.layer)) map.removeLayer(e.layer);
}
export function toggleUser(key) {
  const e = layers.get(key);
  if (!e) return;
  e.userHidden = !e.userHidden;
  applyVisibility(e);
  notify();
}
const legendDefs = new Map();      // scope -> [{ key, label, colour, dashed }]
export function setLegend(forScope, defs) { legendDefs.set(forScope, defs); notify(); }
/** Declared legend rows for the current scope (always shown) merged with the live layer state. */
export function legendEntries() {
  const declared = legendDefs.get(scope) || [];
  const seen = new Set();
  const out = declared.map((d) => {
    const e = layers.get(d.key);
    seen.add(d.key);
    return { ...d, present: !!e, hidden: !!e?.userHidden };
  });
  for (const [key, e] of layers.entries()) {
    if (e.scope === scope && e.meta?.legend && !seen.has(key)) {
      out.push({ key, label: e.meta.label, colour: e.meta.colour, dashed: e.meta.dashed, present: true, hidden: !!e.userHidden });
    }
  }
  return out;
}
export function layerKeys() { return [...layers.keys()]; }
export function hasLayer(key) { return layers.has(key); }

const arrowIcon = (bearing, colour) => L.divIcon({
  className: 'traj-arrow', iconSize: [18, 18], iconAnchor: [9, 9],
  html: `<svg width="18" height="18" viewBox="0 0 18 18" style="transform:rotate(${bearing}deg)">
    <path d="M9 1 L15 15 L9 11.5 L3 15 Z" fill="${colour}" stroke="#0b1220" stroke-width="1.6" stroke-linejoin="round"/></svg>`,
});
function bearingDeg(a, b) {
  const p1 = (a.lat * Math.PI) / 180, p2 = (b.lat * Math.PI) / 180, dl = ((b.lon - a.lon) * Math.PI) / 180;
  const y = Math.sin(dl) * Math.cos(p2), x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}
/** Direction arrows: ~7 evenly spaced (by point index) markers pointing along travel. */
function buildArrows(points, colour) {
  const pts = points.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const out = [];
  if (pts.length < 4) return out;
  const n = Math.min(7, Math.floor(pts.length / 3));
  for (let k = 1; k <= n; k += 1) {
    const i = Math.min(pts.length - 2, Math.floor((k * pts.length) / (n + 1)));
    const j = Math.min(pts.length - 1, i + Math.max(1, Math.floor(pts.length / 60)));
    if (pts[i].lat === pts[j].lat && pts[i].lon === pts[j].lon) continue;
    out.push(L.marker([pts[i].lat, pts[i].lon], { icon: arrowIcon(bearingDeg(pts[i], pts[j]), colour), interactive: false, keyboard: false }));
  }
  return out;
}

function nearestPoint(points, latlng) {
  let best = null, bd = Infinity;
  for (const p of points) {
    const d = (p.lat - latlng.lat) ** 2 + (p.lon - latlng.lng) ** 2;
    if (d < bd) { bd = d; best = p; }
  }
  return best;
}
function popupHtml(p, label) {
  const f = (v, d = 1, u = '') => (Number.isFinite(v) ? `${v.toFixed(d)}${u}` : 'N/A');
  return `<b>${label}</b><br>${p.t ? new Date(p.t).toISOString().replace('T', ' ').slice(0, 19) + 'Z' : ''}<br>` +
    `Lat ${f(p.lat, 5, '°')} · Lon ${f(p.lon, 5, '°')}<br>Alt ${f(p.alt, 0, ' m')}${p.phase ? `<br>Phase: ${p.phase}` : ''}` +
    (p.vz != null ? `<br>Vz ${f(p.vz, 2, ' m/s')}` : '');
}

/** Create or update a trajectory layer: dark casing + coloured line (+ direction arrows), one group per key.
 *  points: [{lat, lon, alt, t, phase}]. style: { color, weight, dashArray }. meta: { legend, label, colour, dashed, arrows } */
export function setPolyline(key, layerScope, points, style, meta = {}) {
  getMap();
  const clean = points.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const latlngs = clean.map((p) => [p.lat, p.lon]);
  const weight = style.weight ?? 4.5;
  const colour = style.color;
  let e = layers.get(key);
  const arrows = meta.arrows === false ? [] : buildArrows(clean, colour);
  if (!e) {
    const casing = L.polyline(latlngs, { color: '#0b1220', weight: weight + 3.5, opacity: 0.55, lineCap: 'round', lineJoin: 'round', interactive: false });
    const line = L.polyline(latlngs, { weight, opacity: 1, lineCap: 'round', lineJoin: 'round', ...style });
    // Arrows are added to the group directly: a nested LayerGroup has no getBounds()/getLatLng(), which makes
    // FeatureGroup.getBounds() throw and unmounts the whole React tree (blank page).
    const group = L.featureGroup([casing, line, ...arrows]);
    line.on('click', (ev) => {
      const pts = layers.get(key).points;
      const p = nearestPoint(pts, ev.latlng);
      if (p) L.popup().setLatLng([p.lat, p.lon]).setContent(popupHtml(p, layers.get(key).meta.label || key)).openOn(map);
    });
    e = { layer: group, line, casing, arrows, scope: layerScope, meta, points: clean };
    layers.set(key, e);
    applyVisibility(e);
    notify();
  } else {
    e.casing.setLatLngs(latlngs);
    e.casing.setStyle({ weight: weight + 3.5 });
    e.line.setLatLngs(latlngs);
    e.line.setStyle({ weight, ...style });
    e.arrows.forEach((a) => e.layer.removeLayer(a));
    arrows.forEach((a) => e.layer.addLayer(a));
    e.arrows = arrows;
    e.meta = meta;
    e.points = clean;
    notify();
  }
}

const ICONS = {
  target: L.icon({ iconUrl: '/assets/map/target-red.png', iconSize: [26, 26], iconAnchor: [13, 13] }),
  recovery: L.icon({ iconUrl: '/assets/map/target-blue.png', iconSize: [26, 26], iconAnchor: [13, 13] }),
};
const BADGES = { launch: 'L', burst: 'B', float: 'F', landing: '⬇' };
/** Large, high-contrast badge markers (white ring + dark outline) readable on street and satellite imagery. */
function badgeIcon(kind, colour) {
  const label = BADGES[kind] || '•';
  return L.divIcon({
    className: 'map-badge', iconSize: [28, 28], iconAnchor: [14, 14],
    html: `<svg width="28" height="28" viewBox="0 0 28 28"><circle cx="14" cy="14" r="12" fill="${colour}" stroke="#ffffff" stroke-width="3"/>
      <circle cx="14" cy="14" r="13.5" fill="none" stroke="#0b1220" stroke-width="1.5"/>
      <text x="14" y="18.5" text-anchor="middle" font-size="13" font-weight="800" font-family="Arial,sans-serif" fill="#0b1220">${label}</text></svg>`,
  });
}
function latestIcon(colour) {
  return L.divIcon({
    className: 'map-latest', iconSize: [44, 44], iconAnchor: [22, 22],
    html: `<div class="pulse" style="border-color:${colour}"></div>
      <svg width="44" height="44" viewBox="0 0 44 44"><circle cx="22" cy="22" r="9" fill="${colour}" stroke="#fff" stroke-width="3.5"/>
      <circle cx="22" cy="22" r="10.7" fill="none" stroke="#0b1220" stroke-width="1.5"/><circle cx="22" cy="22" r="3" fill="#0b1220"/></svg>`,
  });
}
function balloonIcon(heading, colour) {
  const rot = Number.isFinite(heading) ? heading : 0;
  return L.divIcon({
    className: 'balloon-icon', iconSize: [34, 34], iconAnchor: [17, 17],
    html: `<svg width="34" height="34" viewBox="0 0 34 34" style="transform:rotate(${rot}deg)">
      <circle cx="17" cy="17" r="7" fill="${colour}" stroke="#04202a" stroke-width="2"/>
      ${Number.isFinite(heading) ? `<path d="M17 1 L22 10 L12 10 Z" fill="${colour}"/>` : ''}</svg>`,
  });
}
function windIcon(towardDeg) {
  return L.divIcon({
    className: '', iconSize: [44, 44], iconAnchor: [22, 22],
    html: `<svg width="44" height="44" viewBox="0 0 44 44" style="transform:rotate(${towardDeg}deg)">
      <path d="M22 40 L22 8 M14 16 L22 6 L30 16" stroke="#f2b33d" stroke-width="2.5" fill="none" stroke-linecap="round"/></svg>`,
  });
}

/** Create or update a marker. kind: launch|landing|burst|target|recovery|balloon|wind */
export function setMarker(key, layerScope, pos, { kind = 'launch', heading, colour = '#2979FF', popup, meta = {} } = {}) {
  getMap();
  if (!pos || !Number.isFinite(pos.lat) || !Number.isFinite(pos.lon)) { removeLayer(key); return; }
  const icon = kind === 'balloon' ? balloonIcon(heading, colour) : kind === 'wind' ? windIcon(heading)
    : kind === 'latest' ? latestIcon(colour) : ICONS[kind] || badgeIcon(kind, colour);
  let e = layers.get(key);
  if (!e) {
    const layer = L.marker([pos.lat, pos.lon], { icon, zIndexOffset: kind === 'latest' ? 1500 : kind === 'balloon' ? 1000 : 400, interactive: kind !== 'wind' });
    e = { layer, scope: layerScope, meta };
    layers.set(key, e);
    applyVisibility(e);
    notify();
  } else {
    e.layer.setLatLng([pos.lat, pos.lon]);
    if (kind === 'balloon' || kind === 'wind' || kind === 'latest' || !ICONS[kind]) e.layer.setIcon(icon);
  }
  if (popup) e.layer.bindPopup(popup);
}

export function removeLayer(key) {
  const e = layers.get(key);
  if (!e) return;
  if (map.hasLayer(e.layer)) map.removeLayer(e.layer);
  layers.delete(key);
  notify();
}
export function removeByPrefix(prefix) { [...layers.keys()].filter((k) => k.startsWith(prefix)).forEach(removeLayer); }

export function fitTo(keys, maxZoom = 11) {
  getMap();
  const b = L.latLngBounds([]);
  for (const k of keys) {
    const e = layers.get(k);
    if (!e) continue;
    if (e.layer.getBounds) { const lb = e.layer.getBounds(); if (lb.isValid()) b.extend(lb); }
    else if (e.layer.getLatLng) b.extend(e.layer.getLatLng());
  }
  if (b.isValid()) map.fitBounds(b.pad(0.15), { maxZoom });
}
export function onMouseMove(fn) { getMap().on('mousemove', fn); return () => map.off('mousemove', fn); }
