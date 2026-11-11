// WebSocket telemetry client: automatic reconnection with exponential backoff and a
// REST polling fallback after repeated failures. Receive-only; it never sends commands.
import { telemetryService } from './apiClient';

export function connectTelemetry(missionId, { onMessage, onTransport }) {
  let ws = null;
  let closed = false;
  let attempt = 0;
  let pollTimer = null;
  let retryTimer = null;
  let heartbeat = null;
  let lastTs = null;

  const setTransport = (t) => onTransport?.(t);

  function startPolling() {
    if (pollTimer) return;
    setTransport('POLLING');
    const tick = async () => {
      try {
        const st = await telemetryService.status(missionId);
        onMessage({ type: 'status', ...st });
        const h = await telemetryService.history(missionId, { start: lastTs || undefined, limit: 500 });
        for (const it of h.items) {
          if (lastTs && it.timestamp_utc <= lastTs) continue;
          lastTs = it.timestamp_utc;
          onMessage({ type: 'telemetry', ...it, live: true, status: { connection: st.connection, flight_phase: st.flight_phase } });
        }
      } catch { /* backend unreachable: keep trying */ }
    };
    tick();
    pollTimer = setInterval(tick, 5000);
  }
  function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

  function open() {
    if (closed) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/telemetry/${encodeURIComponent(missionId)}`);
    setTransport('CONNECTING');
    ws.onopen = () => {
      attempt = 0;
      stopPolling();
      setTransport('WEBSOCKET');
      heartbeat = setInterval(() => ws?.readyState === 1 && ws.send('ping'), 20000);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'telemetry' && msg.live) lastTs = msg.timestamp_utc;
        if (msg.type !== 'pong') onMessage(msg);
      } catch { /* ignore malformed frame */ }
    };
    ws.onclose = () => {
      clearInterval(heartbeat);
      if (closed) return;
      attempt += 1;
      if (attempt >= 3) startPolling();
      const delay = Math.min(30000, 1000 * 2 ** Math.min(attempt, 5)) * (0.8 + Math.random() * 0.4);
      setTransport(attempt >= 3 ? 'POLLING' : 'RECONNECTING');
      retryTimer = setTimeout(open, delay);
    };
    ws.onerror = () => ws?.close();
  }
  open();
  return {
    setLastTs: (t) => { lastTs = t; },
    close() { closed = true; clearTimeout(retryTimer); clearInterval(heartbeat); stopPolling(); ws?.close(); },
  };
}
