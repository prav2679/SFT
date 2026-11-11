import { useEffect, useState } from 'react';
import { useApp } from '../context/AppContext';
import { useTelemetry } from '../context/TelemetryContext';
import { Logo, Pill } from '../components/Common/ui';

function UtcClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  return (
    <div className="nav-stat" aria-label="Coordinated universal time">
      <span className="utc">{now.toISOString().slice(11, 19)}Z</span>
      <small>{now.toISOString().slice(0, 10)} UTC</small>
    </div>
  );
}

const WORKSPACES = [
  { id: 'burst', label: 'Balloon Burst Calculator & Telemetry' },
  { id: 'trajectory', label: 'Forward & Reverse Trajectory' },
  { id: 'diurnal', label: 'Diurnal Effect Analysis' },
];

export default function TopNavigation() {
  const { workspace, setWorkspace, system, backendUp, theme, setTheme, setSettingsOpen } = useApp();
  const { mission, status } = useTelemetry();
  const wx = system?.weather?.overall;
  const sims = system?.simulations?.active ?? 0;
  const phase = status?.flight_phase || mission?.flight_phase;
  return (
    <header className="topnav">
      <div className="brand">
        <Logo />
        <div>
          <div className="brand-title">SFT BALLOON GNC MISSION CONTROL</div>
          <div className="brand-sub">SUSAN FUTURE TECHNOLOGY · Advanced Balloon Guidance, Navigation &amp; Control</div>
        </div>
      </div>
      <nav className="ws-tabs" aria-label="Workspaces">
        {WORKSPACES.map((w) => (
          <button key={w.id} className={`ws-tab ${workspace === w.id ? 'active' : ''}`} aria-current={workspace === w.id}
            onClick={() => setWorkspace(w.id)}>{w.label}</button>
        ))}
      </nav>
      <div className="nav-status">
        {!backendUp ? <Pill status="FAILED">BACKEND OFFLINE</Pill> : (
          <>
            <div className="nav-stat"><small>Mission</small>
              {mission ? <Pill status={phase === 'ABORTED' ? 'ABORTED' : status?.connection || 'DISCONNECTED'}
                title={`${mission.mission_id} — telemetry ${status?.connection || 'DISCONNECTED'}`}>{phase || '—'}</Pill> : <Pill status="NONE">NO MISSION</Pill>}
            </div>
            <div className="nav-stat"><small>Weather data</small>
              <Pill status={wx} title={system?.weather?.latest_valid_cycle ? `Latest valid cycle ${system.weather.latest_valid_cycle}` : 'No valid dataset'}>
                {wx === 'AVAILABLE' ? system.weather.covers_now[0] : wx === 'STALE' ? `STALE ${system.weather.latest_valid_cycle}` : wx?.replace(/_/g, ' ') || '—'}
              </Pill>
            </div>
            <div className="nav-stat"><small>Simulation</small>
              <Pill status={sims ? 'RUNNING' : 'IDLE'}>{sims ? `${sims} RUNNING` : 'IDLE'}</Pill>
            </div>
          </>
        )}
        <UtcClock />
        <button className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label="Settings" title="Settings">⚙</button>
        <button className="icon-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          aria-label="Toggle light or dark mode" title="Light/dark mode">{theme === 'dark' ? '☀' : '☾'}</button>
      </div>
    </header>
  );
}
