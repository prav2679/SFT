import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

describe('app smoke', () => {
  it('renders the shell without crashing', async () => {
    window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
    globalThis.ResizeObserver = class { observe() {} disconnect() {} };
    const M = { mission_id: 'M-1', mission_name: 'n', mode: 'LIVE', launch_latitude: -33.8, launch_longitude: 151.2, created_at: '2026-11-07T00:00:00Z',
      lifecycle_status: 'PRE-LAUNCH', active: false, config: {}, prediction_sets: [], telemetry: {} };
    const pt = (i) => ({ t: `2026-11-07T0${i}:00:00Z`, lat: -33.8 + i / 10, lon: 151.2 + i / 10, alt: i * 1000, phase: i === 2 ? 'burst' : 'ascent' });
    const FV = { versions: [], original: { summary: { burst: pt(2), landing: pt(4), float: null }, track: [0, 1, 2, 3, 4].map(pt) },
      actual: { points: [], latest: null, landing: null }, revised: { summary: null, track: [] }, comparison: {}, error_series: { original: [], revised: [], sufficient: false } };
    globalThis.fetch = vi.fn(async (url) => {
      const u = String(url);
      const body = u.endsWith('/api/missions') ? [M] : u.includes('/missions/M-1') ? M : u.includes('flight-view') ? FV
        : u.includes('history') ? { items: [], total: 0 } : u.includes('alerts') ? [] : u.includes('comparison') ? { available: false } : {};
      return { ok: true, text: async () => JSON.stringify(body) };
    });
    class WS { constructor() { setTimeout(() => this.onopen?.(), 0); } close() {} send() {} }
    globalThis.WebSocket = WS;
    const errors = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => errors.push(a.join(' ')));
    const App = (await import('../App')).default;
    const { container } = render(<App />);
    await waitFor(() => expect(container.querySelector('.topnav')).toBeTruthy());
    console.log('ERRORS:', errors.slice(0, 5).join('\n'));
    expect(container.querySelector('.workspace')).toBeTruthy();
    spy.mockRestore();
  });
});

describe('workspaces render after their defaults load (hook-order regression)', () => {
  it('Diurnal, Trajectory and the burst workspace re-render with loaded defaults without throwing', async () => {
    window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
    globalThis.ResizeObserver = class { observe() {} disconnect() {} };
    globalThis.WebSocket = class { close() {} send() {} };
    const burstDefaults = { parameters: { launch_altitude: 87, payload_mass: 5, ascent_rate: 6.7, burst_altitude: 30000 } };
    const diurnalDefaults = { balloon: { drag_coefficient: 0.45, envelope_mode: 'compliant' }, mission: { duration_hours: 24 } };
    globalThis.fetch = vi.fn(async (url) => {
      const u = String(url);
      const body = u.includes('diurnal/defaults') ? diurnalDefaults : u.includes('burst/defaults') ? burstDefaults
        : u.includes('engines') ? { sft: { available: true }, tawhiri: { available: false, message: 'Tawhiri engine unavailable' } }
        : u.endsWith('/api/missions') ? [] : u.includes('catalogue') ? {} : {};
      return { ok: true, text: async () => JSON.stringify(body) };
    });
    const errors = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => errors.push(a.join(' ')));
    const { AppProvider, WorkspaceActive } = await import('../context/AppContext');
    const { TelemetryProvider } = await import('../context/TelemetryContext');
    const pages = [(await import('../pages/Diurnal/DiurnalPage')).default, (await import('../pages/Trajectory/TrajectoryPage')).default,
      (await import('../pages/BurstTelemetry/BurstTelemetryPage')).default];
    for (const Page of pages) {
      const { container, unmount } = render(<AppProvider><TelemetryProvider><WorkspaceActive.Provider value><Page /></WorkspaceActive.Provider></TelemetryProvider></AppProvider>);
      await new Promise((r) => setTimeout(r, 150));              // let the defaults resolve and the page re-render
      expect(container.querySelector('.ws-header')).toBeTruthy();
      unmount();
    }
    spy.mockRestore();
    expect(errors.filter((e) => /hooks|Error:/i.test(e))).toEqual([]);
  });
});
