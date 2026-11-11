import { useWS1 } from './BurstTelemetryPage';
import { Panel, Pill } from '../../components/Common/ui';
import TelemetryCard from '../../components/Telemetry/TelemetryCard';
import MissionMap from '../../components/Map/MissionMap';
import { lastUpdated, previousValue, valueClass } from './telemetryModel';
import PhaseBand from './PhaseBand';

export const GROUPS = {
  'Navigation': [['latitude', 'Latitude', '°', 5], ['longitude', 'Longitude', '°', 5], ['gps_altitude', 'GPS altitude', 'm', 0],
    ['vertical_velocity', 'Vertical velocity', 'm/s', 2], ['ground_speed', 'Ground speed', 'm/s', 1], ['heading', 'Ground track', '°', 0],
    ['_distance_travelled_m', 'Distance travelled', 'm', 0], ['distance_from_launch_m', 'Distance from launch', 'm', 0]],
  'Atmospheric': [['ambient_temperature', 'Ambient temperature', '°C', 1], ['atmospheric_pressure', 'Atmospheric pressure', 'hPa', 2],
    ['relative_humidity', 'Relative humidity', '%', 0], ['wind_speed', 'Wind speed', 'm/s', 1],
    ['wind_direction_from', 'Wind direction FROM', '°', 0], ['wind_direction_toward', 'Wind direction TOWARD', '°', 0]],
  'Balloon': [['internal_gas_temperature', 'Internal gas temperature', '°C', 1], ['envelope_temperature', 'Envelope temperature', '°C', 1],
    ['internal_pressure', 'Internal pressure', 'hPa', 2], ['atmospheric_pressure', 'External pressure', 'hPa', 2],
    ['differential_pressure', 'Differential pressure', 'Pa', 0], ['balloon_volume', 'Balloon volume', 'm³', 1],
    ['est_gross_lift_n', 'Estimated buoyant force', 'N', 1], ['est_net_lift_n', 'Estimated net lift', 'N', 2]],
  'Payload health': [['battery_voltage', 'Battery voltage', 'V', 2], ['battery_current', 'Battery current', 'A', 2],
    ['battery_percentage', 'Battery percentage', '%', 0], ['payload_temperature', 'Payload temperature', '°C', 1],
    ['system_uptime', 'System uptime', 's', 0], ['cpu_temperature', 'CPU temperature', '°C', 1], ['storage_free_pct', 'Storage free', '%', 0]],
  'IMU': [['accel_x', 'Acceleration X', 'm/s²', 2], ['accel_y', 'Acceleration Y', 'm/s²', 2], ['accel_z', 'Acceleration Z', 'm/s²', 2],
    ['gyro_x', 'Angular velocity X', '°/s', 2], ['gyro_y', 'Angular velocity Y', '°/s', 2], ['gyro_z', 'Angular velocity Z', '°/s', 2],
    ['roll', 'Roll', '°', 1], ['pitch', 'Pitch', '°', 1], ['yaw', 'Yaw', '°', 1]],
};

export function levelFor(field, v, th) {
  if (v == null || !th) return '';
  if (field === 'differential_pressure') return v > th.differential_pressure_max_pa ? 'crit' : v > th.differential_pressure_max_pa * th.differential_pressure_warn_fraction ? 'warn' : '';
  if (field === 'battery_voltage') return v < th.battery_critical_v ? 'crit' : v < th.battery_warning_v ? 'warn' : '';
  if (field === 'payload_temperature') return v > th.payload_temperature_max_c || v < th.payload_temperature_min_c ? 'warn' : '';
  if (field === 'internal_gas_temperature') return v > th.internal_gas_temperature_max_c ? 'warn' : '';
  if (field === 'wind_speed') return v > th.wind_speed_max_ms ? 'warn' : '';
  return '';
}

export function CardGroup({ title, fields }) {
  const { packets, latest, mission } = useWS1();
  const th = mission?.config?.thresholds;
  const sensors = mission?.config?.sensors || [];
  const allNA = fields.every(([f]) => latest?.payload?.[f] == null);
  if (title === 'IMU' && allNA && !sensors.includes('imu')) {
    return <Panel title="IMU"><span className="muted small">No IMU configured for this mission — values are N/A.</span></Panel>;
  }
  return (
    <Panel title={title}>
      <div className="grid gauto">
        {fields.map(([f, label, unit, d]) => (
          <TelemetryCard key={f + label} label={label} unit={unit} digits={d} value={latest?.payload?.[f]}
            previous={previousValue(packets, f)} updated={lastUpdated(packets, f)} vc={valueClass(latest, f)}
            quality={latest?.quality} level={levelFor(f, latest?.payload?.[f], th)} />
        ))}
      </div>
    </Panel>
  );
}

export default function LiveTelemetry() {
  const { latest, status, transport, mission } = useWS1();
  if (!mission) return <div className="notice">Select or create a mission in Overview.</div>;
  return (
    <div className="stack">
      <div className="row">
        <Pill status={status?.connection || 'DISCONNECTED'}>TELEMETRY {status?.connection || 'DISCONNECTED'}</Pill>
        <Pill status={transport}>{transport}</Pill>
        {latest && <Pill status={latest.quality}>PACKET {latest.quality}</Pill>}
        {latest?.quality_flags?.length > 0 && <span className="small muted">Flags: {latest.quality_flags.join(', ')}</span>}
        <span className="spacer" />
        <span className="small muted">Source: {latest?.data_source || '—'} · packet {latest?.packet_id || '—'}</span>
      </div>
      <PhaseBand phase={status?.flight_phase || mission.flight_phase} since={status?.phase_since || mission.phase_since} latestTs={latest?.timestamp_utc} />
      <div className="split-map">
        <MissionMap scope="ws1" height="calc(100vh - 290px)" />
        <div className="stack scroll" style={{ maxHeight: 'calc(100vh - 290px)' }}>
          <CardGroup title="Navigation" fields={GROUPS.Navigation} />
          <CardGroup title="Atmospheric" fields={GROUPS.Atmospheric} />
        </div>
      </div>
      <div className="grid g2">
        <CardGroup title="Balloon" fields={GROUPS.Balloon} />
        <CardGroup title="Payload health" fields={GROUPS['Payload health']} />
      </div>
      <CardGroup title="IMU" fields={GROUPS.IMU} />
      {mission.config?.simulation_note && <div className="notice small">{mission.config.simulation_note}</div>}
    </div>
  );
}
