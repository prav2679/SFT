import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useTelemetry } from '../../context/TelemetryContext';
import { useWorkspaceActive } from '../../context/AppContext';
import { Tabs, WorkspaceHeader } from '../../components/Common/ui';
import { BalloonMarker, COLOURS, FitOnChange, PointMarker, TrajectoryPolyline, WindArrow } from '../../components/Map/MapLayers';
import { telemetryService } from '../../services/apiClient';
import useSimulation from '../../hooks/useSimulation';
import { track } from './telemetryModel';
import MissionOverview from './MissionOverview';
import BurstCalculator from './BurstCalculator';
import LiveTelemetry from './LiveTelemetry';
import FlightTracking from './FlightTracking';
import BalloonHealth from './BalloonHealth';
import FlightAnalytics from './FlightAnalytics';
import PredictionComparison from './PredictionComparison';
import AlertsEvents from './AlertsEvents';
import TelemetryHistory from './TelemetryHistory';
import MissionHistory from './MissionHistory';
import TelemetryUpdate from './TelemetryUpdate';

const WS1 = createContext(null);
export const useWS1 = () => useContext(WS1);
export const SCOPE = 'ws1';

export default function BurstTelemetryPage() {
  const [section, setSection] = useState('overview');
  const tel = useTelemetry();
  const active = useWorkspaceActive();
  const burst = useSimulation('burst');                      // burst calculator job (shared across sections)
  const [comparison, setComparison] = useState(null);
  const [flightView, setFlightView] = useState(null);        // original / actual / revised layers + comparison (backend)
  const [selectedVersion, setSelectedVersion] = useState(null);   // null = latest revised version
  const [layerVis] = useState({});
  const { packets, version, missionId, mission, alerts, predictionTick } = tel;

  const actual = useMemo(() => track(packets), [version]); // eslint-disable-line react-hooks/exhaustive-deps
  const latest = packets[packets.length - 1];
  const p = latest?.payload || {};

  const refreshFlightView = useCallback(async () => {
    if (!missionId) { setFlightView(null); return null; }
    try {
      const fv = await telemetryService.flightView(missionId, selectedVersion);
      setFlightView(fv);
      return fv;
    } catch { setFlightView(null); return null; }
  }, [missionId, selectedVersion]);
  useEffect(() => { setSelectedVersion(null); setFlightView(null); }, [missionId]);
  useEffect(() => {
    if (!missionId || !active) return undefined;
    refreshFlightView();
    const t = setInterval(refreshFlightView, 15000);
    return () => clearInterval(t);
  }, [missionId, active, refreshFlightView, predictionTick, mission?.prediction_sets?.length]);

  // Legacy single-prediction comparison (charts in "Prediction vs Actual"); always the immutable ORIGINAL by default.
  useEffect(() => {
    if (!missionId || !active) return undefined;
    const load = () => telemetryService.comparison(missionId).then(setComparison).catch(() => setComparison(null));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [missionId, active, predictionTick, mission?.prediction_sets?.length]);

  const orig = flightView?.original;
  const rev = flightView?.revised;
  const origTrack = orig?.track?.length ? orig.track : null;
  const revTrack = rev?.track?.length ? rev.track : null;
  const calcTraj = burst.result?.trajectory;
  const lastFix = actual[actual.length - 1];
  const launch = mission?.launch_latitude != null ? { lat: mission.launch_latitude, lon: mission.launch_longitude } : actual[0];
  const recovery = mission?.config?.recovery_location;
  const unack = alerts.filter((a) => !a.acknowledged && a.severity !== 'INFO').length;
  const oSum = orig?.summary, rSum = rev?.summary;
  const floatPt = (sum) => sum?.float?.start;

  const tabs = [
    { id: 'overview', label: 'Overview' }, { id: 'missions', label: 'Mission History' },
    { id: 'calculator', label: 'Burst Calculator' },
    { id: 'live', label: 'Live Telemetry' }, { id: 'update', label: 'Telemetry Update' },
    { id: 'tracking', label: 'Flight Tracking' },
    { id: 'health', label: 'Balloon Health' }, { id: 'analytics', label: 'Flight Analytics' },
    { id: 'comparison', label: 'Prediction vs Actual' }, { id: 'alerts', label: 'Alerts & Events', count: unack },
    { id: 'history', label: 'Telemetry History' },
  ];
  const Section = { overview: MissionOverview, missions: MissionHistory, calculator: BurstCalculator, live: LiveTelemetry,
    update: TelemetryUpdate, tracking: FlightTracking, health: BalloonHealth, analytics: FlightAnalytics,
    comparison: PredictionComparison, alerts: AlertsEvents, history: TelemetryHistory }[section];

  return (
    <WS1.Provider value={{ ...tel, burst, comparison, setComparison, actual, latest, setSection, layerVis,
      flightView, refreshFlightView, selectedVersion, setSelectedVersion }}>
      {/* Map layers for this workspace (kept mounted; the map itself is shared). Colours: see COLOURS. */}
      <TrajectoryPolyline id="ws1:original" scope={SCOPE} points={origTrack} colour={COLOURS.original} dashed label="Original Prediction" />
      <TrajectoryPolyline id="ws1:actual" scope={SCOPE} points={actual} colour={COLOURS.actual} label="Actual Flight Path" weight={4.5} />
      <TrajectoryPolyline id="ws1:revised" scope={SCOPE} points={revTrack} colour={COLOURS.revised} dashed label="Revised Prediction" />
      <TrajectoryPolyline id="ws1:calc" scope={SCOPE} points={calcTraj} colour={COLOURS.sft} dashed label="SFT Prediction (burst calculator)" />
      <PointMarker id="ws1:launch" scope={SCOPE} point={launch} kind="launch" colour={COLOURS.original} popup="Launch location" />
      <PointMarker id="ws1:oburst" scope={SCOPE} point={oSum?.burst} kind="burst" colour={COLOURS.original} popup="Original prediction — burst" />
      <PointMarker id="ws1:ofloat" scope={SCOPE} point={floatPt(oSum)} kind="float" colour={COLOURS.original} popup="Original prediction — float start" />
      <PointMarker id="ws1:olanding" scope={SCOPE} point={oSum?.landing} kind="landing" colour={COLOURS.original} popup="Original predicted landing" />
      <PointMarker id="ws1:rburst" scope={SCOPE} point={rSum?.burst} kind="burst" colour={COLOURS.revised} popup={`Revised prediction V${rSum?.version} — burst`} />
      <PointMarker id="ws1:rfloat" scope={SCOPE} point={floatPt(rSum)} kind="float" colour={COLOURS.revised} popup={`Revised prediction V${rSum?.version} — float start`} />
      <PointMarker id="ws1:rlanding" scope={SCOPE} point={rSum?.landing} kind="landing" colour={COLOURS.revised} popup={`Revised predicted landing (V${rSum?.version})`} />
      <PointMarker id="ws1:alanding" scope={SCOPE} point={flightView?.actual?.landing} kind="landing" colour={COLOURS.actual} popup="Actual landing" />
      <PointMarker id="ws1:cburst" scope={SCOPE} point={calcTraj?.find((q) => q.phase === 'burst')} kind="burst" colour={COLOURS.sft} popup="Calculator burst point" />
      <PointMarker id="ws1:recovery" scope={SCOPE} point={recovery} kind="recovery" popup="Recovery location" />
      <PointMarker id="ws1:latest" scope={SCOPE} point={lastFix} kind="latest" colour={COLOURS.actual}
        popup={lastFix ? `Latest telemetry — ${lastFix.alt?.toFixed(0)} m` : undefined} />
      <BalloonMarker id="ws1:balloon" scope={SCOPE} point={lastFix} heading={p.heading}
        colour={latest?.data_source === 'SIMULATED' ? '#b48cff' : '#3fd07a'}
        popup={lastFix ? `Balloon — ${lastFix.alt?.toFixed(0)} m` : undefined} />
      <FitOnChange keys={['ws1:actual', 'ws1:original']} dep={missionId && (actual.length > 1 || origTrack) ? `${missionId}:${origTrack?.length || 0}` : null} />
      <WindArrow id="ws1:wind" scope={SCOPE} point={lastFix} towardDeg={p.wind_direction_toward} />

      <WorkspaceHeader title="Balloon Burst Calculator & Live Telemetry" subtitle="Missions, burst prediction, live telemetry, telemetry-based re-forecasting" />
      {mission?.mode === 'SIMULATION' && <div className="sim-banner" role="status">SIMULATION MODE – NOT LIVE HARDWARE DATA</div>}
      <Tabs tabs={tabs} value={section} onChange={setSection} />
      <div className="ws-content"><Section /></div>
    </WS1.Provider>
  );
}
