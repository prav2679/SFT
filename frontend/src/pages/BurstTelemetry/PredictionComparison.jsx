import { useEffect, useMemo, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { ErrorBox, Field, JobStatus, KV, Panel } from '../../components/Common/ui';
import ChartPanel from '../../components/Charts/ChartPanel';
import MissionMap from '../../components/Map/MissionMap';
import { COLOURS, TrajectoryPolyline } from '../../components/Map/MapLayers';
import { systemService, telemetryService } from '../../services/apiClient';
import useJobWatch from '../../hooks/useJobWatch';
import { duration, fmt, fmtLatLon, km, toSec, utc } from '../../utils/format';

const bearingName = (b) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(b / 45) % 8];

/** Prediction versions + re-forecast from the latest telemetry (phase-aware, stored as a new version). */
function VersionPanel() {
  const { mission, missionId, flightView, selectedVersion, setSelectedVersion, refreshFlightView, refreshMission } = useWS1();
  const [jobs, setJobs] = useState([]);
  const [base, setBase] = useState('');
  const [floatEnd, setFloatEnd] = useState('');
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const { job, watch } = useJobWatch((st) => {
    refreshFlightView(); refreshMission();
    setMsg(st.status === 'COMPLETED' && st.post_process?.status === 'OK' ? `Revised prediction V${st.post_process.version} stored.`
      : `Re-forecast ${st.status.toLowerCase()}${st.error?.message ? `: ${st.error.message}` : ''}`);
  });
  useEffect(() => {
    systemService.simulations('burst').then((l) => setJobs(l.filter((s) => s.status === 'COMPLETED'))).catch(() => {});
  }, []);
  const versions = flightView?.versions || [];
  const run = async () => {
    setError(null); setMsg(null);
    try {
      const r = await telemetryService.reforecast(missionId, { phase: 'AUTO', simulation_id: base || null,
        float_end_datetime: floatEnd ? `${floatEnd}${floatEnd.endsWith('Z') ? '' : 'Z'}` : null });
      if (r.submitted && r.job) watch(r.job); else setMsg(r.reason || 'Nothing to do.');
      refreshFlightView();
    } catch (e) { setError(e); }
  };
  return (
    <Panel title="Prediction versions">
      <div role="group" aria-label="Prediction versions">
        {versions.map((v) => {
          const isSel = v.kind === 'ORIGINAL' ? false : (selectedVersion ? String(selectedVersion) === String(v.version) : v.version === flightView.selected_version);
          return (
            <button key={v.prediction_set} className={`ver-chip ${isSel ? 'active' : ''}`} onClick={() => v.kind !== 'ORIGINAL' && setSelectedVersion(v.version)}
              title={v.kind === 'ORIGINAL' ? 'Immutable original prediction (always shown)' : `Anchored at ${utc(v.anchor_timestamp)} (${v.anchor_phase})`}>
              <i className="dot" style={{ background: v.kind === 'ORIGINAL' ? COLOURS.original : COLOURS.revised }} />
              V{v.version} {v.kind === 'ORIGINAL' ? 'Original' : v.kind === 'REVISED' ? `Revised ${utc(v.anchor_timestamp).slice(11, 19)}Z` : 'Attached'}
            </button>
          );
        })}
        {!versions.length && <span className="muted">No prediction attached yet.</span>}
      </div>
      <p className="small muted">Each telemetry update creates a new version; earlier versions are never overwritten. Select a version to compare it with the original.</p>
      <div className="form-grid">
        <Field label="Baseline model run (only if not recorded)" value={base} onChange={setBase}
          options={[{ value: '', label: 'Use the original prediction’s model run' }, ...jobs.map((j) => ({ value: j.simulation_id, label: j.simulation_id }))]} />
        <Field label="Planned end of float (UTC, optional)" type="datetime-local" step="1" value={floatEnd} onChange={setFloatEnd} />
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn primary" disabled={!missionId || (job && ['QUEUED', 'RUNNING'].includes(job.status))} onClick={run}>Re-forecast from latest telemetry</button>
      </div>
      <JobStatus job={job} />
      <ErrorBox error={error} />
      {msg && <div className="alert-box" role="status">{msg}</div>}
      {mission?.mode === 'SIMULATION' && <p className="small muted">Simulation mission: telemetry and re-forecasts use simulated data.</p>}
    </Panel>
  );
}

/** Original vs revised vs actual landing, durations, displacement. All distances are WGS-84 geodesic. */
function ComparisonSummary({ fv }) {
  const c = fv?.comparison;
  if (!c?.original_landing) return null;
  const rv = fv.revised?.summary;
  const landRow = (label, p) => [label, p ? `${fmtLatLon(p.lat, p.lon)} · ${utc(p.t)}` : 'Not available'];
  return (
    <Panel title="Original vs revised vs actual">
      <KV items={[
        landRow('Original predicted landing (V1)', c.original_landing),
        landRow(`Revised predicted landing${rv ? ` (V${rv.version})` : ''}`, c.revised_landing),
        ['Actual landing', c.actual_landing ? `${fmtLatLon(c.actual_landing.lat, c.actual_landing.lon)} · ${utc(c.actual_landing.t)}` : 'Not landed yet'],
        c.landing_shift_m != null && ['Original → revised landing', `${km(c.landing_shift_m)} toward ${Math.round(c.landing_shift_bearing_deg)}° ${bearingName(c.landing_shift_bearing_deg)} (Δlat ${fmt(c.landing_shift_dlat_deg, 4)}°, Δlon ${fmt(c.landing_shift_dlon_deg, 4)}°)`],
        c.revised_remaining_duration_s != null && ['Predicted remaining flight time (revised)', duration(c.revised_remaining_duration_s)],
        c.original_remaining_duration_s_from_anchor != null && ['Same interval per original prediction', duration(c.original_remaining_duration_s_from_anchor)],
        c.revised_landing_time && ['Estimated landing time (revised)', `${utc(c.revised_landing_time)} (${c.landing_time_shift_s >= 0 ? '+' : ''}${fmt(c.landing_time_shift_s / 60, 1)} min vs original)`],
        c.trajectory_displacement && ['Trajectory displacement (mean / max / at landing)', `${km(c.trajectory_displacement.mean_m)} / ${km(c.trajectory_displacement.max_m)} / ${km(c.trajectory_displacement.final_m)}`],
        c.actual_vs_original_landing_error_m != null && ['Actual vs original landing error', km(c.actual_vs_original_landing_error_m)],
        c.actual_vs_revised_landing_error_m != null && ['Actual vs revised landing error', km(c.actual_vs_revised_landing_error_m)],
      ]} />
    </Panel>
  );
}

export default function PredictionComparison() {
  const { comparison, mission, setComparison, version, flightView } = useWS1();
  useEffect(() => { if (mission) telemetryService.comparison(mission.mission_id).then(setComparison).catch(() => {}); }, [version > 0 && Math.floor(version / 10), mission?.mission_id]); // eslint-disable-line
  const c = comparison;
  const series = useMemo(() => {
    if (!c?.series?.length) return null;
    const x = c.series.map((s) => toSec(s.t));
    return { x, altErr: c.series.map((s) => s.altitude_error_m), hErr: c.series.map((s) => s.horizontal_error_m),
      predAlt: c.series.map((s) => s.predicted.alt), actAlt: c.series.map((s) => s.actual.alt) };
  }, [c]);
  // Position-error series for the original and the selected revised version, merged on one time axis.
  const errChart = useMemo(() => {
    const es = flightView?.error_series;
    if (!es?.sufficient) return null;
    const times = [...new Set([...es.original, ...es.revised].map((r) => toSec(r.t)))].sort((a, b) => a - b);
    const at = (arr) => { const m = new Map(arr.map((r) => [toSec(r.t), r.horizontal_error_m])); return times.map((t) => m.get(t) ?? null); };
    return { x: times, orig: at(es.original), rev: at(es.revised) };
  }, [flightView]);
  // Separation segments between actual and time-aligned predicted positions (sampled).
  const sep = useMemo(() => {
    if (!c?.series?.length) return [];
    const step = Math.max(1, Math.floor(c.series.length / 25));
    return c.series.filter((_, i) => i % step === 0);
  }, [c]);
  if (!mission) return <div className="notice">Select or create a mission in Overview.</div>;
  if (!c?.available) return (
    <div className="split"><div className="stack"><VersionPanel /></div>
      <div className="notice">No prediction is attached to this mission. Run the burst calculator and choose “Use as mission prediction”, or start a simulation (its baseline is attached automatically).</div></div>
  );
  const last = c.series[c.series.length - 1];
  const rows = last ? [
    ['Latitude', last.predicted.lat, last.actual.lat, 5, '°'], ['Longitude', last.predicted.lon, last.actual.lon, 5, '°'],
    ['Altitude', last.predicted.alt, last.actual.alt, 0, 'm'], ['Vertical velocity', last.predicted.vz, last.actual.vz, 2, 'm/s'],
    ['Wind speed', last.predicted.wind_speed, last.actual.wind_speed, 1, 'm/s'], ['Temperature', last.predicted.temperature_c, last.actual.temperature_c, 1, '°C'],
  ] : [];
  return (
    <div className="stack">
      {sep.map((s, i) => (
        <TrajectoryPolyline key={i} id={`ws1:sep${i}`} scope="ws1" colour={COLOURS.separation} weight={2} arrows={false}
          points={[{ ...s.actual, t: s.t }, { ...s.predicted, t: s.t }]} label={i === 0 ? 'Predicted–actual separation' : undefined} />
      ))}
      <div className="grid g2">
        <Panel title={`Predicted vs actual at ${utc(last?.t)}`} tight>
          <table className="data"><thead><tr><th>Parameter</th><th className="num">Predicted</th><th className="num">Actual</th><th className="num">Error</th></tr></thead>
            <tbody>{rows.map(([l, pv, av, d, u]) => (
              <tr key={l}><td>{l}</td><td className="num">{fmt(pv, d)}</td><td className="num">{fmt(av, d)}</td>
                <td className="num">{pv != null && av != null ? `${fmt(av - pv, d)} ${u}` : 'N/A'}</td></tr>
            ))}
              <tr><td>Horizontal separation</td><td colSpan={2} /><td className="num">{km(last?.horizontal_error_m)}</td></tr></tbody></table>
        </Panel>
        <Panel title="Prediction accuracy statistics">
          <KV items={[['Samples compared', c.statistics?.samples], ['Mean |altitude error|', `${fmt(c.statistics?.mean_abs_altitude_error_m, 1)} m`],
            ['Max |altitude error|', `${fmt(c.statistics?.max_abs_altitude_error_m, 1)} m`], ['Mean horizontal error', km(c.statistics?.mean_horizontal_error_m)],
            ['Max horizontal error', km(c.statistics?.max_horizontal_error_m)], ['Prediction generated', utc(c.prediction_generated_utc)],
            ['Forecast initialisation', c.forecast_cycle || 'N/A'], ['Forecast valid', `${utc(c.forecast_valid_from_utc)} → ${utc(c.forecast_valid_to_utc_exclusive)} (excl.)`],
            ['Model version', c.model_version], ['Prediction source', c.source],
            ['Excluded (outside prediction span)', c.excluded_samples_outside_prediction_span],
            ['Outside forecast valid window', c.samples_outside_forecast_valid_window]]} />
          <p className="small muted">{c.alignment}</p>
        </Panel>
      </div>
      <div className="split-map">
        <MissionMap scope="ws1" height="440px" />
        <div className="stack"><VersionPanel /><ComparisonSummary fv={flightView} /></div>
      </div>
      {errChart && (
        <ChartPanel title="Horizontal position error vs time (geodesic)" unit="m" x={errChart.x} syncKey="cmp"
          series={[{ label: 'vs original prediction', colour: COLOURS.original, values: errChart.orig },
            { label: 'vs revised prediction', colour: COLOURS.revised, values: errChart.rev }]} />
      )}
      {series && (
        <div className="grid gcharts">
          <ChartPanel title="Altitude: predicted vs actual" unit="m" x={series.x} syncKey="cmp"
            series={[{ label: 'Predicted', colour: COLOURS.original, values: series.predAlt, dashed: true }, { label: 'Actual', colour: COLOURS.actual, values: series.actAlt }]} />
          <ChartPanel title="Altitude prediction error" unit="m" x={series.x} syncKey="cmp" series={[{ label: 'Actual − predicted', colour: '#f2b33d', values: series.altErr }]} />
          <ChartPanel title="Horizontal position error" unit="m" x={series.x} syncKey="cmp" series={[{ label: 'Separation', colour: '#f0504a', values: series.hErr }]} />
        </div>
      )}
    </div>
  );
}
