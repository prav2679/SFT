// Manual telemetry update: validated, stored immutably, and (optionally) triggers a background re-forecast.
import { useEffect, useRef, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { ErrorBox, Field, JobStatus, Panel, Pill } from '../../components/Common/ui';
import { simService, telemetryService } from '../../services/apiClient';
import { fmt, utc } from '../../utils/format';
import { buildManualBody, phaseConflict, validateTelemetry } from '../../utils/telemetryValidation';

const EMPTY = { timestamp: '', latitude: '', longitude: '', altitude_m: '', vertical_velocity: '', horizontal_velocity: '',
  wind_speed: '', wind_direction: '', flight_phase: 'AUTO', reforecast: true, use_measured_ascent_rate: true,
  float_end: '', correction_of: '', correction_reason: '' };
const PHASE_OPTS = [{ value: 'AUTO', label: 'Automatic detection' }, { value: 'ASCENT', label: 'Override: Ascent' },
  { value: 'FLOAT', label: 'Override: Float' }, { value: 'DESCENT', label: 'Override: Descent' }, { value: 'LANDED', label: 'Override: Landed' }];

export default function TelemetryUpdate() {
  const { missionId, mission, packets, refreshMission, reloadTelemetry, refreshFlightView, setSection } = useWS1();
  const [f, setF] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [detect, setDetect] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [job, setJob] = useState(null);
  const [done, setDone] = useState(null);
  const poll = useRef(null);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => () => clearInterval(poll.current), []);
  useEffect(() => { setF(EMPTY); setResult(null); setJob(null); setDone(null); setError(null); }, [missionId]);

  // live phase preview (what "automatic" would choose for these values)
  useEffect(() => {
    if (!missionId || f.vertical_velocity === '' || f.altitude_m === '') { setDetect(null); return undefined; }
    const t = setTimeout(() => telemetryService.phasePreview(missionId, f.vertical_velocity, f.altitude_m).then(setDetect).catch(() => setDetect(null)), 300);
    return () => clearTimeout(t);
  }, [missionId, f.vertical_velocity, f.altitude_m]);

  const needsFloatEnd = (f.flight_phase === 'FLOAT') || (f.flight_phase === 'AUTO' && detect?.phase === 'FLOAT');
  const conflict = f.flight_phase !== 'AUTO' ? phaseConflict(f.flight_phase, f.vertical_velocity) : null;

  const watch = (jobId) => {
    clearInterval(poll.current);
    poll.current = setInterval(async () => {
      try {
        const st = await simService.status(jobId);
        setJob(st);
        if (['COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(st.status)) {
          clearInterval(poll.current);
          setDone(st);
          refreshFlightView();
          refreshMission();
        }
      } catch { /* transient */ }
    }, 1500);
  };

  const submit = async (ev) => {
    ev.preventDefault();
    const errs = validateTelemetry(f, { launchTime: mission?.launch_time });
    if (conflict) errs.flight_phase = conflict;
    setErrors(errs); setError(null); setResult(null); setDone(null); setJob(null);
    if (Object.keys(errs).length) return;           // nothing is sent until every input is valid
    setBusy(true);
    try {
      const body = buildManualBody(f);
      const r = await telemetryService.manual(missionId, body);
      setResult(r);
      reloadTelemetry();
      refreshMission();
      refreshFlightView();
      if (r.reforecast?.submitted && r.reforecast.job) { setJob(r.reforecast.job); watch(r.reforecast.job.simulation_id); }
      if (!f.correction_of) setF((x) => ({ ...EMPTY, flight_phase: 'AUTO', reforecast: x.reforecast, use_measured_ascent_rate: x.use_measured_ascent_rate }));
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const startCorrection = (p) => setF({ ...EMPTY, timestamp: p.timestamp_utc.slice(0, 19), latitude: p.payload?.latitude ?? p.latitude ?? '',
    longitude: p.payload?.longitude ?? p.longitude ?? '', altitude_m: p.payload?.gps_altitude ?? '', vertical_velocity: p.payload?.vertical_velocity ?? '',
    reforecast: true, use_measured_ascent_rate: true, correction_of: p.telemetry_id, correction_reason: '' });
  const recent = [...packets].reverse().slice(0, 8);
  const rf = result?.reforecast;

  if (!missionId) return <div className="muted">Create or select a mission first.</div>;
  return (
    <div className="split">
      <Panel title="Telemetry update" badge={mission?.mode === 'SIMULATION' ? <Pill status="INFO">SIMULATED data</Pill> : <Pill status="CONNECTED">MEASURED data</Pill>}>
        <form onSubmit={submit} noValidate aria-label="Telemetry update form">
          {f.correction_of && <div className="alert-box">Correcting telemetry record #{f.correction_of}. The original observation is kept (marked superseded); a reason is required.</div>}
          <div className="form-grid">
            <Field label="Timestamp (UTC)" type="datetime-local" step="1" value={f.timestamp} onChange={set('timestamp')} hint={errors.timestamp} />
            <Field label="Latitude" unit="°" value={f.latitude} onChange={set('latitude')} hint={errors.latitude || 'Decimal degrees, −90 to 90'} />
            <Field label="Longitude" unit="°" value={f.longitude} onChange={set('longitude')} hint={errors.longitude || 'Decimal degrees, −180 to 180'} />
            <Field label="Altitude" unit="m" value={f.altitude_m} onChange={set('altitude_m')} hint={errors.altitude_m} />
            <Field label="Vertical velocity" unit="m/s" value={f.vertical_velocity} onChange={set('vertical_velocity')} hint={errors.vertical_velocity || '+ climbing, − descending'} />
            <Field label="Horizontal velocity (optional)" unit="m/s" value={f.horizontal_velocity} onChange={set('horizontal_velocity')} hint={errors.horizontal_velocity} />
            <Field label="Wind speed (optional)" unit="m/s" value={f.wind_speed} onChange={set('wind_speed')} hint={errors.wind_speed} />
            <Field label="Wind direction from (optional)" unit="°" value={f.wind_direction} onChange={set('wind_direction')} hint={errors.wind_direction || 'Direction the wind blows FROM'} />
            <Field label="Flight phase" value={f.flight_phase} onChange={set('flight_phase')} options={PHASE_OPTS}
              hint={errors.flight_phase || conflict || (f.flight_phase === 'AUTO' ? (detect ? (detect.phase ? `Detected: ${detect.phase} (${detect.reason})` : detect.reason) : 'Detected from vertical velocity and altitude') : 'Manual override')} />
            {needsFloatEnd && <Field label="Planned end of float (UTC)" type="datetime-local" step="1" value={f.float_end} onChange={set('float_end')}
              hint={errors.float_end || 'Optional if the original prediction contains a float segment'} />}
            {f.correction_of && <Field label="Correction reason" type="text" value={f.correction_reason} onChange={set('correction_reason')} hint={errors.correction_reason} full />}
          </div>
          <div className="stack" style={{ margin: '10px 0' }}>
            <label><input type="checkbox" checked={f.reforecast} onChange={(e) => set('reforecast')(e.target.checked)} /> Re-forecast the remaining trajectory from this state (creates a new prediction version)</label>
            <label><input type="checkbox" checked={f.use_measured_ascent_rate} onChange={(e) => set('use_measured_ascent_rate')(e.target.checked)} /> Use the measured vertical velocity as the ascent rate (ascent phase)</label>
          </div>
          <button className="btn primary" type="submit" disabled={busy}>{busy ? 'Submitting…' : f.correction_of ? 'Submit correction' : 'Submit telemetry'}</button>
          {f.correction_of && <button type="button" className="btn" style={{ marginLeft: 8 }} onClick={() => setF(EMPTY)}>Cancel correction</button>}
        </form>
        <ErrorBox error={error} />
        {result && (
          <div className="alert-box ok" role="status">
            Telemetry #{result.telemetry_id} stored — quality <b>{result.quality}</b>{result.live ? '' : ' (not live)'}; phase <b>{result.phase.used}</b> ({result.phase.source.toLowerCase()}).
            {result.warnings.map((w) => <div key={w}>⚠ {w}</div>)}
            {rf && !rf.submitted && rf.error && <div className="alert-box err">Re-forecast not started: {rf.error.message}</div>}
            {rf && !rf.submitted && rf.reason && <div>{rf.reason}{rf.version ? ` (existing prediction V${rf.version})` : ''}</div>}
          </div>
        )}
        {job && <JobStatus job={job} />}
        {done?.status === 'COMPLETED' && done.post_process?.status === 'OK' && (
          <div className="alert-box ok" role="status">Revised prediction <b>V{done.post_process.version}</b> stored. The original prediction is unchanged.
            <button className="btn small" style={{ marginLeft: 8 }} onClick={() => setSection('comparison')}>Compare predictions</button></div>)}
        {done?.status === 'COMPLETED' && done.post_process?.status === 'FAILED' && <div className="alert-box err">Re-forecast finished but could not be stored: {done.post_process.error}</div>}
        {done && done.status !== 'COMPLETED' && <div className="alert-box err">Re-forecast {done.status.toLowerCase()}: {done.error?.message || done.error || 'see job log'}</div>}
      </Panel>
      <Panel title="Recent telemetry">
        {!recent.length ? <div className="muted">No telemetry yet.</div> : (
          <table className="hist"><thead><tr><th>Time (UTC)</th><th>Alt (m)</th><th>Source</th><th /></tr></thead>
            <tbody>{recent.map((p) => (
              <tr key={p.packet_id}><td>{utc(p.timestamp_utc)}</td><td>{fmt(p.payload?.gps_altitude, 0)}</td><td>{p.entry_method || 'API'}</td>
                <td><button className="btn small" disabled={!p.telemetry_id} onClick={() => startCorrection(p)}>Correct…</button></td></tr>))}</tbody></table>)}
        <p className="inline-note">Records are never edited. A correction stores a new record, links it to the old one and keeps the old one for audit.</p>
      </Panel>
    </div>
  );
}
