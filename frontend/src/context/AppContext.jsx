import { createContext, useContext, useEffect, useState } from 'react';
import { systemService } from '../services/apiClient';

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

export function AppProvider({ children }) {
  const [theme, setTheme] = useState('dark');
  const [system, setSystem] = useState(null);
  const [backendUp, setBackendUp] = useState(true);
  const [booted, setBooted] = useState(false);   // first backend contact attempted (drives the loading screen)
  const [workspace, setWorkspace] = useState('burst');
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    let t;
    const tick = async () => {
      try { setSystem(await systemService.status()); setBackendUp(true); } catch { setBackendUp(false); }
      setBooted(true);
      t = setTimeout(tick, 5000);
    };
    tick();
    return () => clearTimeout(t);
  }, []);

  return (
    <Ctx.Provider value={{ theme, setTheme, system, backendUp, booted, workspace, setWorkspace, settingsOpen, setSettingsOpen }}>
      {children}
    </Ctx.Provider>
  );
}

export const WorkspaceActive = createContext(true);
export const useWorkspaceActive = () => useContext(WorkspaceActive);
