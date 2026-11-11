import { useMemo, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { Panel, Pill, Seg } from '../../components/Common/ui';
import { fmt, utc } from '../../utils/format';

export default function AlertsEvents() {
  const { alerts, acknowledge, mission } = useWS1();
  const [sev, setSev] = useState('ALL');
  const [onlyOpen, setOnlyOpen] = useState(false);
  const list = useMemo(() => alerts.filter((a) => (sev === 'ALL' || a.severity === sev) && (!onlyOpen || !a.acknowledged)), [alerts, sev, onlyOpen]);
  const counts = useMemo(() => ({ CRITICAL: alerts.filter((a) => a.severity === 'CRITICAL' && !a.acknowledged).length,
    WARNING: alerts.filter((a) => a.severity === 'WARNING' && !a.acknowledged).length }), [alerts]);
  if (!mission) return <div className="notice">Select or create a mission in Overview.</div>;
  return (
    <div className="stack">
      <div className="row">
        <Pill status={counts.CRITICAL ? 'CRITICAL' : 'NONE'}>{counts.CRITICAL} CRITICAL OPEN</Pill>
        <Pill status={counts.WARNING ? 'WARNING' : 'NONE'}>{counts.WARNING} WARNING OPEN</Pill>
        <span className="spacer" />
        <Seg options={['ALL', 'CRITICAL', 'WARNING', 'INFO'].map((s) => ({ value: s, label: s === 'ALL' ? 'All' : s[0] + s.slice(1).toLowerCase() }))} value={sev} onChange={setSev} />
        <label className="row small"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />Unacknowledged only</label>
      </div>
      <div className="notice small">Alerts are advisory. The dashboard never executes flight-control commands in response to an alert.</div>
      <Panel title={`Alerts & events (${list.length})`} tight>
        <div className="scroll" style={{ maxHeight: 'calc(100vh - 290px)' }}>
          <table className="data">
            <thead><tr><th>Alert ID</th><th>Timestamp (UTC)</th><th>Category</th><th>Severity</th><th>Parameter</th>
              <th className="num">Actual</th><th className="num">Threshold</th><th>Description</th><th>Source</th><th>Acknowledgement</th></tr></thead>
            <tbody>{list.map((a) => (
              <tr key={a.alert_id}>
                <td>{a.alert_id}</td><td>{utc(a.timestamp_utc)}</td><td>{a.category}</td><td><Pill status={a.severity} /></td>
                <td>{a.parameter || '—'}</td><td className="num">{a.measured_value != null ? fmt(a.measured_value, 2) : '—'}</td>
                <td className="num">{a.threshold != null ? fmt(a.threshold, 2) : '—'}</td><td>{a.description}</td><td>{a.data_source || '—'}</td>
                <td>{a.acknowledged ? <span className="small muted">by {a.acknowledged_by} {utc(a.acknowledged_at)}</span>
                  : <button className="btn sm" onClick={() => acknowledge(a.alert_id)}>Acknowledge</button>}</td>
              </tr>
            ))}</tbody>
          </table>
          {!list.length && <div className="panel-b muted">No alerts match this filter.</div>}
        </div>
      </Panel>
    </div>
  );
}
