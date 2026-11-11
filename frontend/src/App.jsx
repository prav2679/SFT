import { Component, useEffect, useState } from 'react';
import { AppProvider, useApp, WorkspaceActive } from './context/AppContext';
import { SplashScreen } from './components/Common/ui';
import { TelemetryProvider } from './context/TelemetryContext';
import TopNavigation from './navigation/TopNavigation';
import SettingsDrawer from './navigation/SettingsDrawer';
import BurstTelemetryPage from './pages/BurstTelemetry/BurstTelemetryPage';
import TrajectoryPage from './pages/Trajectory/TrajectoryPage';
import DiurnalPage from './pages/Diurnal/DiurnalPage';

function Workspaces() {
  const { workspace } = useApp();
  // All workspaces stay mounted (hidden when inactive) so their state, results and
  // map layers persist; the single shared map moves to the active workspace.
  const ws = [['burst', BurstTelemetryPage], ['trajectory', TrajectoryPage], ['diurnal', DiurnalPage]];
  return ws.map(([id, Page]) => (
    <WorkspaceActive.Provider key={id} value={workspace === id}>
      <div className="workspace" hidden={workspace !== id}><Page /></div>
    </WorkspaceActive.Provider>
  ));
}

/** Shows the error instead of a blank page if any component throws while rendering. */
class ErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" style={{ padding: 24, color: '#fff', background: '#000', minHeight: '100vh', fontFamily: 'sans-serif' }}>
        <h2>SFT Mission Control hit an error</h2>
        <pre style={{ whiteSpace: 'pre-wrap' }}>{String(this.state.error?.stack || this.state.error)}</pre>
        <button onClick={() => window.location.reload()}>Reload</button>
      </div>
    );
  }
}

function Shell() {
  const { booted } = useApp();
  const [minElapsed, setMinElapsed] = useState(false);
  useEffect(() => { const t = setTimeout(() => setMinElapsed(true), 900); return () => clearTimeout(t); }, []);
  const ready = booted && minElapsed;
  return (
    <>
      {!ready && <SplashScreen />}
      <TelemetryProvider>
        <TopNavigation />
        <main className="app-body"><Workspaces /></main>
        <SettingsDrawer />
      </TelemetryProvider>
    </>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppProvider>
        <Shell />
      </AppProvider>
    </ErrorBoundary>
  );
}
