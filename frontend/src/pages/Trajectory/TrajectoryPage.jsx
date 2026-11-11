import { useEffect, useMemo, useState } from 'react';
import { useWorkspaceActive } from '../../context/AppContext';
import { ErrorBox, Field, Group, JobStatus, KV, Panel, Pill, Seg, WorkspaceHeader } from '../../components/Common/ui';
import MissionMap from '../../components/Map/MissionMap';
import { COLOURS, FitOnChange, PointMarker, TrajectoryPolyline } from '../../components/Map/MapLayers';
import ChartPanel from '../../components/Charts/ChartPanel';
import { burstService, simService, trajectoryService } from '../../services/apiClient';
import useSimulation from '../../hooks/useSimulation';
import { duration, fmt, fmtInt, fmtLatLon, km, toSec, utc } from '../../utils/format';
import { coordinateError } from '../../utils/coordinates';

const S = 'ws2';
const FWD_DEFAULT = { launch_latitude: '', launch_longitude: '', launch_altitude_m: 0, launch_datetime: '2026-10-31T00:00:00Z',
  hold_duration_hours: 2, payload_mass_kg: 2, parachute_diameter_m: 2, parachute_cd: 1.5, target_altitude_m: 25000,
  ascent_rate_mps: 5, ascent_hold_step_s: 60, descent_output_step_s: 10, ground_altitude_m: 0 };
const REV_DEFAULT = { target_latitude: '', target_longitude: '', target_landing_datetime: '2026-10-31T09:00:00Z',
  target_altitude_m: 25000, hold_duration_hours: 0.8333, launch_altitude_m: 0, ascent_rate_mps: 6.69, payload_mass_kg: 5,
  parachute_diameter_m: 2.4, parachute_cd: 1, ground_altitude_m: 0, backtrack_step_s: 60, ascent_hold_step_s: 60, descent_output_step_s: 10 };
const PHASES = { ascent: 'Ascent', altitude_hold: 'Float / hold', float: 'Float / hold', burst: 'Ascent', descent: 'Descent', landing: 'Descent' };

function EngineSelector({ engines, value, onChange }) {
  const opt = (id, label) => ({ value: id, label, disabled: engines && !engines[id]?.available,
    title: engines && !engines[id]?.available ? (id === 'tawhiri' ? engines.tawhiri.message || 'Tawhiri engine unavailable' : 'Requires valid weather data and Tawhiri engine') : undefined });
  return <Seg options={[opt('sft', 'Custom SFT GNC model'), opt('tawhiri', 'Tawhiri engine'), opt('compare', 'Compare engines')]} value={value} onChange={onChange} />;
}

function PhaseFilter({ value, onChange }) {
  return <Seg options={[{ value: 'all', label: 'All phases' }, { value: 'Ascent', label: 'Ascent' }, { value: 'Float / hold', label: 'Float' }, { value: 'Descent', label: 'Descent' }]} value={value} onChange={onChange} />;
}
const filterPhase = (tr, ph) => (ph === 'all' || !tr ? tr : tr.filter((p) => (PHASES[p.phase] || p.phase) === ph));

function TrajSummary({ title, r, vc = 'ESTIMATE' }) {
  const tr = r?.trajectory || [];
  if (!tr.length) return null;
  const end = tr[tr.length - 1];
  const maxAlt = Math.max(...tr.map((p) => p.alt));
  return (
    <Panel title={title} badge={<span className={`badge vc-${vc}`}>{vc === 'ESTIMATE' ? 'MODEL EST.' : vc}</span>}>
      <KV items={[['Model', r.model_version], ['Forecast cycle', r.forecast_cycle || r.engine_dataset],
        ['Launch', `${fmtLatLon(tr[0].lat, tr[0].lon)} · ${utc(tr[0].t)}`], ['Final model point', `${fmtLatLon(end.lat, end.lon)} · ${utc(end.t)}`],
        ['Final altitude', `${fmt(end.alt, 1)} m`], ['Maximum altitude', `${fmtInt(maxAlt)} m`],
        ['Total duration', duration(toSec(end.t) - toSec(tr[0].t))]]} />
    </Panel>
  );
}

function Profiles({ tracks }) {
  const charts = useMemo(() => tracks.filter((t) => t.points?.length).map((t) => ({ ...t, x: t.points.map((p) => toSec(p.t)), alt: t.points.map((p) => p.alt),
    asc: t.points.filter((p) => p.phase === 'ascent' && p.wind_speed != null) })), [tracks]);
  if (!charts.length) return null;
  return (
    <div className="grid gcharts">
      {charts.map((c) => <ChartPanel key={c.label} title={`Altitude profile — ${c.label}`} unit="m" valueClass="ESTIMATE" x={c.x} syncKey="ws2"
        series={[{ label: c.label, colour: c.colour, values: c.alt }]} />)}
      {charts.filter((c) => c.asc.length > 1).map((c) => <ChartPanel key={`w${c.label}`} title={`Wind profile (ascent) — ${c.label}`} unit="m/s" valueClass="FORECAST"
        xTime={false} xLabel="Altitude (m)" x={c.asc.map((p) => p.alt)} series={[{ label: 'Wind speed', colour: '#3fd07a', values: c.asc.map((p) => p.wind_speed) }]} />)}
    </div>
  );
}

function CompareView({ r }) {
  const m = r.metrics;
  if (r.mode === 'reverse') {
    return (
      <Panel title="Engine comparison — reverse">
        <div className="notice warn small">{r.segment_compared}. Tawhiri's reverse profile does not solve landing-target problems, so only the ascent back-track is comparable.</div>
        <KV items={[['SFT estimated launch', `${fmtLatLon(r.sft.estimated_launch_latitude, r.sft.estimated_launch_longitude)} · ${utc(r.sft.estimated_launch_datetime_utc)}`],
          ['Tawhiri estimated launch', `${fmtLatLon(r.tawhiri.launch_estimate?.latitude, r.tawhiri.launch_estimate?.longitude)} · ${utc(r.tawhiri.launch_estimate?.datetime)}`],
          ['Launch position difference', km(m?.launch_position_difference_m)], ['Launch time difference', `${fmt(m?.launch_time_difference_s, 1)} s`]]} />
      </Panel>
    );
  }
  const sep = m.time_aligned_separation || [];
  return (
    <>
      <Panel title="Engine comparison" badge={<Pill status="INFO">{r.segment_compared}</Pill>} tight>
        <table className="data"><thead><tr><th>Metric</th><th className="num">SFT</th><th className="num">Tawhiri</th><th className="num">Difference</th></tr></thead>
          <tbody>
            <tr><td>Flight time</td><td className="num">{duration(m.flight_time_s.sft)}</td><td className="num">{duration(m.flight_time_s.tawhiri)}</td><td className="num">{fmt(m.flight_time_s.difference, 0)} s</td></tr>
            <tr><td>Maximum altitude</td><td className="num">{fmtInt(m.max_altitude_m.sft)} m</td><td className="num">{fmtInt(m.max_altitude_m.tawhiri)} m</td><td className="num">{fmt(m.max_altitude_m.difference, 1)} m</td></tr>
            <tr><td>Horizontal displacement</td><td className="num">{km(m.horizontal_displacement_m.sft)}</td><td className="num">{km(m.horizontal_displacement_m.tawhiri)}</td><td className="num">{km(m.horizontal_displacement_m.difference)}</td></tr>
            <tr><td>{m.landing_point_difference_m != null ? 'Landing-point difference' : 'End-of-segment position difference'}</td><td /><td /><td className="num">{km(m.end_point_difference_m)}</td></tr>
            <tr><td>Max time-aligned separation</td><td /><td /><td className="num">{km(m.max_time_aligned_separation_m)}</td></tr>
          </tbody></table>
      </Panel>
      <div className="grid gcharts">
        <ChartPanel title="Time-aligned horizontal separation" unit="m" x={sep.map((s) => toSec(s.t))} series={[{ label: 'SFT − Tawhiri', colour: '#f0504a', values: sep.map((s) => s.horizontal_separation_m) }]} />
        <ChartPanel title="Altitude difference (SFT − Tawhiri)" unit="m" x={sep.map((s) => toSec(s.t))} series={[{ label: 'Altitude difference', colour: '#f2b33d', values: sep.map((s) => s.altitude_difference_m) }]} />
        <ChartPanel title="Wind data: SFT sampled wind vs Tawhiri derived drift" unit="m/s" xTime={false} xLabel="Altitude (m)"
          x={m.wind.sft_wind_speed.map((w) => w.alt)} series={[{ label: 'SFT wind speed', colour: '#3dd6f5', values: m.wind.sft_wind_speed.map((w) => w.speed) }]} note={m.wind.note} />
      </div>
    </>
  );
}

export default function TrajectoryPage() {
  const active = useWorkspaceActive();
  const [mode, setMode] = useState('forward');
  const [engine, setEngine] = useState('sft');
  const [sftModel, setSftModel] = useState('hold_mission');
  const [fwd, setFwd] = useState(FWD_DEFAULT);
  const [burst, setBurst] = useState(null);
  const [rev, setRev] = useState(REV_DEFAULT);
  const [descentRate, setDescentRate] = useState(5);
  const [cycle, setCycle] = useState('');
  const [engines, setEngines] = useState(null);
  const [phase, setPhase] = useState('all');
  const sim = useSimulation('trajectory');
  useEffect(() => { burstService.defaults().then((d) => setBurst({ ...d.parameters, latitude: '', longitude: '' })); }, []);
  useEffect(() => { if (active) trajectoryService.engines().then(setEngines).catch(() => {}); }, [active]);

  const [formErr, setFormErr] = useState(null);
  const run = () => {
    const bad = mode === 'reverse' ? coordinateError(rev.target_latitude, rev.target_longitude, 'Target landing')
      : sftModel === 'hold_mission' ? coordinateError(fwd.launch_latitude, fwd.launch_longitude, 'Launch')
      : coordinateError(burst?.latitude, burst?.longitude, 'Launch');
    setFormErr(bad);
    if (bad) return;                       // never run with a missing / default location
    const body = { engine, sft_model: sftModel, forecast_cycle: cycle || null, tawhiri_descent_rate: descentRate };
    if (mode === 'forward') {
      if (sftModel === 'hold_mission') body.forward = fwd; else body.burst = burst;
      sim.submit(() => trajectoryService.forward(body));
    } else {
      body.reverse = rev;
      sim.submit(() => trajectoryService.reverse(body));
    }
  };

  const r = sim.result;
  const isCompare = r && r.sft && r.tawhiri;
  const sftR = isCompare ? r.sft : r?.model !== 'tawhiri' ? r : null;
  const tawR = isCompare ? r.tawhiri : r?.model === 'tawhiri' ? r : null;
  const sftTrack = filterPhase(sftR?.trajectory, phase);
  const tawTrack = filterPhase(tawR?.trajectory, phase);
  const reverseR = sftR?.model === 'sft_reverse' ? sftR : null;
  const sfp = (setter, obj) => (k) => (v) => setter({ ...obj, [k]: v });
  const F = sfp(setFwd, fwd), R = sfp(setRev, rev), B = burst && sfp(setBurst, burst);

  return (
    <>
      <TrajectoryPolyline id={reverseR ? 'ws2:reverse' : 'ws2:sft'} scope={S} points={sftTrack} colour={reverseR ? COLOURS.reverse : COLOURS.sft} dashed label={reverseR ? 'Reverse Trajectory' : 'SFT Prediction'} />
      {reverseR ? <TrajectoryPolyline id="ws2:sft" scope={S} points={null} colour={COLOURS.sft} /> : <TrajectoryPolyline id="ws2:reverse" scope={S} points={null} colour={COLOURS.reverse} />}
      <TrajectoryPolyline id="ws2:tawhiri" scope={S} points={tawTrack} colour={COLOURS.tawhiri} dashed label="Tawhiri Prediction" />
      <PointMarker id="ws2:launch" scope={S} point={sftTrack?.[0] || tawTrack?.[0]} kind="launch" colour={COLOURS.sft} popup="Launch" />
      <PointMarker id="ws2:landing" scope={S} point={sftR?.trajectory?.[sftR.trajectory.length - 1]} kind="landing" colour={reverseR ? COLOURS.reverse : COLOURS.sft} popup="SFT final model point" />
      <PointMarker id="ws2:tlanding" scope={S} point={tawR?.trajectory?.[tawR.trajectory.length - 1]} kind="landing" colour={COLOURS.tawhiri} popup="Tawhiri final point" />
      <PointMarker id="ws2:target" scope={S} point={reverseR ? { lat: reverseR.target.latitude, lon: reverseR.target.longitude } : null} kind="target" popup="Target landing location" />
      <FitOnChange keys={['ws2:sft', 'ws2:tawhiri']} dep={sim.job?.simulation_id && r ? sim.job.simulation_id : null} />
      <WorkspaceHeader title="Trajectory Prediction — Forward · Reverse · Tawhiri" subtitle="SFT GNC models and the Tawhiri engine, with user-supplied launch / target coordinates" />
      <div className="ws-content">
        <div className="split">
          <div className="panel" style={{ alignSelf: 'start' }}>
            <div className="panel-b stack">
              <Seg options={[{ value: 'forward', label: 'Forward trajectory' }, { value: 'reverse', label: 'Reverse trajectory' }]} value={mode} onChange={setMode} />
              <EngineSelector engines={engines} value={engine} onChange={setEngine} />
              {mode === 'forward' && (engine !== 'tawhiri' || true) && (
                <Field label="SFT mission model" value={sftModel} onChange={setSftModel} options={[
                  { value: 'hold_mission', label: 'Ascent → altitude hold → descent (flight_forward)' },
                  { value: 'burst_flight', label: 'Ascent → burst → descent (burst calculator)' }]}
                  hint={engine !== 'sft' ? `Tawhiri profile used: ${sftModel === 'hold_mission' ? 'float_profile (no descent)' : 'standard_profile'}` : undefined} />
              )}
            </div>
            {mode === 'forward' && sftModel === 'hold_mission' && (<>
              <Group title="Launch configuration">
                <Field label="Launch latitude" unit="°" value={fwd.launch_latitude} onChange={F('launch_latitude')} />
                <Field label="Launch longitude" unit="°" value={fwd.launch_longitude} onChange={F('launch_longitude')} />
                <Field label="Launch altitude" unit="m" value={fwd.launch_altitude_m} onChange={F('launch_altitude_m')} />
                <Field label="Launch date/time (UTC)" type="text" value={fwd.launch_datetime} onChange={F('launch_datetime')} />
              </Group>
              <Group title="Balloon & flight configuration">
                <Field label="Payload mass" unit="kg" value={fwd.payload_mass_kg} onChange={F('payload_mass_kg')} />
                <Field label="Ascent rate" unit="m/s" value={fwd.ascent_rate_mps} onChange={F('ascent_rate_mps')} />
                <Field label="Target float altitude" unit="m" value={fwd.target_altitude_m} onChange={F('target_altitude_m')} />
                <Field label="Float duration" unit="h" value={fwd.hold_duration_hours} onChange={F('hold_duration_hours')} />
                <Field label="Ascent/hold time step" unit="s" value={fwd.ascent_hold_step_s} onChange={F('ascent_hold_step_s')} />
                <Field label="Envelope / helium / volume" type="text" value="Not used by this model" onChange={() => {}} unsupported hint="Idealised hold — no balloon thermodynamics" />
              </Group>
              <Group title="Descent configuration">
                <Field label="Parachute diameter" unit="m" value={fwd.parachute_diameter_m} onChange={F('parachute_diameter_m')} />
                <Field label="Parachute Cd" value={fwd.parachute_cd} onChange={F('parachute_cd')} />
                <Field label="Ground altitude" unit="m" value={fwd.ground_altitude_m} onChange={F('ground_altitude_m')} />
                <Field label="Descent output step" unit="s" value={fwd.descent_output_step_s} onChange={F('descent_output_step_s')} />
              </Group>
            </>)}
            {mode === 'forward' && sftModel === 'burst_flight' && burst && (
              <Group title="Burst-flight parameters">
                {['latitude', 'longitude', 'launch_altitude', 'launch_datetime', 'payload_mass', 'envelope_mass', 'helium_mass', 'initial_volume',
                  'burst_diameter', 'ascent_rate', 'burst_altitude', 'maximum_altitude', 'parachute_diameter', 'parachute_cd', 'descent_rate',
                  'ascent_time_step', 'descent_time_step', 'ground_altitude'].map((k) => (
                  <Field key={k} label={k.replace(/_/g, ' ')} type={k === 'launch_datetime' ? 'text' : 'number'} value={burst[k]} onChange={B(k)} />))}
              </Group>
            )}
            {mode === 'reverse' && (<>
              <Group title="Target">
                <Field label="Target latitude" unit="°" value={rev.target_latitude} onChange={R('target_latitude')} />
                <Field label="Target longitude" unit="°" value={rev.target_longitude} onChange={R('target_longitude')} />
                <Field label="Target landing time (UTC)" type="text" value={rev.target_landing_datetime} onChange={R('target_landing_datetime')} full />
                <Field label="Desired float duration" unit="h" value={rev.hold_duration_hours} onChange={R('hold_duration_hours')} />
                <Field label="Launch-time search window" type="text" value="Not supported" onChange={() => {}} unsupported hint="The existing algorithm performs one backward pass" />
              </Group>
              <Group title="Balloon, ascent & descent">
                <Field label="Float altitude" unit="m" value={rev.target_altitude_m} onChange={R('target_altitude_m')} />
                <Field label="Ascent rate" unit="m/s" value={rev.ascent_rate_mps} onChange={R('ascent_rate_mps')} />
                <Field label="Payload mass" unit="kg" value={rev.payload_mass_kg} onChange={R('payload_mass_kg')} />
                <Field label="Parachute diameter" unit="m" value={rev.parachute_diameter_m} onChange={R('parachute_diameter_m')} />
                <Field label="Parachute Cd" value={rev.parachute_cd} onChange={R('parachute_cd')} />
                <Field label="Backtrack step" unit="s" value={rev.backtrack_step_s} onChange={R('backtrack_step_s')} />
              </Group>
            </>)}
            <Group title="Weather & engine options" open={false}>
              <Field label="Forecast cycle" type="text" value={cycle} onChange={setCycle} hint="Blank = newest covering cycle" full />
              {engine !== 'sft' && mode === 'forward' && sftModel === 'burst_flight' && <Field label="Tawhiri sea-level descent rate" unit="m/s" value={descentRate} onChange={setDescentRate} full />}
            </Group>
            <div className="panel-b stack">
              {formErr && <div className="alert-box err" role="alert">{formErr}</div>}
              <button className="btn primary" onClick={run} disabled={sim.busy || (mode === 'reverse' && engine === 'tawhiri')}>
                {sim.busy ? 'Running…' : `Run ${mode} ${engine === 'compare' ? 'comparison' : 'trajectory'}`}</button>
              {mode === 'reverse' && engine === 'tawhiri' && <div className="notice warn small">Tawhiri alone cannot solve a landing-target reverse problem. Choose “Compare engines” to run it on the comparable segment.</div>}
              <JobStatus job={sim.job} onCancel={sim.cancel} />
              <ErrorBox error={sim.error} />
            </div>
          </div>
          <div className="stack">
            <div className="row">
              <PhaseFilter value={phase} onChange={setPhase} />
              <span className="spacer" />
              {r && sim.job && (<>
                <a className="btn sm" href={simService.exportUrl('trajectory', sim.job.simulation_id, 'csv')}>CSV</a>
                <a className="btn sm" href={simService.exportUrl('trajectory', sim.job.simulation_id, 'kml')}>KML</a>
                {isCompare && <a className="btn sm" href={`/api/trajectory/${sim.job.simulation_id}/files/sft/${Object.values(r.sft.files || {})[0] || ''}`}>SFT native file</a>}
              </>)}
            </div>
            <MissionMap scope={S} height="460px" />
            {reverseR && (
              <Panel title="Reverse trajectory result" badge={<span className="badge vc-ESTIMATE">CANDIDATE</span>}>
                <div className="notice warn small">A reverse trajectory is an estimate of where and when to launch. It is not a guaranteed landing prediction: forward validation of the candidate gives the error below, and real winds will differ from the forecast.</div>
                <KV items={[['Calculated launch location', fmtLatLon(reverseR.estimated_launch_latitude, reverseR.estimated_launch_longitude)],
                  ['Calculated launch time', utc(reverseR.estimated_launch_datetime_utc)],
                  ['Target', `${fmtLatLon(reverseR.target.latitude, reverseR.target.longitude)} · ${utc(reverseR.target.datetime_utc)}`],
                  ['Forward-validated landing', `${fmtLatLon(reverseR.predicted_landing_latitude, reverseR.predicted_landing_longitude)} · ${utc(reverseR.predicted_landing_datetime_utc)}`],
                  ['Landing error', km(reverseR.landing_error_m)], ['Landing-time error', `${fmt(reverseR.landing_time_error_s / 60, 1)} min`],
                  ['Convergence', `${reverseR.convergence.method} (${reverseR.convergence.note})`]]} />
                <ul className="small muted">{reverseR.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
              </Panel>
            )}
            {isCompare && <CompareView r={r} />}
            <div className="grid g2">
              {sftR && !reverseR && <TrajSummary title="Custom SFT model" r={sftR} />}
              {tawR && <TrajSummary title="Tawhiri engine" r={tawR} />}
            </div>
            {sftR?.assumptions && !reverseR && <div className="notice small">{sftR.assumptions.join(' ')}</div>}
            <Profiles tracks={[{ label: 'SFT', colour: COLOURS.sft, points: sftTrack }, { label: 'Tawhiri', colour: COLOURS.tawhiri, points: tawTrack }]} />
            {engines?.differences && (
              <Panel title="Engine assumptions" tight>
                <table className="data"><thead><tr><th>Aspect</th><th>Custom SFT model</th><th>Tawhiri engine</th></tr></thead>
                  <tbody>{engines.differences.map((d) => <tr key={d.aspect}><td>{d.aspect}</td><td>{d.sft}</td><td>{d.tawhiri}</td></tr>)}</tbody></table>
              </Panel>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
