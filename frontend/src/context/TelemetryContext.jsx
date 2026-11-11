// Live telemetry store for the selected mission: history via REST, live via WebSocket.
// Samples are buffered in a ref and published at most once per second so charts and
// the map are not re-rendered on every packet.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { missionService, telemetryService } from '../services/apiClient';
import { connectTelemetry } from '../services/websocketService';

const Ctx = createContext(null);
export const useTelemetry = () => useContext(Ctx);

export function TelemetryProvider({ children }) {
  const [missions, setMissions] = useState([]);
  const [missionId, setMissionId] = useState(null);
  const [mission, setMission] = useState(null);
  const [status, setStatus] = useState(null);
  const [transport, setTransport] = useState('NONE');
  const [alerts, setAlerts] = useState([]);
  const [version, setVersion] = useState(0);
  const [predictionTick, setPredictionTick] = useState(0);   // bumps when the backend stores a new prediction version
  const [reloadTick, setReloadTick] = useState(0);           // bumps to force a history reload (e.g. after manual telemetry)
  const buffer = useRef([]);       // live (in-order) packets
  const dirty = useRef(false);

  const refreshMissions = useCallback(async () => {
    try {
      const list = await missionService.list();
      setMissions(list);
      // keep the selection only while that mission still exists (it may have been deleted from mission history)
      setMissionId((cur) => (cur && list.some((m) => m.mission_id === cur) ? cur : list[0]?.mission_id ?? null));
    } catch { /* backend down: top bar shows it */ }
  }, []);
  const refreshMission = useCallback(async () => {
    if (missionId) setMission(await missionService.get(missionId).catch(() => null));
  }, [missionId]);
  useEffect(() => { refreshMissions(); }, [refreshMissions]);

  useEffect(() => {
    buffer.current = []; setAlerts([]); setStatus(null); setMission(null); setVersion((v) => v + 1);
    if (!missionId) return undefined;
    let cancelled = false;
    let conn = null;
    (async () => {
      refreshMission();
      try {
        let offset = 0, items = [];
        for (;;) {   // paginated history load
          const page = await telemetryService.history(missionId, { limit: 5000, offset });
          items = items.concat(page.items);
          offset += page.items.length;
          if (offset >= page.total || !page.items.length || offset >= 50000) break;
        }
        if (cancelled) return;
        buffer.current = items.filter((p) => p.quality !== 'INVALID' && !p.quality_flags.includes('OUT_OF_ORDER'));
        setAlerts(await telemetryService.alerts(missionId));
        dirty.current = true;
      } catch { /* shown via status */ }
      if (cancelled) return;
      conn = connectTelemetry(missionId, {
        onTransport: setTransport,
        onMessage: (m) => {
          if (m.type === 'telemetry') {
            if (m.live && m.quality !== 'INVALID') {
              const last = buffer.current[buffer.current.length - 1];
              if (!last || m.timestamp_utc > last.timestamp_utc) buffer.current.push(m);
            }
            if (m.status) setStatus((s) => ({ ...s, ...m.status, last_received_utc: new Date().toISOString() }));
            dirty.current = true;
          } else if (m.type === 'status') {
            setStatus(m);
          } else if (m.type === 'alert') {
            setAlerts((a) => [m.alert, ...a]);
            if (m.alert.category === 'FLIGHT_PHASE') refreshMission();
          } else if (m.type === 'prediction_version') {
            setPredictionTick((t) => t + 1);
          } else if (m.type === 'alert_ack') {
            setAlerts((a) => a.map((x) => (x.alert_id === m.alert.alert_id ? m.alert : x)));
          }
        },
      });
      const last = buffer.current[buffer.current.length - 1];
      if (last) conn.setLastTs(last.timestamp_utc);
    })();
    const flush = setInterval(() => { if (dirty.current) { dirty.current = false; setVersion((v) => v + 1); } }, 1000);
    return () => { cancelled = true; clearInterval(flush); conn?.close(); };
  }, [missionId, refreshMission, reloadTick]);
  const reloadTelemetry = useCallback(() => setReloadTick((t) => t + 1), []);

  const acknowledge = useCallback(async (alertId) => {
    const row = await telemetryService.acknowledge(missionId, alertId);
    setAlerts((a) => a.map((x) => (x.alert_id === alertId ? row : x)));
  }, [missionId]);

  return (
    <Ctx.Provider value={{ missions, missionId, setMissionId, mission, refreshMission, refreshMissions, status, transport,
      alerts, acknowledge, packets: buffer.current, version, predictionTick, reloadTelemetry }}>
      {children}
    </Ctx.Provider>
  );
}
