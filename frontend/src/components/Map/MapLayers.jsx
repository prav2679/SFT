// Declarative wrappers: each updates only its own keyed layer in the shared map.
import { useEffect } from 'react';
import * as store from './mapStore';

/** The one colour scheme used throughout the application (high-contrast on street and satellite imagery). */
export const COLOURS = {
  original: '#2979FF',   // Electric Blue  - original prediction
  actual: '#00E676',     // Bright Green   - actual telemetry
  revised: '#FF9100',    // Amber Orange   - revised prediction
  sft: '#AA00FF',        // Royal Purple   - SFT forward model
  tawhiri: '#FF1744',    // Magenta Red    - Tawhiri forward model
  reverse: '#FFD600',    // Yellow         - reverse trajectory
  diurnal: '#FFFFFF',    // White          - diurnal trajectory
  separation: '#ff5252',
};
COLOURS.predicted = COLOURS.original;   // legacy alias

/** Legend rows per workspace scope; layer visibility is controlled independently per row. */
export const LEGEND = {
  ws1: [
    { key: 'ws1:original', label: 'Original Prediction', colour: COLOURS.original, dashed: true },
    { key: 'ws1:actual', label: 'Actual Flight Path', colour: COLOURS.actual },
    { key: 'ws1:revised', label: 'Revised Prediction', colour: COLOURS.revised, dashed: true },
    { key: 'ws1:calc', label: 'SFT Prediction (burst calculator)', colour: COLOURS.sft, dashed: true },
  ],
  ws2: [
    { key: 'ws2:sft', label: 'SFT Prediction', colour: COLOURS.sft, dashed: true },
    { key: 'ws2:tawhiri', label: 'Tawhiri Prediction', colour: COLOURS.tawhiri, dashed: true },
    { key: 'ws2:reverse', label: 'Reverse Trajectory', colour: COLOURS.reverse, dashed: true },
  ],
  ws3: [{ key: 'ws3:path', label: 'Diurnal Trajectory', colour: COLOURS.diurnal, dashed: true }],
};

export function TrajectoryPolyline({ id, scope, points, colour, dashed = false, label, weight = 4.5, arrows = true }) {
  useEffect(() => {
    if (!points || points.length < 2) { store.removeLayer(id); return; }
    store.setPolyline(id, scope, points, { color: colour, weight, dashArray: dashed ? '10 8' : null },
      { legend: !!label, label, colour, dashed, arrows });
  }, [id, scope, points, colour, dashed, label, weight, arrows]);
  useEffect(() => () => store.removeLayer(id), [id]);
  return null;
}

export function PointMarker({ id, scope, point, kind, popup, colour }) {
  const lat = point?.lat, lon = point?.lon;
  useEffect(() => {
    store.setMarker(id, scope, lat != null ? { lat, lon } : null, { kind, popup, colour });
  }, [id, scope, lat, lon, kind, popup, colour]);
  useEffect(() => () => store.removeLayer(id), [id]);
  return null;
}

export function BalloonMarker({ id, scope, point, heading, colour = '#3dd6f5', popup }) {
  const lat = point?.lat, lon = point?.lon;
  useEffect(() => {
    store.setMarker(id, scope, lat != null ? { lat, lon } : null, { kind: 'balloon', heading, colour, popup });
  }, [id, scope, lat, lon, heading, colour, popup]);
  useEffect(() => () => store.removeLayer(id), [id]);
  return null;
}

export function WindArrow({ id, scope, point, towardDeg }) {
  const lat = point?.lat, lon = point?.lon;
  useEffect(() => {
    store.setMarker(id, scope, lat != null && towardDeg != null ? { lat, lon } : null, { kind: 'wind', heading: towardDeg });
  }, [id, scope, lat, lon, towardDeg]);
  useEffect(() => () => store.removeLayer(id), [id]);
  return null;
}

export function FitOnChange({ keys, dep }) {
  useEffect(() => { if (dep) setTimeout(() => store.fitTo(keys), 50); }, [dep]); // eslint-disable-line
  return null;
}

/** Registers the legend rows of a workspace scope. */
export function LegendDefs({ scope, defs }) {
  useEffect(() => { store.setLegend(scope, defs); }, [scope, defs]);
  return null;
}
