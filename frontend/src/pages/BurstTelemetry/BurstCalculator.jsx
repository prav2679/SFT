import { useEffect, useMemo, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { useApp } from '../../context/AppContext';
import { ErrorBox, Field, Group, JobStatus, KV, Panel, Pill } from '../../components/Common/ui';
import ChartPanel from '../../components/Charts/ChartPanel';
import MissionMap from '../../components/Map/MissionMap';
import { FitOnChange } from '../../components/Map/MapLayers';
import { burstService, missionService, simService } from '../../services/apiClient';
import { duration, fmt, fmtInt, fmtLatLon, km, localToUtcIso, toSec, utc, utcIsoToLocal } from '../../utils/format';
import { coordinateError } from '../../utils/coordinates';

export default function BurstCalculator() {
  const { burst, mission, refreshMission } = useWS1();
  const { system } = useApp();
  const [p, setP] = useState(null);
  const [notes, setNotes] = useState({});
  const [launch, setLaunch] = useState({ date: '2026-10-31', time: '00:00', tz: 0 });
  const [cycle, setCycle] = useState('');
  const [msg, setMsg] = useState(null);
  useEffect(() => { burstService.defaults().then((d) => { setP({ ...d.parameters, latitude: '', longitude: '' }); setNotes(d.notes); setLaunch({ ...utcIsoToLocal(d.parameters.launch_datetime, 0), tz: 0 }); }); }, []);
  const set = (k) => (v) => setP({ ...p, [k]: v });
  const launchUtc = localToUtcIso(launch.date, launch.time, Number(launch.tz) || 0);
  const r = burst.result;

  const charts = useMemo(() => {
    if (!r?.trajectory?.length) return null;
    const tr = r.trajectory;
    const x = tr.map((q) => toSec(q.t));
    const asc = tr.filter((q) => q.phase === 'ascent' || q.phase === 'burst');
    return {
      x, alt: tr.map((q) => q.alt), vz: tr.map((q) => q.vz ?? null), ws: tr.map((q) => q.wind_speed ?? null),
      ascAlt: asc.map((q) => q.alt), dia: asc.map((q) => q.diameter_m ?? null), vol: asc.map((q) => q.volume_m3 ?? null),
      temp: asc.map((q) => q.temperature_c ?? null), pres: asc.map((q) => q.pressure_hpa ?? null), wsAsc: asc.map((q) => q.wind_speed ?? null),
      burstDia: asc.map(() => p?.burst_diameter ?? null),
    };
  }, [r, p?.burst_diameter]);

  if (!p) return <div className="muted">Loading calculator defaults…</div>;
  const cycles = system?.weather ? [] : [];
  const coordErr = coordinateError(p.latitude, p.longitude, 'Launch');
  const run = () => {
    setMsg(null);
    if (coordErr) { setMsg(coordErr); return; }          // never run with a missing / default location
    burst.submit(() => burstService.run({ ...p, launch_datetime: launchUtc }, cycle || null, false));
  };
  const burstPt = r?.trajectory?.find((q) => q.phase === 'burst');

  return (
    <div className="split">
      <div className="panel" style={{ alignSelf: 'start' }}>
        <div className="panel-h"><h3>Burst calculator inputs</h3><span className="spacer" /><Pill status="INFO">flight_model_paramaterized</Pill></div>
        <Group title="A. Launch configuration">
          <Field label="Launch latitude" unit="°" value={p.latitude} onChange={set('latitude')} hint={msg && !p.latitude && p.latitude !== 0 ? msg : 'Required — decimal degrees'} />
          <Field label="Launch longitude" unit="°" value={p.longitude} onChange={set('longitude')} hint="Required — decimal degrees" />
          <Field label="Launch altitude" unit="m ASL" value={p.launch_altitude} onChange={set('launch_altitude')} />
          <Field label="Ground altitude (landing)" unit="m ASL" value={p.ground_altitude} onChange={set('ground_altitude')} />
          <Field label="Launch date" type="date" value={launch.date} onChange={(v) => setLaunch({ ...launch, date: v })} />
          <Field label="Launch time" type="time" value={launch.time} onChange={(v) => setLaunch({ ...launch, time: v })} />
          <Field label="Time zone" value={launch.tz} onChange={(v) => setLaunch({ ...launch, tz: v })}
            options={[{ value: 0, label: 'UTC' }, { value: 5.5, label: 'IST (UTC+05:30)' }]} hint={`Model input (UTC): ${launchUtc}`} />
          <Field label="Initial atmosphere" type="text" value="From forecast/ISA at launch" onChange={() => {}} unsupported hint="Derived by the model at launch" />
        </Group>
        <Group title="B. Balloon configuration">
          <Field label="Balloon type" type="text" value="Latex sounding (burst)" onChange={() => {}} unsupported full hint={notes.balloon_type} />
          <Field label="Envelope mass" unit="kg" value={p.envelope_mass} onChange={set('envelope_mass')} />
          <Field label="Payload mass" unit="kg" value={p.payload_mass} onChange={set('payload_mass')} />
          <Field label="Helium mass" unit="kg" value={p.helium_mass} onChange={set('helium_mass')} />
          <Field label="Initial volume" unit="m³" value={p.initial_volume} onChange={set('initial_volume')} />
          <Field label="Initial diameter" unit="m" value={p.initial_volume ? ((6 * p.initial_volume) / Math.PI) ** (1 / 3) : ''} onChange={() => {}} unsupported hint="Sphere of the initial volume (display only)" />
          <Field label="Burst diameter" unit="m" value={p.burst_diameter} onChange={set('burst_diameter')} hint="Monitored; burst is by commanded altitude" />
          <Field label="Balloon drag coefficient" value={p.balloon_cd} onChange={set('balloon_cd')} />
          <Field label="Max differential pressure" unit="Pa" value="" onChange={() => {}} unsupported hint="Not modelled by this calculator" />
        </Group>
        <Group title="C. Ascent configuration">
          <Field label="Ascent rate" unit="m/s" value={p.ascent_rate} onChange={set('ascent_rate')} />
          <Field label="Target burst altitude" unit="m" value={p.burst_altitude} onChange={set('burst_altitude')} />
          <Field label="Maximum altitude (safety ceiling)" unit="m" value={p.maximum_altitude} onChange={set('maximum_altitude')} />
          <Field label="Ascent time step" unit="s" value={p.ascent_time_step} onChange={set('ascent_time_step')} />
          <Field label="Float duration" unit="h" value="" onChange={() => {}} unsupported hint="Use Workspace 2 (hold mission) or 3" />
        </Group>
        <Group title="D. Parachute configuration">
          <Field label="Parachute diameter" unit="m" value={p.parachute_diameter} onChange={set('parachute_diameter')} />
          <Field label="Parachute drag coefficient" value={p.parachute_cd} onChange={set('parachute_cd')} />
          <Field label="Descent rate" unit="m/s" value={p.descent_rate} onChange={set('descent_rate')} hint={notes.descent_rate} full />
          <Field label="Descent time step" unit="s" value={p.descent_time_step} onChange={set('descent_time_step')} />
          <Field label="Parachute mass" unit="kg" value="" onChange={() => {}} unsupported hint={notes.descent_mass} />
        </Group>
        <Group title="E. Weather configuration">
          <Field label="Weather source" type="text" value="Tawhiri CUSF binary (GFS 0.5°)" onChange={() => {}} unsupported full />
          <Field label="Forecast cycle" type="text" value={cycle} onChange={setCycle} hint={`Blank = newest covering cycle (latest valid: ${system?.weather?.latest_valid_cycle || 'none'})`} full />
          <Field label="Pressure levels" type="text" value="47 levels, 1–1000 hPa" onChange={() => {}} unsupported />
          <Field label="Temperature" type="text" value="ISA (adapter)" onChange={() => {}} unsupported hint={notes.atmosphere} />
        </Group>
        <div className="panel-b stack">
          <button className="btn primary" onClick={run} disabled={burst.busy}>{burst.busy ? 'Running model…' : 'Run burst calculation'}</button>
          <JobStatus job={burst.job} onCancel={burst.cancel} />
          <ErrorBox error={burst.error} />
        </div>
      </div>

      <div className="stack">
        {!r ? <div className="notice">Results from the SFT burst model appear here. All outputs are MODEL ESTIMATES; winds are FORECAST data.</div> : (
          <>
            <div className="grid g2">
              <Panel title="Predicted burst & landing" badge={<span className="badge vc-ESTIMATE">MODEL EST.</span>}>
                <KV items={[['Outcome', r.success ? 'Burst reached' : 'Ascent terminated (no burst)'],
                  ['Burst altitude', `${fmtInt(r.burst?.altitude_m)} m`], ['Burst time', burstPt ? utc(burstPt.t) : 'N/A'],
                  ['Time to burst', duration(r.ascent_time_s)], ['Burst diameter (model)', `${fmt(r.burst?.diameter_m, 2)} m`],
                  ['Burst location', fmtLatLon(r.burst?.latitude, r.burst?.longitude)],
                  ['Final model point', fmtLatLon(r.landing?.latitude, r.landing?.longitude)], ['Final altitude', `${fmt(r.landing?.altitude_m, 1)} m`],
                  ['Total flight duration', duration(r.total_flight_time_s)], ['Descent duration', duration(r.descent_time_s)],
                  ['Launch → final point', km(r.launch_to_landing_distance_m)]]} />
              </Panel>
              <Panel title="Model provenance & warnings">
                <KV items={[['Model', r.model_version], ['Forecast cycle', r.forecast_cycle], ['Atmosphere', r.atmosphere_source]]} />
                <div className="stack" style={{ gap: 6, marginTop: 8 }}>
                  {r.warnings.map((w) => <div key={w.code} className={`notice ${w.severity === 'CRITICAL' ? 'crit' : w.severity === 'WARNING' ? 'warn' : ''}`}>{w.message}</div>)}
                  <div className="notice">Not modelled by the burst calculator: internal/differential pressure and gas/envelope temperature (see Workspace 3).</div>
                </div>
                <div className="row" style={{ marginTop: 8 }}>
                  <a className="btn sm" href={simService.exportUrl('burst', burst.job.simulation_id, 'csv')}>CSV export</a>
                  <a className="btn sm" href={simService.exportUrl('burst', burst.job.simulation_id, 'kml')}>KML export</a>
                  {mission && <button className="btn sm" onClick={() => missionService.attachPrediction(mission.mission_id, burst.job.simulation_id)
                    .then((x) => { setMsg(`Attached as ${x.prediction_set}`); refreshMission(); }).catch((e) => setMsg(e.message))}>Use as mission prediction</button>}
                  <span className="small muted">{msg}</span>
                </div>
              </Panel>
            </div>
            <MissionMap scope="ws1" height="380px" />
            <FitOnChange keys={['ws1:calc']} dep={burst.job?.simulation_id} />
            <div className="grid gcharts">
              <ChartPanel title="Altitude vs time" unit="m" valueClass="ESTIMATE" x={charts.x} series={[{ label: 'Altitude', colour: '#3dd6f5', values: charts.alt }]} />
              <ChartPanel title="Vertical velocity vs time" unit="m/s" valueClass="ESTIMATE" x={charts.x} series={[{ label: 'Vertical velocity', colour: '#3fd07a', values: charts.vz }]} />
              <ChartPanel title="Balloon diameter vs altitude" unit="m" valueClass="ESTIMATE" xTime={false} xLabel="Altitude (m)" x={charts.ascAlt}
                series={[{ label: 'Diameter', colour: '#3dd6f5', values: charts.dia }, { label: 'Configured burst diameter', colour: '#f0504a', values: charts.burstDia, dashed: true }]} />
              <ChartPanel title="Balloon volume vs altitude" unit="m³" valueClass="ESTIMATE" xTime={false} xLabel="Altitude (m)" x={charts.ascAlt} series={[{ label: 'Volume', colour: '#b48cff', values: charts.vol }]} />
              <ChartPanel title="Temperature vs altitude" unit="°C" valueClass="ESTIMATE" xTime={false} xLabel="Altitude (m)" x={charts.ascAlt}
                series={[{ label: 'Ambient (ISA)', colour: '#f2b33d', values: charts.temp }]} note="ISA estimate supplied by the wind adapter." />
              <ChartPanel title="External pressure vs altitude" unit="hPa" valueClass="ESTIMATE" xTime={false} xLabel="Altitude (m)" x={charts.ascAlt}
                series={[{ label: 'Pressure (ISA)', colour: '#ff9a52', values: charts.pres }]} note="Internal and differential pressure are not modelled by the burst calculator." />
              <ChartPanel title="Wind speed vs altitude (ascent)" unit="m/s" valueClass="FORECAST" xTime={false} xLabel="Altitude (m)" x={charts.ascAlt} series={[{ label: 'Wind speed', colour: '#3fd07a', values: charts.wsAsc }]} />
              <ChartPanel title="Wind speed vs time" unit="m/s" valueClass="FORECAST" x={charts.x} series={[{ label: 'Wind speed', colour: '#3fd07a', values: charts.ws }]} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
