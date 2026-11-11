// Map slot: hosts the single shared Leaflet map for the current workspace scope.
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import * as store from './mapStore';
import { useWorkspaceActive } from '../../context/AppContext';
import { LEGEND } from './MapLayers';

export function MapLegend() {
  const entries = useSyncExternalStore(store.subscribe, () => JSON.stringify(store.legendEntries()));
  const list = JSON.parse(entries);
  if (!list.length) return null;
  return (
    <div className="map-legend" role="group" aria-label="Map layers">
      {list.map((e) => (
        <label key={e.key} className={`lg-row ${e.present ? '' : 'absent'}`} title={e.present ? 'Show / hide this layer' : 'No data for this layer yet'}>
          <input type="checkbox" checked={e.present && !e.hidden} disabled={!e.present} onChange={() => store.toggleUser(e.key)} />
          <span className={`lg-swatch ${e.dashed ? 'dashed' : ''}`} style={{ borderTopColor: e.colour }} />
          {e.label}
        </label>
      ))}
      <div className="lg-markers" aria-label="Marker legend">
        <span><i className="lg-dot" style={{ background: '#2979FF' }} />Launch (L)</span>
        <span><i className="lg-dot" style={{ background: '#FF9100' }} />Burst (B)</span>
        <span><i className="lg-dot" style={{ background: '#26C6DA' }} />Float (F)</span>
        <span><i className="lg-dot" style={{ background: '#FFD600' }} />Landing (⬇)</span>
        <span><i className="lg-dot" style={{ background: '#00E676' }} />Latest telemetry</span>
      </div>
    </div>
  );
}

function MapCoords() {
  const [c, setC] = useState(null);
  useEffect(() => store.onMouseMove((ev) => setC(ev.latlng)), []);
  return c ? <div className="map-coords">{c.lat.toFixed(5)}°, {c.lng.toFixed(5)}°</div> : null;
}

export default function MissionMap({ scope, height = '100%', children }) {
  useEffect(() => { store.setLegend(scope, LEGEND[scope] || []); }, [scope]);
  const slot = useRef(null);
  const active = useWorkspaceActive();
  useEffect(() => {
    if (!active) return undefined;
    store.attach(slot.current);
    store.setScope(scope);
    const ro = new ResizeObserver(() => store.invalidate());
    ro.observe(slot.current);
    return () => ro.disconnect();
  }, [scope, active]);
  return (
    <div className="map-slot" ref={slot} style={{ height }}>
      <MapCoords />
      <MapLegend />
      {children}
    </div>
  );
}
