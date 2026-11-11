export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
export const fmt = (v, d = 1) => (isNum(v) ? v.toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d }) : 'N/A');
export const fmtInt = (v) => (isNum(v) ? Math.round(v).toLocaleString('en-GB') : 'N/A');
export const fmtLatLon = (lat, lon) => (isNum(lat) && isNum(lon) ? `${lat.toFixed(5)}°, ${lon.toFixed(5)}°` : 'N/A');
export const utc = (iso) => (iso ? new Date(iso).toISOString().replace('T', ' ').slice(0, 19) + 'Z' : 'N/A');
export const utcShort = (iso) => (iso ? new Date(iso).toISOString().slice(11, 19) + 'Z' : '—');
export const toSec = (iso) => new Date(iso).getTime() / 1000;
export function duration(s) {
  if (!isNum(s)) return 'N/A';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min ${String(sec).padStart(2, '0')} s`;
}
export const km = (m) => (isNum(m) ? (Math.abs(m) >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(0)} m`) : 'N/A');
export function downloadCsv(name, header, rows) {
  const esc = (v) => (v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v);
  const blob = new Blob([[header.join(','), ...rows.map((r) => r.map(esc).join(','))].join('\n')], { type: 'text/csv' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
/** Convert a local date+time in a fixed UTC offset (hours) to an ISO UTC string. */
export function localToUtcIso(date, time, offsetHours) {
  if (!date || !time) return null;
  const [y, mo, d] = date.split('-').map(Number);
  const [h, mi] = time.split(':').map(Number);
  return new Date(Date.UTC(y, mo - 1, d, h, mi) - offsetHours * 3600e3).toISOString().replace('.000Z', 'Z');
}
export function utcIsoToLocal(iso, offsetHours) {
  const t = new Date(new Date(iso).getTime() + offsetHours * 3600e3).toISOString();
  return { date: t.slice(0, 10), time: t.slice(11, 16) };
}
