// Mission history management: list, view, delete, clear completed, clear all (with extra confirmation).
import { useMemo, useState } from 'react';
import { useWS1 } from './BurstTelemetryPage';
import { ConfirmDialog, ErrorBox, Panel, Pill } from '../../components/Common/ui';
import { missionService } from '../../services/apiClient';
import { fmt, fmtInt, utc } from '../../utils/format';

export const summarise = (missions) => {
  const by = (s) => missions.filter((m) => m.lifecycle_status === s).length;
  return {
    total: missions.length, active: by('ACTIVE'), completed: by('COMPLETED'), aborted: by('ABORTED'), prelaunch: by('PRE-LAUNCH'),
    packets: missions.reduce((n, m) => n + (m.packet_count || 0), 0),
  };
};

export default function MissionHistory() {
  const { missions, missionId, setMissionId, refreshMissions, setSection } = useWS1();
  const [dialog, setDialog] = useState(null);     // { kind: 'delete'|'terminate'|'completed'|'all1'|'all2', mission? }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const stats = useMemo(() => summarise(missions), [missions]);
  const completedCount = missions.filter((m) => ['COMPLETED', 'ABORTED'].includes(m.lifecycle_status)).length;
  const deletableCount = missions.filter((m) => !m.active).length;
  const close = () => { if (!busy) setDialog(null); };

  const run = async (fn, message) => {
    setBusy(true); setError(null);
    try {
      const res = await fn();
      await refreshMissions();                       // list, selection and dashboard statistics refresh from the backend
      setNotice(typeof message === 'function' ? message(res) : message);
      setDialog(null);
    } catch (e) { setError(e); setDialog(null); } finally { setBusy(false); }
  };

  const view = (m) => { setMissionId(m.mission_id); setSection('tracking'); };
  const m = dialog?.mission;

  return (
    <div className="stack">
      <div className="stat-tiles" aria-label="Mission statistics">
        {[['Missions', stats.total], ['Active', stats.active], ['Completed', stats.completed], ['Aborted', stats.aborted],
          ['Pre-launch', stats.prelaunch], ['Telemetry packets', fmtInt(stats.packets)]].map(([k, v]) => (
          <div className="stat-tile" key={k}><b>{v}</b><small>{k}</small></div>
        ))}
      </div>
      <Panel title="Mission history" actions={(
        <>
          <button className="btn" disabled={!completedCount} onClick={() => setDialog({ kind: 'completed' })}>Clear Completed Missions</button>
          <button className="btn danger" disabled={!deletableCount} onClick={() => setDialog({ kind: 'all1' })}>Clear All Mission History</button>
        </>)}>
        <ErrorBox error={error} />
        {notice && <div className="alert-box ok" role="status">{notice}</div>}
        {!missions.length ? <div className="muted">No missions recorded.</div> : (
          <div className="table-wrap">
            <table className="hist">
              <thead><tr>
                <th>Mission ID</th><th>Name</th><th>Launch coordinates</th><th>Created (UTC)</th><th>Status</th><th>Type</th>
                <th>Last updated (UTC)</th><th>Actions</th>
              </tr></thead>
              <tbody>
                {missions.map((x) => (
                  <tr key={x.mission_id} className={x.mission_id === missionId ? 'selected' : ''}>
                    <td>{x.mission_id}</td>
                    <td>{x.mission_name}</td>
                    <td>{x.launch_latitude != null ? `${fmt(x.launch_latitude, 4)}°, ${fmt(x.launch_longitude, 4)}°` : 'N/A'}</td>
                    <td>{utc(x.created_at)}</td>
                    <td><Pill status={x.lifecycle_status}>{x.lifecycle_status}</Pill></td>
                    <td>{x.mission_type}</td>
                    <td>{utc(x.last_updated)}</td>
                    <td>
                      <div className="row-actions">
                        <button className="btn small" onClick={() => view(x)}>View Mission</button>
                        <button className="btn small danger" onClick={() => setDialog({ kind: x.active ? 'terminate' : 'delete', mission: x })}>Delete Mission</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="inline-note">Deleting a mission removes its telemetry, alerts and events, original and revised prediction versions and its
          re-forecast results. Shared weather datasets and stand-alone calculator results are never deleted. Active missions must be terminated first.</p>
      </Panel>

      <ConfirmDialog open={dialog?.kind === 'delete'} danger busy={busy} title="Delete mission?" confirmLabel="Delete Mission" onCancel={close}
        onConfirm={() => run(() => missionService.remove(m.mission_id), `Mission ${m.mission_id} deleted.`)}>
        <p>Permanently delete <b>{m?.mission_id}</b> ({m?.mission_name}) with all of its telemetry, alerts, events and prediction versions? This cannot be undone.</p>
      </ConfirmDialog>

      <ConfirmDialog open={dialog?.kind === 'terminate'} danger busy={busy} title="Mission is active" confirmLabel="Terminate Mission" onCancel={close}
        onConfirm={() => run(() => missionService.abort(m.mission_id), `Mission ${m.mission_id} terminated. It can now be deleted.`)}>
        <p><b>{m?.mission_id}</b> is active and cannot be deleted. Terminate it first (ground-segment abort; stops any simulation feed — no command is sent to the balloon),
          then delete it.</p>
      </ConfirmDialog>

      <ConfirmDialog open={dialog?.kind === 'completed'} danger busy={busy} title="Clear completed missions?" confirmLabel="Clear Completed" onCancel={close}
        onConfirm={() => run(() => missionService.clear('completed'), (r) => `Cleared ${r.deleted.length} completed mission(s)${r.skipped_active.length ? `; ${r.skipped_active.length} active mission(s) kept` : ''}.`)}>
        <p>Delete all <b>{completedCount}</b> completed / aborted mission(s) and everything recorded for them? Active and pre-launch missions are kept.</p>
      </ConfirmDialog>

      <ConfirmDialog open={dialog?.kind === 'all1'} danger busy={busy} title="Clear ALL mission history?" confirmLabel="Continue" onCancel={close}
        onConfirm={() => setDialog({ kind: 'all2' })}>
        <p>This deletes <b>{deletableCount}</b> mission(s) (every mission that is not active), including pre-launch missions, with all telemetry and prediction data. Active missions are never deleted.</p>
      </ConfirmDialog>
      <ConfirmDialog open={dialog?.kind === 'all2'} danger busy={busy} requireText="DELETE ALL" title="Final confirmation" confirmLabel="Clear All Mission History" onCancel={close}
        onConfirm={() => run(() => missionService.clear('all', true), (r) => `Cleared ${r.deleted.length} mission(s)${r.skipped_active.length ? `; ${r.skipped_active.length} active mission(s) kept` : ''}.`)}>
        <p>This cannot be undone.</p>
      </ConfirmDialog>
    </div>
  );
}
