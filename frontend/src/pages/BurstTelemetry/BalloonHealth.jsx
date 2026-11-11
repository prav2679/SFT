import { useWS1 } from './BurstTelemetryPage';
import { KV, Panel, ValueClass } from '../../components/Common/ui';
import { fmt, isNum } from '../../utils/format';
import { previousValue, valueClass } from './telemetryModel';

function Row({ label, field, unit, d = 1, value, vc }) {
  const { latest } = useWS1();
  const v = value !== undefined ? value : latest?.payload?.[field];
  return [label, <span key={label}>{fmt(v, d)}{isNum(v) && unit ? ` ${unit}` : ''} <ValueClass vc={vc || valueClass(latest, field)} /></span>];
}

export default function BalloonHealth() {
  const { latest, packets, mission } = useWS1();
  if (!mission) return <div className="notice">Select or create a mission in Overview.</div>;
  const p = latest?.payload || {};
  const th = mission.config.thresholds;
  const src = latest?.data_source === 'SIMULATED' ? 'SIMULATED' : 'MEASURED';
  const dT = isNum(p.internal_gas_temperature) && isNum(p.ambient_temperature) ? p.internal_gas_temperature - p.ambient_temperature : null;
  const prevGas = previousValue(packets, 'internal_gas_temperature');
  const margin = isNum(p.differential_pressure) ? th.differential_pressure_max_pa - p.differential_pressure : null;
  const refV = mission.config.reference_volume_m3;
  const m = mission.config.masses_kg || {};
  const weight = m.payload && m.envelope && m.helium ? (m.payload + m.envelope + m.helium) * 9.80665 : null;
  return (
    <div className="stack">
      <div className="notice small">Estimated values are labelled MODEL EST. and are never shown as sensor measurements. Burst probability is not shown: no validated burst-probability model exists.</div>
      <div className="grid g2">
        <Panel title="Thermal health">
          <KV items={[Row({ label: 'Internal gas temperature', field: 'internal_gas_temperature', unit: '°C' }),
            Row({ label: 'Envelope temperature', field: 'envelope_temperature', unit: '°C' }),
            Row({ label: 'Ambient temperature', field: 'ambient_temperature', unit: '°C' }),
            Row({ label: 'Gas − ambient (superheat)', value: dT, unit: 'K', vc: dT == null ? 'UNAVAILABLE' : src }),
            ['Gas temperature trend', isNum(p.internal_gas_temperature) && isNum(prevGas) ? (p.internal_gas_temperature >= prevGas ? '▲ rising' : '▼ falling') : 'N/A']]} />
        </Panel>
        <Panel title="Pressure health">
          <KV items={[Row({ label: 'Internal pressure', field: 'internal_pressure', unit: 'hPa', d: 2 }),
            Row({ label: 'External atmospheric pressure', field: 'atmospheric_pressure', unit: 'hPa', d: 2 }),
            Row({ label: 'Differential pressure', field: 'differential_pressure', unit: 'Pa', d: 0 }),
            ['Configured maximum ΔP', `${fmt(th.differential_pressure_max_pa, 0)} Pa (configured)`],
            Row({ label: 'Remaining pressure margin', value: margin, unit: 'Pa', d: 0, vc: margin == null ? 'UNAVAILABLE' : src })]} />
          {isNum(margin) && (
            <div className="progress" style={{ marginTop: 8 }} aria-label="Pressure margin used">
              <div style={{ width: `${Math.max(0, Math.min(100, (p.differential_pressure / th.differential_pressure_max_pa) * 100))}%`,
                background: margin < 0 ? 'var(--red)' : p.differential_pressure > th.differential_pressure_max_pa * th.differential_pressure_warn_fraction ? 'var(--amber)' : 'var(--green)' }} />
            </div>
          )}
        </Panel>
        <Panel title="Buoyancy">
          <KV items={[Row({ label: 'Estimated gross lift', field: 'est_gross_lift_n', unit: 'N' }),
            ['Payload + envelope + gas weight', weight ? `${fmt(weight, 1)} N (configured masses)` : 'N/A — configure masses'],
            Row({ label: 'Estimated net lift', field: 'est_net_lift_n', unit: 'N', d: 2 }),
            Row({ label: 'Estimated vertical acceleration', field: 'est_vertical_acceleration_ms2', unit: 'm/s²', d: 3 })]} />
          <p className="small muted">Requires measured balloon volume, ambient pressure and temperature, plus configured masses. Drag is not included.</p>
        </Panel>
        <Panel title="Envelope health">
          <KV items={[Row({ label: 'Balloon volume', field: 'balloon_volume', unit: 'm³' }),
            ['Volume vs reference', isNum(p.balloon_volume) && refV ? `${fmt((p.balloon_volume / refV) * 100, 1)} % of ${refV} m³` : 'N/A — set reference volume'],
            ['Envelope compliance estimate', 'Not supported by a validated model'],
            ['Pressure-volume state', isNum(p.differential_pressure) ? (p.differential_pressure < 0 ? 'Slack (under-pressurised)' : 'Taut (super-pressure)') : 'N/A']]} />
        </Panel>
      </div>
    </div>
  );
}
