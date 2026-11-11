import { useEffect, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { ErrorBox, Field, Panel, Pill } from '../../components/Common/ui';
import { telemetryService } from '../../services/apiClient';
import { fmt, utc } from '../../utils/format';

const PAGE = 100;
export default function TelemetryHistory() {
  const { mission } = useWS1();
  const [range, setRange] = useState({ start: '', end: '' });
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const load = () => mission && telemetryService.history(mission.mission_id, {
    start: range.start ? `${range.start}:00Z` : undefined, end: range.end ? `${range.end}:00Z` : undefined, limit: PAGE, offset: page * PAGE,
  }).then(setData).catch(setErr);
  useEffect(() => { load(); }, [mission?.mission_id, page]); // eslint-disable-line
  if (!mission) return <div className="notice">Select or create a mission in Overview.</div>;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;
  return (
    <div className="stack">
      <Panel title="Query">
        <div className="row">
          <Field label="From (UTC)" type="datetime-local" value={range.start} onChange={(v) => setRange({ ...range, start: v })} />
          <Field label="To (UTC)" type="datetime-local" value={range.end} onChange={(v) => setRange({ ...range, end: v })} />
          <button className="btn primary" onClick={() => { setPage(0); load(); }}>Search</button>
          <a className="btn" href={telemetryService.historyCsvUrl(mission.mission_id)}>Export all as CSV</a>
        </div>
      </Panel>
      <ErrorBox error={err} />
      <Panel title={`Stored packets (${data?.total ?? 0})`} tight
        actions={<div className="row small"><button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {page + 1} of {pages}</span><button className="btn sm" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button></div>}>
        <div className="scroll" style={{ maxHeight: 'calc(100vh - 320px)' }}>
          <table className="data"><thead><tr><th>Packet time (UTC)</th><th>Received (UTC)</th><th>Packet</th><th>Source</th><th>Quality</th>
            <th className="num">Lat</th><th className="num">Lon</th><th className="num">Alt m</th><th className="num">Vz</th><th className="num">T °C</th><th className="num">P hPa</th><th className="num">ΔP Pa</th><th className="num">Batt V</th><th>Flags</th></tr></thead>
            <tbody>{data?.items.map((it) => { const p = it.payload; return (
              <tr key={it.packet_id}><td>{utc(it.timestamp_utc)}</td><td className="small muted">{utc(it.received_utc)}</td><td>{it.packet_id}</td><td>{it.data_source}</td>
                <td><Pill status={it.quality} /></td><td className="num">{fmt(p.latitude, 5)}</td><td className="num">{fmt(p.longitude, 5)}</td>
                <td className="num">{fmt(p.gps_altitude, 0)}</td><td className="num">{fmt(p.vertical_velocity, 2)}</td><td className="num">{fmt(p.ambient_temperature, 1)}</td>
                <td className="num">{fmt(p.atmospheric_pressure, 2)}</td><td className="num">{fmt(p.differential_pressure, 0)}</td><td className="num">{fmt(p.battery_voltage, 2)}</td>
                <td className="small">{it.quality_flags.join(', ')}</td></tr>); })}</tbody></table>
        </div>
      </Panel>
    </div>
  );
}
