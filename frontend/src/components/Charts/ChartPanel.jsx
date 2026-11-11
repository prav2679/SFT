import { memo, useMemo, useState } from 'react';
import TimeSeriesChart from './TimeSeriesChart';
import { downloadCsv } from '../../utils/format';

/** Panel with title, value-class badge, visibility toggle and CSV export. */
function ChartPanel({ title, unit, x, series, valueClass, height = 190, xTime = true, xLabel, syncKey, bands, markers, note, csvName }) {
  const [hidden, setHidden] = useState(false);
  const hasData = useMemo(() => x?.length > 1 && series.some((s) => s.values.some((v) => v != null)), [x, series]);
  const exportCsv = () => downloadCsv(`${csvName || title.replace(/\W+/g, '_')}.csv`,
    [xTime ? 'timestamp_utc' : xLabel || 'x', ...series.map((s) => `${s.label}${unit ? ` (${unit})` : ''}`)],
    x.map((xv, i) => [xTime ? new Date(xv * 1000).toISOString() : xv, ...series.map((s) => s.values[i])]));
  return (
    <section className="panel chart-panel">
      <div className="panel-h">
        <h3>{title}</h3>
        {unit && <span className="muted small">{unit}</span>}
        {valueClass && <span className={`badge vc-${valueClass}`}>{valueClass === 'ESTIMATE' ? 'MODEL EST.' : valueClass}</span>}
        <span className="spacer" />
        <button className="btn sm" onClick={exportCsv} disabled={!hasData}>CSV</button>
        <button className="btn sm" onClick={() => setHidden((h) => !h)} aria-expanded={!hidden}>{hidden ? 'Show' : 'Hide'}</button>
      </div>
      {!hidden && (
        <div className="panel-b">
          {hasData ? (
            <TimeSeriesChart x={x} series={series} height={height} xTime={xTime} xLabel={xLabel} yLabel={unit} syncKey={syncKey} bands={bands} markers={markers} />
          ) : <div className="chart-empty">No data available for this parameter</div>}
          {note && <div className="small muted" style={{ marginTop: 4 }}>{note}</div>}
        </div>
      )}
    </section>
  );
}
export default memo(ChartPanel);
