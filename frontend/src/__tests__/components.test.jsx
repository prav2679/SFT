import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const ctx = { missions: [], missionId: null, setMissionId: vi.fn(), refreshMissions: vi.fn(async () => {}), setSection: vi.fn() };
vi.mock('../pages/BurstTelemetry/BurstTelemetryPage', () => ({ useWS1: () => ctx }));
const api = vi.hoisted(() => ({ remove: vi.fn(async () => ({})), clear: vi.fn(async () => ({ deleted: ['M-1'], skipped_active: [] })), abort: vi.fn(async () => ({})) }));
vi.mock('../services/apiClient', async (orig) => ({ ...(await orig()), missionService: { ...api } }));

import MissionHistory, { summarise } from '../pages/BurstTelemetry/MissionHistory';
import { Logo, SplashScreen, WorkspaceHeader } from '../components/Common/ui';

const mk = (id, status, extra = {}) => ({ mission_id: id, mission_name: `name ${id}`, launch_latitude: -33.8688, launch_longitude: 151.2093,
  created_at: '2026-11-07T00:00:00Z', last_updated: '2026-11-07T01:00:00Z', lifecycle_status: status, active: status === 'ACTIVE',
  mission_type: 'Live - Latex burst', packet_count: 5, ...extra });

beforeEach(() => { Object.values(api).forEach((f) => f.mockClear()); ctx.refreshMissions.mockClear(); });

describe('MissionHistory', () => {
  it('lists every required column and statistics', () => {
    ctx.missions = [mk('M-1', 'COMPLETED'), mk('M-2', 'ACTIVE'), mk('M-3', 'PRE-LAUNCH')];
    render(<MissionHistory />);
    for (const h of ['Mission ID', 'Name', 'Launch coordinates', 'Created (UTC)', 'Status', 'Type', 'Last updated (UTC)', 'Actions']) expect(screen.getByText(h)).toBeTruthy();
    expect(screen.getByText('M-1')).toBeTruthy();
    expect(screen.getAllByText('-33.8688°, 151.2093°').length).toBe(3);
    expect(summarise(ctx.missions)).toMatchObject({ total: 3, active: 1, completed: 1, prelaunch: 1 });
  });
  it('asks for confirmation before deleting, then refreshes the list', async () => {
    ctx.missions = [mk('M-1', 'COMPLETED')];
    render(<MissionHistory />);
    fireEvent.click(screen.getByText('Delete Mission'));
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(api.remove).not.toHaveBeenCalled();                      // nothing happens before confirmation
    fireEvent.click(within(screen.getByRole('dialog')).getByText('Delete Mission'));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('M-1'));
    await waitFor(() => expect(ctx.refreshMissions).toHaveBeenCalled());
  });
  it('active missions must be terminated, not deleted', async () => {
    ctx.missions = [mk('M-2', 'ACTIVE')];
    render(<MissionHistory />);
    fireEvent.click(screen.getByText('Delete Mission'));
    expect(screen.getByText('Mission is active')).toBeTruthy();
    fireEvent.click(screen.getByText('Terminate Mission'));
    await waitFor(() => expect(api.abort).toHaveBeenCalledWith('M-2'));
    expect(api.remove).not.toHaveBeenCalled();
  });
  it('Clear All requires a second, typed confirmation', async () => {
    ctx.missions = [mk('M-1', 'COMPLETED')];
    render(<MissionHistory />);
    fireEvent.click(screen.getByText('Clear All Mission History'));
    fireEvent.click(screen.getByText('Continue'));
    const final = screen.getByText('Final confirmation').closest('.modal');
    const button = within(final).getByText('Clear All Mission History');
    expect(button.disabled).toBe(true);
    fireEvent.change(within(final).getByLabelText('confirmation phrase'), { target: { value: 'DELETE ALL' } });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(api.clear).toHaveBeenCalledWith('all', true));
  });
});

describe('SFT branding', () => {
  it('shows the supplied logo file unmodified inside a black badge, with company and app names', () => {
    const { container } = render(<><Logo /><WorkspaceHeader title="Diurnal Analysis" /><SplashScreen /></>);
    const imgs = [...container.querySelectorAll('img')];
    expect(imgs.length).toBe(3);
    imgs.forEach((i) => expect(i.getAttribute('src')).toBe('/assets/branding/sft-logo.jpg'));
    expect(container.querySelectorAll('.logo-badge').length).toBe(3);
    expect(screen.getAllByText(/SUSAN FUTURE TECHNOLOGY/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('SFT BALLOON GNC MISSION CONTROL')).toBeTruthy();
  });
});
