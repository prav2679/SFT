// uPlot wrapper. The plot is created once per series layout and updated with setData(),
// so a new telemetry sample never rebuilds the chart. Drag to zoom, double-click to reset.
import { useEffect, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function bandsPlugin(getBands, getMarkers) {
  return {
    hooks: {
      drawClear: (u) => {
        const bands = getBands();
        if (!bands?.length) return;
        const { ctx } = u;
        const { top, height } = u.bbox;
        ctx.save();
        ctx.fillStyle = 'rgba(110,130,170,0.13)';
        for (const [a, b] of bands) {
          const x0 = u.valToPos(a, 'x', true), x1 = u.valToPos(b, 'x', true);
          ctx.fillRect(Math.min(x0, x1), top, Math.abs(x1 - x0), height);
        }
        ctx.restore();
      },
      draw: (u) => {
        const marks = getMarkers();
        if (!marks?.length) return;
        const { ctx } = u;
        const { top, height } = u.bbox;
        ctx.save();
        ctx.font = `${11 * devicePixelRatio}px Barlow, sans-serif`;
        for (const m of marks) {
          const x = u.valToPos(m.x, 'x', true);
          if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue;
          ctx.strokeStyle = m.colour || '#f2b33d';
          ctx.setLineDash([4 * devicePixelRatio, 3 * devicePixelRatio]);
          ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
          ctx.fillStyle = m.colour || '#f2b33d';
          ctx.fillText(m.label, x + 3 * devicePixelRatio, top + 12 * devicePixelRatio);
        }
        ctx.restore();
      },
    },
  };
}

/**
 * x: array of x values (unix seconds when xTime, else numeric)
 * series: [{label, colour, values, dashed?}]
 */
export default function TimeSeriesChart({ x, series, height = 200, xTime = true, xLabel, yLabel, syncKey, bands, markers }) {
  const el = useRef(null);
  const plot = useRef(null);
  const bandsRef = useRef(bands);
  const marksRef = useRef(markers);
  bandsRef.current = bands;
  marksRef.current = markers;
  const layout = series.map((s) => s.label).join('|') + `|${xTime}|${yLabel}`;

  useEffect(() => {
    const grid = { stroke: css('--line-soft') || '#1b3350', width: 1 };
    const axis = { stroke: css('--muted') || '#8da0b8', grid, ticks: grid, font: '11px Barlow, sans-serif' };
    const opts = {
      width: el.current.clientWidth || 400,
      height,
      scales: { x: { time: xTime } },
      cursor: syncKey ? { sync: { key: syncKey } } : {},
      legend: { live: true },
      axes: [{ ...axis, label: xLabel, ...(xTime ? {
        // Explicit 24-hour UTC tick labels (date shown when the day changes)
        values: (u, splits) => splits.map((v, i) => {
          const iso = new Date(v * 1000).toISOString();
          const prev = i > 0 ? new Date(splits[i - 1] * 1000).toISOString().slice(0, 10) : null;
          return iso.slice(0, 10) !== prev ? `${iso.slice(11, 16)}Z\n${iso.slice(5, 10)}` : `${iso.slice(11, 16)}Z`;
        }) } : {}) }, { ...axis, label: yLabel, size: 58 }],
      series: [{ label: xTime ? 'UTC' : xLabel || 'x', value: xTime ? (u, v) => (v == null ? '—' : new Date(v * 1000).toISOString().slice(11, 19) + 'Z') : undefined },
        ...series.map((s) => ({ label: s.label, stroke: s.colour, width: 1.6, dash: s.dashed ? [6, 4] : undefined, spanGaps: false, points: { show: false } }))],
      plugins: [bandsPlugin(() => bandsRef.current, () => marksRef.current)],
    };
    // uPlot uses UTC when tzDate returns UTC-shifted dates
    opts.tzDate = (ts) => uPlot.tzDate(new Date(ts * 1000), 'Etc/UTC');
    plot.current = new uPlot(opts, [x, ...series.map((s) => s.values)], el.current);
    const ro = new ResizeObserver(() => plot.current?.setSize({ width: el.current.clientWidth, height }));
    ro.observe(el.current);
    return () => { ro.disconnect(); plot.current?.destroy(); plot.current = null; };
  }, [layout, height]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (plot.current) plot.current.setData([x, ...series.map((s) => s.values)]);
  }, [x, series]);

  useEffect(() => { plot.current?.redraw(false); }, [bands, markers]);

  return <div ref={el} style={{ width: '100%' }} onDoubleClick={() => plot.current?.setData(plot.current.data)} />;
}
