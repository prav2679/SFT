import { duration } from '../../utils/format';

const ORDER = ['PRE-LAUNCH', 'ASCENT', 'FLOAT', 'DESCENT', 'LANDED'];
export default function PhaseBand({ phase, since, latestTs }) {
  const idx = ORDER.indexOf(phase);
  const inPhase = since && latestTs ? (new Date(latestTs) - new Date(since)) / 1000 : null;
  return (
    <div className="phase-band" role="list" aria-label="Flight phase">
      {ORDER.map((p, i) => (
        <div key={p} role="listitem" aria-current={p === phase}
          className={`phase-step ${phase === 'ABORTED' ? (i === 0 ? 'aborted' : '') : i < idx ? 'done' : i === idx ? 'current' : ''}`}>
          {phase === 'ABORTED' && i === 0 ? 'ABORTED' : p}
          {p === phase && inPhase != null && inPhase >= 0 && <small>{duration(inPhase)} in phase (mission time)</small>}
        </div>
      ))}
    </div>
  );
}
