import { useMemo, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { Seg } from '../../components/Common/ui';
import ChartPanel from '../../components/Charts/ChartPanel';
import { RANGES, seriesFor } from './telemetryModel';

const CHARTS = [
  ['gps_altitude', 'Altitude vs time', 'm', '#3dd6f5'], ['vertical_velocity', 'Vertical velocity vs time', 'm/s', '#3fd07a'],
  ['ambient_temperature', 'Ambient temperature vs time', '°C', '#f2b33d'], ['internal_gas_temperature', 'Internal gas temperature vs time', '°C', '#ff9a52'],
  ['envelope_temperature', 'Envelope temperature vs time', '°C', '#f0504a'], ['atmospheric_pressure', 'Atmospheric pressure vs time', 'hPa', '#b48cff'],
  ['differential_pressure', 'Differential pressure vs time', 'Pa', '#f0504a'], ['wind_speed', 'Wind speed vs time', 'm/s', '#3fd07a'],
  ['battery_voltage', 'Battery voltage vs time', 'V', '#f2b33d'], ['balloon_volume', 'Balloon volume vs time', 'm³', '#3dd6f5'],
];

export default function FlightAnalytics() {
  const { packets, version, latest, mission } = useWS1();
  const [range, setRange] = useState('all');
  const rs = RANGES.find((r) => r.id === range).s;
  const { x, cols } = useMemo(() => seriesFor(packets, CHARTS.map((c) => c[0]), rs), [version, rs]); // eslint-disable-line react-hooks/exhaustive-deps
  const vc = latest?.data_source === 'SIMULATED' ? 'SIMULATED' : 'MEASURED';
  if (!mission) return <div className="notice">Select or create a mission in Overview.</div>;
  return (
    <div className="stack">
      <div className="row">
        <Seg options={RANGES.map((r) => ({ value: r.id, label: r.label }))} value={range} onChange={setRange} />
        <span className="small muted">Window ends at the latest packet time (UTC). Drag across a chart to zoom; double-click to reset.</span>
      </div>
      <div className="grid gcharts">
        {CHARTS.map(([f, title, unit, colour]) => (
          <ChartPanel key={f} title={title} unit={unit} valueClass={vc} x={x} syncKey="ws1-live"
            series={[{ label: title.split(' vs')[0], colour, values: cols[f] }]} csvName={`${mission.mission_id}_${f}`} />
        ))}
      </div>
    </div>
  );
}
