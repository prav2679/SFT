import { memo } from 'react';
import { ValueClass } from '../Common/ui';
import { isNum, utcShort } from '../../utils/format';

/** Every card: value, unit, trend vs previous, last-updated, source class, quality, warning state. */
function TelemetryCard({ label, value, unit, digits = 1, previous, updated, vc, quality, level, sensorMissing }) {
  const na = !isNum(value);
  const delta = isNum(value) && isNum(previous) ? value - previous : null;
  return (
    <div className={`tcard ${level || ''}`}>
      <div className="t-top"><span>{label}</span><ValueClass vc={na ? 'UNAVAILABLE' : vc} /></div>
      <div className={`t-val ${na ? 'na' : ''}`}>
        {na ? 'N/A' : value.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits })}
        {!na && unit && <small>{unit}</small>}
      </div>
      <div className="t-meta">
        <span>{delta == null ? (sensorMissing ? 'Sensor not configured' : '—') : (
          <span className={delta >= 0 ? 'trend-up' : 'trend-down'}>{delta >= 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(digits)}</span>)}</span>
        <span>{quality && quality !== 'VALID' ? <b className={quality === 'STALE' || quality === 'DEGRADED' ? 's-warn' : 's-crit'}>{quality} </b> : null}{utcShort(updated)}</span>
      </div>
    </div>
  );
}
export default memo(TelemetryCard);
