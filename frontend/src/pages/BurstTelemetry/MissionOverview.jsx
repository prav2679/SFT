import { useEffect, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { ErrorBox, Field, KV, Panel, Pill, Seg } from '../../components/Common/ui';
import MissionMap from '../../components/Map/MissionMap';
import { missionService, systemService } from '../../services/apiClient';
import { fmt, fmtInt, fmtLatLon, utc, km } from '../../utils/format';
import PhaseBand from './PhaseBand';
import { coordinateError } from '../../utils/coordinates';

function CreateMission({ onCreated }) {
  const [f, setF] = useState({ mission_name: '', balloon_id: 'SFT-SPB-01', mode: 'SIMULATION', launch_latitude: '',
    launch_longitude: '', launch_altitude: 87, burst_expected: true });
  const [err, setErr] = useState(null);
  const set = (k) => (v) => setF({ ...f, [k]: v });
  const create = async () => {
    setErr(null);
    const bad = coordinateError(f.launch_latitude, f.launch_longitude, 'Mission launch');
    if (bad) { setErr({ detail: { error_type: 'INVALID_INPUT', message: bad } }); return; }
    try {
      const m = await missionService.create({ mission_name: f.mission_name || 'Untitled mission', balloon_id: f.balloon_id, mode: f.mode,
        launch_latitude: f.launch_latitude, launch_longitude: f.launch_longitude, launch_altitude: f.launch_altitude,
        config: { burst_expected: f.burst_expected === true || f.burst_expected === 'true' } });
      onCreated(m.mission_id);
    } catch (e) { setErr(e); }
  };
  return (
    <Panel title="New mission">
      <div className="fields">
        <Field label="Mission name" type="text" value={f.mission_name} onChange={set('mission_name')} full />
        <Field label="Balloon ID" type="text" value={f.balloon_id} onChange={set('balloon_id')} />
        <Field label="Telemetry source" value={f.mode} onChange={set('mode')} options={[{ value: 'SIMULATION', label: 'Simulation' }, { value: 'LIVE', label: 'Live hardware' }]} />
        <Field label="Launch latitude" unit="°" value={f.launch_latitude} onChange={set('launch_latitude')} />
        <Field label="Launch longitude" unit="°" value={f.launch_longitude} onChange={set('launch_longitude')} />
        <Field label="Launch altitude" unit="m" value={f.launch_altitude} onChange={set('launch_altitude')} />
        <Field label="Balloon behaviour" value={String(f.burst_expected)} onChange={set('burst_expected')}
          options={[{ value: 'true', label: 'Burst expected (latex)' }, { value: 'false', label: 'Super-pressure float' }]} />
      </div>
      <div className="row" style={{ marginTop: 10 }}><button className="btn primary" onClick={create}>Create mission</button></div>
      <p className="small muted">A mission receives either simulated or measured telemetry, never both.</p>
      <ErrorBox error={err} />
    </Panel>
  );
}

const SCENARIO_LABELS = { gps_loss: 'GPS signal loss', communication_interruption: 'Communication interruption',
  battery_degradation: 'Battery degradation', temperature_anomaly: 'Temperature anomaly', pressure_anomaly: 'Pressure anomaly',
  altitude_deviation: 'Unexpected altitude deviation', sensor_failure: 'Sensor failure' };

function SimulationControls({ mission }) {
  const [sources, setSources] = useState([]);
  const [opts, setOpts] = useState({ source: 'recorded', speed: 20, interval_s: 10, gps_noise_m: 0 });
  const [scen, setScen] = useState({});
  const [st, setSt] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    systemService.simulations().then((l) => setSources(l.filter((s) => s.status === 'COMPLETED' && ['burst', 'forward', 'diurnal'].includes(s.kind))));
    const load = () => missionService.simStatus(mission.mission_id).then(setSt).catch(() => {});
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [mission.mission_id]);
  const start = () => {
    setErr(null);
    const scenarios = Object.entries(scen).filter(([, v]) => v.on).map(([type, v]) => ({ type, start: v.start / 100, end: v.end / 100 }));
    missionService.simStart(mission.mission_id, { ...opts, scenarios }).then(setSt).catch(setErr);
  };
  const running = st?.state === 'RUNNING' || st?.state === 'PAUSED';
  return (
    <Panel title="Simulation mode" badge={<Pill status={st?.state?.startsWith('COMPLETED') ? 'COMPLETED' : st?.state || 'NONE'}>{st?.state?.split(' (')[0] || 'NOT STARTED'}</Pill>}>
      <div className="fields">
        <Field label="Flight states from" value={opts.source} onChange={(v) => setOpts({ ...opts, source: v })} full
          options={[{ value: 'recorded', label: 'Recorded SFT burst-calculator output (2026-10-31)' },
            ...sources.map((s) => ({ value: `${s.kind}:${s.simulation_id}`, label: `${s.kind} job ${s.simulation_id}` }))]} />
        <Field label="Speed-up" unit="×" value={opts.speed} onChange={(v) => setOpts({ ...opts, speed: v })} />
        <Field label="Packet interval" unit="s sim" value={opts.interval_s} onChange={(v) => setOpts({ ...opts, interval_s: v })} />
        <Field label="GPS noise (1σ)" unit="m" value={opts.gps_noise_m} onChange={(v) => setOpts({ ...opts, gps_noise_m: v })} />
      </div>
      <div className="small muted" style={{ margin: '8px 0 4px' }}>Test scenarios (window as % of flight time; affect simulated data only)</div>
      <table className="data"><tbody>
        {Object.entries(SCENARIO_LABELS).map(([k, l]) => {
          const v = scen[k] || { on: false, start: 40, end: 50 };
          const up = (patch) => setScen({ ...scen, [k]: { ...v, ...patch } });
          return (
            <tr key={k}><td><label className="row" style={{ flexWrap: 'nowrap' }}><input type="checkbox" checked={v.on} onChange={(e) => up({ on: e.target.checked })} />{l}</label></td>
              <td style={{ width: 70 }}><input aria-label={`${l} start %`} type="number" value={v.start} onChange={(e) => up({ start: +e.target.value })} style={{ width: 60 }} /></td>
              <td style={{ width: 70 }}><input aria-label={`${l} end %`} type="number" value={v.end} onChange={(e) => up({ end: +e.target.value })} style={{ width: 60 }} /></td></tr>
          );
        })}
      </tbody></table>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" onClick={start} disabled={running}>Start simulation</button>
        {st?.state === 'RUNNING' && <button className="btn" onClick={() => missionService.simAction(mission.mission_id, 'pause').then(setSt)}>Pause</button>}
        {st?.state === 'PAUSED' && <button className="btn" onClick={() => missionService.simAction(mission.mission_id, 'resume').then(setSt)}>Resume</button>}
        {running && <button className="btn danger" onClick={() => missionService.simAction(mission.mission_id, 'stop').then(setSt)}>Stop</button>}
      </div>
      {st && st.state !== 'NONE' && (
        <div style={{ marginTop: 8 }}>
          <div className="progress"><div style={{ width: `${(st.progress || 0) * 100}%` }} /></div>
          <div className="small muted">{st.packets_sent} packets · simulation clock {utc(st.sim_time_utc)}</div>
        </div>
      )}
      <ErrorBox error={err} />
    </Panel>
  );
}

export default function MissionOverview() {
  const { missions, missionId, setMissionId, mission, refreshMissions, refreshMission, status, transport, latest, comparison, actual } = useWS1();
  const [creating, setCreating] = useState(false);
  const p = latest?.payload || {};
  const predEnd = comparison?.prediction_track?.[comparison.prediction_track.length - 1];
  const predBurst = comparison?.prediction_track?.reduce((m, q) => (q.alt > (m?.alt ?? -1) ? q : m), null);
  return (
    <div className="split">
      <div className="stack">
        <Panel title="Mission" actions={<button className="btn sm" onClick={() => setCreating((c) => !c)}>{creating ? 'Close' : 'New mission'}</button>}>
          <Field label="Selected mission" value={missionId || ''} onChange={setMissionId}
            options={missions.length ? missions.map((m) => ({ value: m.mission_id, label: `${m.mission_id} — ${m.mission_name} (${m.mode})` })) : [{ value: '', label: 'No missions yet' }]} />
        </Panel>
        {creating && <CreateMission onCreated={(id) => { refreshMissions(); setMissionId(id); setCreating(false); }} />}
        {mission?.mode === 'SIMULATION' && <SimulationControls mission={mission} />}
        {mission?.mode === 'LIVE' && (
          <Panel title="Live telemetry gateway">
            <p className="small">Ground-station receivers send packets to <code>POST /api/telemetry/ingest</code> with
              <code> data_source: "MEASURED"</code>. The dashboard never talks to the balloon directly.</p>
          </Panel>
        )}
        {mission && (
          <Panel title="Ground-segment status">
            <div className="row">
              <button className="btn danger" disabled={mission.flight_phase === 'ABORTED'}
                onClick={() => window.confirm('Mark this mission ABORTED in the ground segment? No command is sent to the balloon.') &&
                  missionService.abort(mission.mission_id).then(refreshMission)}>Mark mission aborted</button>
            </div>
            <p className="small muted">This dashboard is monitoring-only. It cannot command the balloon, release ballast, vent gas or terminate flight.</p>
          </Panel>
        )}
      </div>
      <div className="stack">
        {!mission ? (
          <div className="notice">Create a mission to start. Use a simulation mission to exercise the dashboard with SFT model output.</div>
        ) : (
          <>
            <PhaseBand phase={status?.flight_phase || mission.flight_phase} since={status?.phase_since || mission.phase_since} latestTs={latest?.timestamp_utc} />
            <div className="grid g2">
              <Panel title="Mission summary">
                <KV items={[['Mission ID', mission.mission_id], ['Balloon ID', mission.balloon_id], ['Mission name', mission.mission_name],
                  ['Data source', mission.mode === 'SIMULATION' ? 'SIMULATED' : 'MEASURED (hardware)'],
                  ['Launch location', fmtLatLon(mission.launch_latitude, mission.launch_longitude)],
                  ['Launch time (ascent detected)', utc(mission.launch_time || actual.find((q) => q.vz > 1)?.t)], ['Mission status', mission.mission_status],
                  ['Weather forecast cycle', comparison?.forecast_cycle || '—']]} />
              </Panel>
              <Panel title="Flight state" badge={<Pill status={status?.connection || 'DISCONNECTED'} />}>
                <KV items={[['Current flight phase', status?.flight_phase || mission.flight_phase],
                  ['Telemetry connection', `${status?.connection || 'DISCONNECTED'} via ${transport}`],
                  ['Current altitude', `${fmtInt(p.gps_altitude)} m`], ['Maximum altitude', `${fmtInt(status?.max_altitude)} m`],
                  ['Predicted burst altitude', predBurst ? `${fmtInt(predBurst.alt)} m` : '—'],
                  ['Predicted landing', predEnd ? fmtLatLon(predEnd.lat, predEnd.lon) : '—'],
                  ['Current location', fmtLatLon(p.latitude, p.longitude)],
                  ['Distance from launch', km(p.distance_from_launch_m)],
                  ['Last telemetry (packet time)', utc(latest?.timestamp_utc)], ['Last received (wall clock)', utc(status?.last_received_utc)],
                  ['Packets', fmt(status?.packet_count, 0)]]} />
              </Panel>
            </div>
            <MissionMap scope="ws1" height="420px" />
          </>
        )}
      </div>
    </div>
  );
}
