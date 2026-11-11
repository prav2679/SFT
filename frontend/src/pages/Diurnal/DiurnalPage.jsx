import { useEffect, useMemo, useState } from 'react';
import { ErrorBox, Field, Group, JobStatus, KV, Panel, Pill, Seg, WorkspaceHeader } from '../../components/Common/ui';
import MissionMap from '../../components/Map/MissionMap';
import { COLOURS, FitOnChange, PointMarker, TrajectoryPolyline } from '../../components/Map/MapLayers';
import ChartPanel from '../../components/Charts/ChartPanel';
import { diurnalService, simService } from '../../services/apiClient';
import useSimulation from '../../hooks/useSimulation';
import { fmt, fmtInt, toSec, utc } from '../../utils/format';
import { coordinateError } from '../../utils/coordinates';

const S = 'ws3';
const K = (v) => (v == null ? null : v - 273.15);   // display conversion only

function Config({ b, m, setB, setM, onRun, sim, formErr }) {
  const fb = (k) => (v) => setB({ ...b, [k]: v });
  const fm = (k) => (v) => setM({ ...m, [k]: v });
  return (
    <div className="panel" style={{ alignSelf: 'start' }}>
      <div className="panel-h"><h3>Diurnal analysis configuration</h3><span className="spacer" /><Pill status="INFO">SPB Stage 5</Pill></div>
      <Group title="Launch">
        <Field label="Launch latitude" unit="°" value={b.initial_latitude_deg} onChange={fb('initial_latitude_deg')} />
        <Field label="Launch longitude" unit="°" value={b.initial_longitude_deg} onChange={fb('initial_longitude_deg')} />
        <Field label="Launch elevation" unit="m" value={b.launch_elevation_m} onChange={fb('launch_elevation_m')} />
        <Field label="Launch time (UTC)" type="text" value={m.launch_time_utc} onChange={fm('launch_time_utc')} />
      </Group>
      <Group title="Balloon">
        <Field label="Payload mass" unit="kg" value={b.payload_mass_kg} onChange={fb('payload_mass_kg')} />
        <Field label="Envelope mass" unit="kg" value={b.envelope_mass_kg} onChange={fb('envelope_mass_kg')} />
        <Field label="Helium mass" unit="kg" value={b.helium_mass_kg} onChange={fb('helium_mass_kg')} />
        <Field label="Initial volume" unit="m³" value={b.initial_volume_m3} onChange={fb('initial_volume_m3')} />
        <Field label="Maximum (taut) volume" unit="m³" value={b.max_volume_m3} onChange={fb('max_volume_m3')} />
        <Field label="Nominal ΔP limit" unit="Pa" value={b.max_differential_pressure_pa} onChange={fb('max_differential_pressure_pa')} />
        <Field label="Envelope model" value={b.envelope_mode} onChange={fb('envelope_mode')} options={[{ value: 'compliant', label: 'Compliant (provisional P-V law)' }, { value: 'rigid', label: 'Rigid (idealised)' }]} full />
      </Group>
      <Group title="Flight & simulation">
        <Field label="Initial float altitude" unit="m" value={m.target_float_altitude_m} onChange={fm('target_float_altitude_m')} />
        <Field label="Ascent rate (prescribed)" unit="m/s" value={m.prescribed_ascent_rate_ms} onChange={fm('prescribed_ascent_rate_ms')} />
        <Field label="Float / simulation duration" unit="h" value={m.float_duration_h} onChange={fm('float_duration_h')} />
        <div className="field"><label>Presets</label><Seg options={[{ value: 24, label: '24 h' }, { value: 72, label: '72 h' }]} value={m.float_duration_h} onChange={fm('float_duration_h')} /></div>
        <Field label="Outer time step" unit="s" value={m.outer_timestep_s} onChange={fm('outer_timestep_s')} hint="Atmosphere sampling interval" />
        <Field label="Inner time step" unit="s" value={m.inner_timestep_s} onChange={fm('inner_timestep_s')} hint="Thermal/vertical integration" />
        <Field label="Weather source" type="text" value="Tawhiri TMP + winds (no ISA fallback)" onChange={() => {}} unsupported full />
      </Group>
      <Group title="Thermal & optical (assumed values)" open={false}>
        {['solar_absorptivity', 'infrared_emissivity', 'internal_heat_transfer_w_m2k', 'external_h_ground_w_m2k', 'external_h_float_w_m2k',
          'envelope_heat_capacity_j_k', 'initial_helium_temp_k', 'initial_envelope_temp_k', 'drag_coefficient', 'envelope_compliance_pa_inv'].map((k) => (
          <Field key={k} label={k.replace(/_/g, ' ')} value={b[k]} onChange={fb(k)} />))}
        <Field label="Solar transmittance" value={m.solar_transmittance} onChange={fm('solar_transmittance')} />
        <Field label="Outgoing longwave" unit="W/m²" value={m.outgoing_longwave_w_m2} onChange={fm('outgoing_longwave_w_m2')} />
      </Group>
      <div className="panel-b stack">
        {formErr && <div className="alert-box err" role="alert">{formErr}</div>}
        <button className="btn primary" onClick={onRun} disabled={sim.busy}>{sim.busy ? 'Running model…' : 'Run diurnal analysis'}</button>
        <JobStatus job={sim.job} onCancel={sim.cancel} />
        <ErrorBox error={sim.error} />
        <p className="small muted">Most thermal and envelope parameters are assumed and must be calibrated before results are treated as validated.</p>
      </div>
    </div>
  );
}

export default function DiurnalPage() {
  const [b, setB] = useState(null);
  const [m, setM] = useState(null);
  const [formErr, setFormErr] = useState(null);
  const sim = useSimulation('diurnal');
  useEffect(() => { diurnalService.defaults().then((d) => { setB({ ...d.balloon, initial_latitude_deg: '', initial_longitude_deg: '' }); setM(d.mission); }); }, []);
  const r = sim.result;

  const d = useMemo(() => {
    if (!r?.rows?.length) return null;
    const rows = r.rows;
    const x = rows.map((q) => toSec(q.time_utc));
    const bands = [];
    let start = null;
    rows.forEach((q, i) => {
      if (!q.is_day && start == null) start = x[i];
      if ((q.is_day || i === rows.length - 1) && start != null) { bands.push([start, x[i]]); start = null; }
    });
    const markers = r.analysis.events.map((e) => ({ x: toSec(e.time_utc), label: e.type === 'SUNRISE' ? 'Sunrise' : 'Sunset', colour: e.type === 'SUNRISE' ? '#f2b33d' : '#8da0b8' }));
    const col = (f, conv) => rows.map((q) => (conv ? conv(q[f]) : q[f]));
    const wsp = rows.map((q) => Math.hypot(q.u_wind_ms, q.v_wind_ms));
    const wdir = rows.map((q) => (Math.atan2(-q.u_wind_ms, -q.v_wind_ms) * 180 / Math.PI + 360) % 360);
    const dayCount = rows.filter((q) => q.is_day).length;
    return { x, bands, markers, rows, alt: col('altitude_m'), he: col('helium_temperature_k', K), env: col('envelope_temperature_k', K),
      air: col('air_temperature_k', K), vol: col('envelope_volume_m3'), dp: col('differential_pressure_pa'), lift: col('buoyancy_margin_n'),
      vz: col('vertical_speed_ms'), sun: col('solar_elevation_deg'), wsp, wdir, rho: col('air_density_kgm3'), pres: col('air_pressure_pa', (v) => v / 100),
      dpLimit: rows.map(() => r.balloon.max_differential_pressure_pa), dayCount };
  }, [r]);

  if (!b || !m) return <div className="ws-content muted">Loading diurnal model defaults…</div>;
  const run = () => {
    const bad = coordinateError(b.initial_latitude_deg, b.initial_longitude_deg, 'Initial');
    setFormErr(bad);
    if (bad) return;                       // never run with a missing / default location
    sim.submit(() => diurnalService.run({ balloon: b, mission: m }));
  };
  const a = r?.analysis;
  const last = d?.rows[d.rows.length - 1];
  const track = d?.rows.map((q) => ({ lat: q.latitude_deg, lon: q.longitude_deg, alt: q.altitude_m, t: q.time_utc, phase: q.phase, vz: q.vertical_speed_ms }));
  const common = { x: d?.x, syncKey: 'diurnal', bands: d?.bands, markers: d?.markers, valueClass: 'ESTIMATE', height: 170 };

  return (
    <>
      <TrajectoryPolyline id="ws3:path" scope={S} points={track} colour={COLOURS.diurnal} dashed label="Diurnal Trajectory" />
      <PointMarker id="ws3:launch" scope={S} point={track?.[0]} kind="launch" colour={COLOURS.diurnal} popup="Launch" />
      <PointMarker id="ws3:end" scope={S} point={track?.[track.length - 1]} kind="float" colour={COLOURS.diurnal} popup="End of simulation (still floating)" />
      <FitOnChange keys={['ws3:path']} dep={r ? sim.job?.simulation_id : null} />
      <WorkspaceHeader title="Diurnal Analysis" subtitle="Super-pressure balloon thermal / diurnal analysis from the user-supplied initial position" />
      <div className="ws-content">
        <div className="split">
          <Config b={b} m={m} setB={setB} setM={setM} onRun={run} sim={sim} formErr={formErr} />
          <div className="stack">
            {!r ? (
              <div className="notice">Run the Stage 5 model to analyse day/night behaviour. The model computes altitude from balloon physics — it never forces descent at sunset or ascent at sunrise.</div>
            ) : (<>
              <div className="grid g3">
                <Panel title="Environment">
                  <KV items={[['Forecast cycle', r.forecast_cycle], ['Atmosphere', 'Tawhiri forecast'],
                    ['Records (day / night)', `${d.dayCount} / ${d.rows.length - d.dayCount}`],
                    ['Solar elevation range', `${fmt(Math.min(...d.sun), 1)}° to ${fmt(Math.max(...d.sun), 1)}°`],
                    ['Air density at end', `${fmt(last.air_density_kgm3, 4)} kg/m³`], ['Ambient at end', `${fmt(K(last.air_temperature_k), 1)} °C`]]} />
                </Panel>
                <Panel title="Sunrise & sunset (at balloon)">
                  {a.events.length ? <table className="data"><tbody>{a.events.map((e) => <tr key={e.time_utc}><td>{e.type === 'SUNRISE' ? 'Sunrise' : 'Sunset'}</td><td>{utc(e.time_utc)}</td><td className="num">{fmtInt(e.altitude_m)} m</td></tr>)}</tbody></table>
                    : <span className="muted small">No sunrise or sunset within the simulated window.</span>}
                  <p className="small muted">Day = any part of the solar disc above the balloon's apparent horizon.</p>
                </Panel>
                <Panel title="Float summary" badge={<span className="badge vc-ESTIMATE">MODEL EST.</span>}>
                  <KV items={[['Float altitude range', `${fmtInt(a.summary?.float_altitude_min_m)}–${fmtInt(a.summary?.float_altitude_max_m)} m`],
                    ['ΔP range', `${fmtInt(a.summary?.dp_min_pa)} to ${fmtInt(a.summary?.dp_max_pa)} Pa`], ['Nominal ΔP limit', `${fmtInt(a.summary?.dp_limit_pa)} Pa`],
                    ['Envelope model', r.balloon.envelope_mode]]} />
                  <a className="btn sm" href={simService.exportUrl('diurnal', sim.job.simulation_id, 'csv')}>CSV</a>{' '}
                  <a className="btn sm" href={simService.exportUrl('diurnal', sim.job.simulation_id, 'kml')}>KML</a>
                </Panel>
              </div>
              <Panel title="Operational assessment">
                <div className="stack" style={{ gap: 6 }}>
                  {a.interpretations.map((i) => (
                    <div key={i.text} className={`notice ${i.level === 'CRITICAL' ? 'crit' : i.level === 'WARNING' ? 'warn' : ''}`}>
                      {i.text}<div className="small muted">Basis: {i.basis}</div>
                    </div>
                  ))}
                  <div className="notice warn"><b>Ballast & venting advisories unavailable.</b> {a.advisories.reason} These are engineering interpretations, not control commands; this page cannot execute any control action.</div>
                </div>
              </Panel>
              {a.segments.length > 0 && (
                <Panel title="Day / night float segments" tight>
                  <div className="scroll"><table className="data"><thead><tr><th>Period</th><th>Start (UTC)</th><th>End (UTC)</th><th className="num">Alt min–max m</th>
                    <th className="num">He max °C</th><th className="num">Superheat K</th><th className="num">ΔP max Pa</th><th className="num">Thermal lag min</th></tr></thead>
                    <tbody>{a.segments.map((s) => (
                      <tr key={s.start_utc}><td>{s.period === 'DAY' ? 'Day' : 'Night'}</td><td>{utc(s.start_utc)}</td><td>{utc(s.end_utc)}</td>
                        <td className="num">{fmtInt(s.altitude_min_m)}–{fmtInt(s.altitude_max_m)}</td><td className="num">{fmt(K(s.helium_temp_max_k), 1)}</td>
                        <td className="num">{fmt(s.superheat_mean_k, 1)}</td><td className="num">{fmtInt(s.dp_max_pa)}</td>
                        <td className="num">{s.thermal_lag_helium_min != null ? fmt(s.thermal_lag_helium_min, 0) : '—'}</td></tr>))}</tbody></table></div>
                </Panel>
              )}
              <MissionMap scope={S} height="360px" />
              <div className="small muted">Shaded = night. Charts share a cursor; drag to zoom, double-click to reset.</div>
              <div className="grid gcharts">
                <ChartPanel title="Altitude vs time" unit="m" {...common} series={[{ label: 'Altitude', colour: '#3dd6f5', values: d.alt }]} />
                <ChartPanel title="Internal gas temperature vs time" unit="°C" {...common} series={[{ label: 'Helium', colour: '#ff9a52', values: d.he }]} />
                <ChartPanel title="Envelope temperature vs time" unit="°C" {...common} series={[{ label: 'Envelope', colour: '#f0504a', values: d.env }]} />
                <ChartPanel title="Ambient temperature vs time" unit="°C" {...common} valueClass="FORECAST" series={[{ label: 'Ambient', colour: '#f2b33d', values: d.air }]} />
                <ChartPanel title="Balloon volume vs time" unit="m³" {...common} series={[{ label: 'Volume', colour: '#b48cff', values: d.vol }]} />
                <ChartPanel title="Differential pressure vs time" unit="Pa" {...common} series={[{ label: 'ΔP', colour: '#f0504a', values: d.dp }, { label: 'Nominal limit', colour: '#8da0b8', values: d.dpLimit, dashed: true }]} />
                <ChartPanel title="Net lift vs time" unit="N" {...common} series={[{ label: 'Buoyancy − weight', colour: '#3fd07a', values: d.lift }]} />
                <ChartPanel title="Vertical velocity vs time" unit="m/s" {...common} series={[{ label: 'Vertical velocity', colour: '#3dd6f5', values: d.vz }]} />
                <ChartPanel title="Solar elevation vs time" unit="°" {...common} series={[{ label: 'Solar elevation', colour: '#f2b33d', values: d.sun }]} />
                <ChartPanel title="Wind speed vs time" unit="m/s" {...common} valueClass="FORECAST" series={[{ label: 'Wind speed', colour: '#3fd07a', values: d.wsp }]} />
                <ChartPanel title="Wind direction (from) vs time" unit="°" {...common} valueClass="FORECAST" series={[{ label: 'Direction from', colour: '#b48cff', values: d.wdir }]} />
                <ChartPanel title="Atmospheric pressure & density" unit="hPa" {...common} valueClass="FORECAST" series={[{ label: 'Pressure', colour: '#ff9a52', values: d.pres }]} />
              </div>
              <Panel title="Model limitations"><ul className="small">{r.limitations.map((l) => <li key={l}>{l}</li>)}</ul></Panel>
            </>)}
          </div>
        </div>
      </div>
    </>
  );
}
