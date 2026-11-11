import { useMemo } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { KV, Panel } from '../../components/Common/ui';
import MissionMap from '../../components/Map/MissionMap';
import * as store from '../../components/Map/mapStore';
import { duration, fmt, fmtInt, toSec, utc } from '../../utils/format';
import PhaseBand from './PhaseBand';

export default function FlightTracking() {
  const { actual, latest, status, mission, version } = useWS1();
  const stats = useMemo(() => {
    if (!actual.length) return null;
    const vz = actual.map((q) => q.vz).filter((v) => v != null);
    const asc = vz.filter((v) => v > 0.5), desc = vz.filter((v) => v < -0.5);
    return {
      duration: toSec(actual[actual.length - 1].t) - toSec(actual[0].t),
      ascent: asc.length ? asc.reduce((a, b) => a + b, 0) / asc.length : null,
      descent: desc.length ? desc.reduce((a, b) => a + b, 0) / desc.length : null,
    };
  }, [version]); // eslint-disable-line react-hooks/exhaustive-deps
  const phase = status?.flight_phase || mission?.flight_phase;
  const since = status?.phase_since || mission?.phase_since;
  const recent = actual.slice(-200).reverse();
  if (!mission) return <div className="notice">Select or create a mission in Overview.</div>;
  return (
    <div className="stack">
      <PhaseBand phase={phase} since={since} latestTs={latest?.timestamp_utc} />
      <div className="split-map">
        <MissionMap scope="ws1" height="calc(100vh - 230px)" />
        <div className="stack">
          <Panel title="Flight phase monitoring">
            <KV items={[['Current phase', phase], ['Phase entered (mission time)', utc(since)],
              ['Time in current phase', since && latest ? duration((new Date(latest.timestamp_utc) - new Date(since)) / 1000) : 'N/A'],
              ['Current altitude', `${fmtInt(latest?.payload?.gps_altitude)} m`], ['Maximum altitude', `${fmtInt(status?.max_altitude)} m`],
              ['Mean ascent rate', `${fmt(stats?.ascent, 2)} m/s`], ['Mean descent rate', `${fmt(stats?.descent, 2)} m/s`],
              ['Total flight duration', duration(stats?.duration)]]} />
            <p className="small muted">Phase is detected from measured vertical velocity and altitude, never from a day/night schedule.</p>
          </Panel>
          <Panel title="Position history" tight>
            <div className="scroll" style={{ maxHeight: 'calc(100vh - 560px)', minHeight: 200 }}>
              <table className="data"><thead><tr><th>UTC</th><th className="num">Lat</th><th className="num">Lon</th><th className="num">Alt m</th></tr></thead>
                <tbody>{recent.map((q) => (
                  <tr key={q.t} style={{ cursor: 'pointer' }} onClick={() => store.getMap().setView([q.lat, q.lon], 12)}>
                    <td>{q.t.slice(11, 19)}Z</td><td className="num">{q.lat.toFixed(5)}</td><td className="num">{q.lon.toFixed(5)}</td><td className="num">{fmtInt(q.alt)}</td></tr>
                ))}</tbody></table>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
