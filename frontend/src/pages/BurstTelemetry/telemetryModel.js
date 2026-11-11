// Helpers to classify and extract telemetry values. No physics here — only selection,
// labelling and unit display of values computed/measured elsewhere.
import { toSec } from '../../utils/format';

export function valueClass(packet, field) {
  if (!packet) return 'UNAVAILABLE';
  const v = packet.payload?.[field];
  if (v == null) return 'UNAVAILABLE';
  if (packet.derived_fields?.includes(field) || field.startsWith('est_')) return 'ESTIMATE';
  return packet.data_source === 'SIMULATED' ? 'SIMULATED' : 'MEASURED';
}

export const RANGES = [
  { id: '5m', label: '5 min', s: 300 }, { id: '15m', label: '15 min', s: 900 }, { id: '1h', label: '1 h', s: 3600 },
  { id: '6h', label: '6 h', s: 21600 }, { id: '24h', label: '24 h', s: 86400 }, { id: 'all', label: 'Entire mission', s: Infinity },
];

/** Columnar series for the given fields, filtered to a window ending at the latest sample. */
export function seriesFor(packets, fields, rangeS = Infinity) {
  if (!packets.length) return { x: [], cols: Object.fromEntries(fields.map((f) => [f, []])) };
  const end = toSec(packets[packets.length - 1].timestamp_utc);
  const start = end - rangeS;
  const x = [], cols = Object.fromEntries(fields.map((f) => [f, []]));
  for (const p of packets) {
    const t = toSec(p.timestamp_utc);
    if (t < start) continue;
    x.push(t);
    for (const f of fields) cols[f].push(p.payload?.[f] ?? null);
  }
  return { x, cols };
}

export function track(packets) {
  return packets.filter((p) => p.payload?.latitude != null).map((p) => ({
    lat: p.payload.latitude, lon: p.payload.longitude, alt: p.payload.gps_altitude, t: p.timestamp_utc, vz: p.payload.vertical_velocity,
  }));
}

export function previousValue(packets, field) {
  for (let i = packets.length - 2; i >= 0; i--) if (packets[i].payload?.[field] != null) return packets[i].payload[field];
  return null;
}
export function lastUpdated(packets, field) {
  for (let i = packets.length - 1; i >= 0; i--) if (packets[i].payload?.[field] != null) return packets[i].timestamp_utc;
  return null;
}
