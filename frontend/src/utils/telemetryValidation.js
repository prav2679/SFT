// Client-side mirror of the backend telemetry validation (the backend remains the authority).
const num = (v) => (v === '' || v == null ? NaN : Number(v));

export const ALTITUDE_MIN_M = -500;
export const ALTITUDE_MAX_M = 60000;

/** Returns { field: message } for every invalid input. Empty object = valid. */
export function validateTelemetry(f, { launchTime } = {}) {
  const e = {};
  const ts = f.timestamp ? new Date(`${f.timestamp}${f.timestamp.endsWith('Z') ? '' : 'Z'}`) : null;
  if (!ts || Number.isNaN(ts.getTime())) e.timestamp = 'Enter a valid UTC date and time';
  else if (launchTime && ts < new Date(launchTime)) e.timestamp = 'Earlier than the mission launch time';
  const need = (k, label, lo, hi) => {
    const v = num(f[k]);
    if (Number.isNaN(v)) e[k] = `${label} is required`;
    else if (v < lo || v > hi) e[k] = `${label} must be between ${lo} and ${hi}`;
  };
  need('latitude', 'Latitude', -90, 90);
  need('longitude', 'Longitude', -180, 180);
  need('altitude_m', 'Altitude', ALTITUDE_MIN_M, ALTITUDE_MAX_M);
  need('vertical_velocity', 'Vertical velocity', -150, 150);
  const opt = (k, label, lo, hi) => {
    if (f[k] === '' || f[k] == null) return;
    const v = num(f[k]);
    if (Number.isNaN(v) || v < lo || v > hi) e[k] = `${label} must be between ${lo} and ${hi}`;
  };
  opt('horizontal_velocity', 'Horizontal velocity', 0, 400);
  opt('wind_speed', 'Wind speed', 0, 200);
  opt('wind_direction', 'Wind direction', 0, 360);
  if (f.correction_of && !String(f.correction_reason || '').trim()) e.correction_reason = 'A correction needs a written reason';
  return e;
}

/** Contradictory phase / vertical-velocity combinations (same rules as the backend). */
export function phaseConflict(phase, vz) {
  const v = num(vz);
  if (Number.isNaN(v)) return null;
  if (phase === 'ASCENT' && v < -1) return `ASCENT contradicts a vertical velocity of ${v} m/s`;
  if (phase === 'DESCENT' && v > 1) return `DESCENT contradicts a vertical velocity of ${v} m/s`;
  if (phase === 'FLOAT' && Math.abs(v) > 2) return `FLOAT contradicts a vertical velocity of ${v} m/s`;
  return null;
}

/** Request body for POST /api/telemetry/manual/{mission}. Wind direction is the direction the wind blows FROM. */
export function buildManualBody(f) {
  const n = (v) => (v === '' || v == null ? null : Number(v));
  return {
    timestamp_utc: `${f.timestamp}${f.timestamp.endsWith('Z') ? '' : 'Z'}`,
    latitude: Number(f.latitude), longitude: Number(f.longitude), altitude_m: Number(f.altitude_m),
    vertical_velocity: Number(f.vertical_velocity), horizontal_velocity: n(f.horizontal_velocity),
    wind_speed: n(f.wind_speed), wind_direction: n(f.wind_direction), flight_phase: f.flight_phase || 'AUTO',
    correction_of: f.correction_of ? Number(f.correction_of) : null,
    correction_reason: f.correction_of ? f.correction_reason : null,
    reforecast: !!f.reforecast, float_end_datetime: f.float_end ? `${f.float_end}${f.float_end.endsWith('Z') ? '' : 'Z'}` : null,
    use_measured_ascent_rate: !!f.use_measured_ascent_rate,
  };
}
