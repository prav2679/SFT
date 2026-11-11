import { useEffect, useState } from 'react';
import { useApp } from '../context/AppContext';
import { useTelemetry } from '../context/TelemetryContext';
import { missionService, tawhiriService } from '../services/apiClient';
import { ErrorBox, Field, KV, Panel, Pill } from '../components/Common/ui';
import { utc } from '../utils/format';

function TawhiriPanel() {
  const [st, setSt] = useState(null);
  const [cycle, setCycle] = useState('');
  const [err, setErr] = useState(null);
  const load = () => tawhiriService.status().then((s) => { setSt(s); setCycle((c) => c || s.downloader.expected_latest_cycle); }).catch(setErr);
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, []);
  if (!st) return <ErrorBox error={err} />;
  const dl = st.downloader, wx = st.weather_data, eng = st.engine;
  return (
    <>
      <Panel title="Tawhiri downloader" badge={<Pill status={dl.status} />}>
        <KV items={[['Executable', dl.executable_present ? 'present' : 'NOT FOUND'], ['Source', dl.base_url],
          ['Cycle', dl.cycle || '—'], ['Message', dl.message || '—']]} />
        <div className="row" style={{ marginTop: 8 }}>
          <Field label="Forecast cycle" type="text" value={cycle} onChange={setCycle} hint="YYYYMMDDHH (00/06/12/18Z)" />
          <button className="btn primary" disabled={dl.status === 'RUNNING'}
            onClick={() => tawhiriService.download(cycle).then(load).catch(setErr)}>Download cycle</button>
          {dl.status === 'RUNNING' && <button className="btn danger" onClick={() => tawhiriService.cancel().then(load)}>Cancel</button>}
        </div>
        <p className="small muted">Runs the preserved OCaml downloader. A cycle that is already valid locally is not downloaded again.</p>
        {dl.log_tail?.length > 0 && <pre className="small scroll" style={{ maxHeight: 140, background: 'var(--bg)', padding: 6 }}>{dl.log_tail.slice(-12).join('\n')}</pre>}
        <ErrorBox error={err} />
      </Panel>
      <Panel title="Weather data" badge={<Pill status={wx.overall} />}>
        <div className="small muted">{wx.data_dir}</div>
        <table className="data"><thead><tr><th>Cycle</th><th>Status</th><th>Valid until (excl.)</th></tr></thead>
          <tbody>{wx.datasets.length ? wx.datasets.map((d) => (
            <tr key={d.cycle}><td>{d.cycle}</td><td><Pill status={d.status === 'VALID' ? 'VALID' : 'INVALID'}>{d.status}</Pill></td><td>{utc(d.valid_to_utc_exclusive)}</td></tr>
          )) : <tr><td colSpan={3} className="muted">No datasets found. Download a forecast cycle above.</td></tr>}</tbody></table>
      </Panel>
      <Panel title="Tawhiri engine" badge={<Pill status={eng.status} />}>
        <KV items={[['API', eng.api_url], ['Engine dataset', eng.engine_dataset || '—'], eng.message && ['Detail', eng.message]]} />
      </Panel>
    </>
  );
}

function ThresholdPanel() {
  const { mission, refreshMission } = useTelemetry();
  const [th, setTh] = useState(null);
  const [msg, setMsg] = useState(null);
  useEffect(() => { setTh(mission?.config?.thresholds ? { ...mission.config.thresholds } : null); }, [mission]);
  if (!mission || !th) return <Panel title="Alert thresholds"><span className="muted">Select a mission in Workspace 1.</span></Panel>;
  const labels = {
    differential_pressure_max_pa: ['Max differential pressure', 'Pa'], differential_pressure_warn_fraction: ['Pressure warning fraction', '0–1'],
    battery_warning_v: ['Battery warning', 'V'], battery_critical_v: ['Battery critical', 'V'],
    payload_temperature_max_c: ['Payload temp max', '°C'], payload_temperature_min_c: ['Payload temp min', '°C'],
    internal_gas_temperature_max_c: ['Gas temp max', '°C'], wind_speed_max_ms: ['Wind speed max', 'm/s'],
    rapid_altitude_loss_ms: ['Rapid altitude loss', 'm/s'], altitude_deviation_warning_m: ['Altitude deviation', 'm'],
    gps_hdop_max: ['GPS HDOP max', '-'], max_horizontal_speed_ms: ['Plausible horizontal speed', 'm/s'], max_vertical_speed_ms: ['Plausible vertical speed', 'm/s'],
  };
  return (
    <Panel title={`Alert thresholds — ${mission.mission_id}`}>
      <div className="fields">
        {Object.entries(labels).map(([k, [l, u]]) => <Field key={k} label={l} unit={u} value={th[k]} onChange={(v) => setTh({ ...th, [k]: v })} />)}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn primary" onClick={() => missionService.update(mission.mission_id, { config: { thresholds: th } })
          .then(() => { refreshMission(); setMsg('Thresholds saved'); }).catch((e) => setMsg(e.message))}>Save thresholds</button>
        <span className="small muted">{msg}</span>
      </div>
      <p className="small muted">Battery thresholds are placeholders — set them for the actual battery pack.</p>
    </Panel>
  );
}

export default function SettingsDrawer() {
  const { settingsOpen, setSettingsOpen, system } = useApp();
  if (!settingsOpen) return null;
  return (
    <div className="drawer-back" onClick={() => setSettingsOpen(false)}>
      <aside className="drawer stack" onClick={(e) => e.stopPropagation()} aria-label="Settings">
        <div className="row"><h2 style={{ margin: 0, fontFamily: 'var(--font-cond)' }}>Settings</h2><span className="spacer" />
          <button className="btn" onClick={() => setSettingsOpen(false)}>Close</button></div>
        <TawhiriPanel />
        <ThresholdPanel />
        <Panel title="System">
          <KV items={[['Version', system?.version], ['Model interpreter', system?.model_python],
            ['Control capability', system?.control_capability]]} />
          <p className="small"><a href="/legacy-predictor/" target="_blank" rel="noreferrer">Open the preserved CUSF Leaflet predictor</a></p>
        </Panel>
      </aside>
    </div>
  );
}
