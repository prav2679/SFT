import { describe, expect, it } from 'vitest';
import * as store from '../components/Map/mapStore';

describe('map store with real Leaflet', () => {
  it('draws a trajectory with arrows and markers, and can fit/zoom to it without throwing', () => {
    const ctx = new Proxy({}, { get: (t, k) => (k === 'canvas' ? {} : () => {}), set: () => true });
    HTMLCanvasElement.prototype.getContext = () => ctx;
    window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    const el = document.createElement('div');
    Object.defineProperty(el, 'clientWidth', { value: 800 }); Object.defineProperty(el, 'clientHeight', { value: 500 });
    document.body.appendChild(el);
    store.attach(el); store.setScope('ws1');
    const pts = Array.from({ length: 40 }, (_, i) => ({ lat: -33.8 + i / 50, lon: 151.2 + i / 40, alt: i * 500, t: `2026-11-07T00:${String(i).padStart(2, '0')}:00Z`, phase: 'ascent' }));
    store.setPolyline('ws1:original', 'ws1', pts, { color: '#2979FF', weight: 4.5, dashArray: '10 8' }, { legend: true, label: 'Original Prediction', colour: '#2979FF', dashed: true });
    store.setPolyline('ws1:original', 'ws1', pts.slice(0, 30), { color: '#2979FF', weight: 4.5 }, { legend: true, label: 'Original Prediction', colour: '#2979FF' });   // update path
    for (const kind of ['launch', 'burst', 'float', 'landing', 'latest']) store.setMarker(`m:${kind}`, 'ws1', pts[5], { kind, colour: '#FF9100', popup: kind });
    expect(() => store.fitTo(['ws1:original'])).not.toThrow();
    expect(store.legendEntries().length).toBeGreaterThan(0);
    store.removeLayer('ws1:original');
  });
});
