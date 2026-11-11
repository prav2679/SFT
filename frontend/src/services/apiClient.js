// REST client. All scientific results come from the backend; the frontend never computes physics.
export class ApiError extends Error {
  constructor(status, detail) {
    const d = typeof detail === 'object' && detail ? detail : { message: String(detail ?? '') };
    super(d.message || (Array.isArray(detail) ? detail.map((e) => `${e.loc?.slice(-1)[0]}: ${e.msg}`).join('; ') : `HTTP ${status}`));
    this.status = status;
    this.detail = d;
    this.errorType = d.error_type;
  }
}

export async function api(path, { method = 'GET', body, signal } = {}) {
  const res = await fetch(path, {
    method,
    signal,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data;
}

export const systemService = {
  status: () => api('/api/system/status'),
  simulations: (kind) => api(`/api/simulations${kind ? `?kind=${kind}` : ''}`),
  cancel: (id) => api(`/api/simulations/${id}/cancel`, { method: 'POST' }),
};
export const simService = {
  status: (id) => api(`/api/burst/${id}`),          // generic: any simulation id
  results: (base, id) => api(`/api/${base}/${id}/results`),
  exportUrl: (base, id, fmt) => `/api/${base}/${id}/export/${fmt}`,
};
export const burstService = {
  defaults: () => api('/api/burst/defaults'),
  run: (parameters, forecast_cycle, force) => api('/api/burst/run', { method: 'POST', body: { parameters, forecast_cycle, force } }),
};
export const trajectoryService = {
  engines: () => api('/api/trajectory/engines'),
  forward: (body) => api('/api/trajectory/forward', { method: 'POST', body }),
  reverse: (body) => api('/api/trajectory/reverse', { method: 'POST', body }),
};
export const diurnalService = {
  defaults: () => api('/api/diurnal/defaults'),
  run: (body) => api('/api/diurnal/run', { method: 'POST', body }),
};
export const tawhiriService = {
  status: () => api('/api/tawhiri/status'),
  download: (cycle, force = false) => api('/api/tawhiri/download', { method: 'POST', body: { cycle, force } }),
  cancel: () => api('/api/tawhiri/download/cancel', { method: 'POST' }),
};
export const missionService = {
  list: () => api('/api/missions'),
  catalogue: () => api('/api/missions/catalogue'),
  get: (id) => api(`/api/missions/${id}`),
  create: (body) => api('/api/missions', { method: 'POST', body }),
  update: (id, body) => api(`/api/missions/${id}`, { method: 'PATCH', body }),
  abort: (id) => api(`/api/missions/${id}/abort`, { method: 'POST' }),
  remove: (id) => api(`/api/missions/${id}`, { method: 'DELETE' }),
  clear: (scope, confirm = false) => api(`/api/missions?scope=${scope}${confirm ? '&confirm=true' : ''}`, { method: 'DELETE' }),
  attachPrediction: (id, simulation_id) => api(`/api/missions/${id}/predictions`, { method: 'POST', body: { simulation_id } }),
  simStart: (id, body) => api(`/api/missions/${id}/simulation/start`, { method: 'POST', body }),
  simAction: (id, action) => api(`/api/missions/${id}/simulation/${action}`, { method: 'POST' }),
  simStatus: (id) => api(`/api/missions/${id}/simulation`),
};
export const telemetryService = {
  status: (id) => api(`/api/telemetry/status/${id}`),
  history: (id, { start, end, limit = 5000, offset = 0 } = {}) => {
    const q = new URLSearchParams({ limit, offset });
    if (start) q.set('start', start);
    if (end) q.set('end', end);
    return api(`/api/telemetry/history/${id}?${q}`);
  },
  historyCsvUrl: (id) => `/api/telemetry/history/${id}/export.csv`,
  alerts: (id) => api(`/api/telemetry/alerts/${id}`),
  acknowledge: (id, alertId) => api(`/api/telemetry/alerts/${id}/${alertId}/acknowledge`, { method: 'POST' }),
  comparison: (id, predictionSet) => api(`/api/telemetry/comparison/${id}${predictionSet ? `?prediction_set=${predictionSet}` : ''}`),
  /** Operator-entered observed state; by default also queues a background re-forecast (new prediction version). */
  manual: (id, body) => api(`/api/telemetry/manual/${id}`, { method: 'POST', body }),
  phasePreview: (id, vz, alt) => api(`/api/telemetry/phase-preview/${id}?vertical_velocity=${vz}&altitude=${alt}`),
  flightView: (id, version) => api(`/api/telemetry/flight-view/${id}${version ? `?version=${version}` : ''}`),
  versions: (id) => api(`/api/telemetry/versions/${id}`),
  /** Phase-aware re-forecast from stored telemetry (ASCENT / FLOAT / DESCENT). Result is stored server-side as a new version. */
  reforecast: (id, body = {}) => api(`/api/telemetry/reforecast/${id}`, { method: 'POST', body }),
  attachReforecast: (id, simId) => api(`/api/telemetry/reforecast/${id}/${simId}/attach`, { method: 'POST' }),
};
