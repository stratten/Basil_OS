import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';

const hoisted = vi.hoisted(() => ({
  fetchGlobalSettings: vi.fn(),
  updateGlobalSettings: vi.fn(),
  target: { meetingId: null as string | null, isRecording: false },
  controller: {} as Record<string, unknown>,
}));

vi.mock('./companionApi', () => ({
  fetchGlobalSettings: hoisted.fetchGlobalSettings,
  updateGlobalSettings: hoisted.updateGlobalSettings,
}));
vi.mock('./useMeetingCompanion', () => ({
  useMeetingCompanion: () => ({ companion: hoisted.controller, meetingId: hoisted.target.meetingId, isRecording: hoisted.target.isRecording }),
}));

import { COMPANION_PANE_WIDTH, COMPANION_RAIL_WIDTH, COMPANION_TRANSITION_MS } from './companionLayout';
import { emptyTimelineState } from './companionReducer';
import { getCompanionView, resetCompanionViews, updateCompanionView } from './companionViewStore';
import { useEmbeddedCompanion } from './useEmbeddedCompanion';

const idleUi = { isViewingPastMeeting: false, companionApiPort: 8123 } as unknown as MeetingUIStateDTO;
const pastUi = { isViewingPastMeeting: true, companionApiPort: 8123 } as unknown as MeetingUIStateDTO;

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    state: { phase: 'ready', timeline: emptyTimelineState, status: { mode: 'active' } },
    isEnabled: false,
    setMode: vi.fn(async () => true),
    actionError: null,
    clearActionError: vi.fn(),
    enable: vi.fn(async () => true),
    disable: vi.fn(async () => true),
    ...overrides,
  };
}

function settings(autoEnable: boolean) {
  return { auto_enable: autoEnable, default_mode: 'active', next_focus: '', screen_share_note_dismissed: true };
}

beforeEach(() => {
  vi.clearAllMocks();
  hoisted.target.meetingId = null;
  hoisted.target.isRecording = false;
  hoisted.controller = makeController();
  hoisted.fetchGlobalSettings.mockResolvedValue(settings(false));
  hoisted.updateGlobalSettings.mockImplementation(async (_port: number, patch: { auto_enable?: boolean }) => settings(Boolean(patch.auto_enable)));
});

describe('useEmbeddedCompanion before a recording starts', () => {
  it('offers the switch with the Companion off and shows no pane', async () => {
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(hoisted.fetchGlobalSettings).toHaveBeenCalled());
    expect(result.current.switchProps).toMatchObject({ enabled: false, busy: false });
    expect(result.current.kind).toBeNull();
    expect(result.current.extent).toBe(0);
  });

  it('arms the Companion for the next recording and opens the setup pane', async () => {
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    await act(async () => {
      result.current.switchProps?.onChange(true);
    });
    expect(hoisted.updateGlobalSettings).toHaveBeenCalledWith(8123, { auto_enable: true });
    await waitFor(() => expect(result.current.switchProps?.enabled).toBe(true));
    expect(result.current.kind).toBe('setup');
    expect(result.current.expanded).toBe(true);
    expect(result.current.extent).toBe(COMPANION_PANE_WIDTH);
  });

  it('keeps the switch usable and explains a failed save instead of doing nothing', async () => {
    hoisted.updateGlobalSettings.mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    await act(async () => {
      result.current.switchProps?.onChange(true);
    });
    await waitFor(() => expect(result.current.switchProps?.error).toContain('could not be saved'));
    expect(result.current.switchProps?.enabled).toBe(false);
    expect(result.current.switchProps?.busy).toBe(false);
    act(() => result.current.switchProps?.onDismissError());
    expect(result.current.switchProps?.error).toBeNull();
  });

  it('reports a failed save even when the settings never loaded', async () => {
    hoisted.fetchGlobalSettings.mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await act(async () => {
      result.current.switchProps?.onChange(true);
    });
    await waitFor(() => expect(result.current.switchProps?.error).toContain('could not be saved'));
    expect(hoisted.updateGlobalSettings).not.toHaveBeenCalled();
  });

  it('collapses the setup pane to a rail, and switching the Companion on again reopens it', async () => {
    hoisted.fetchGlobalSettings.mockResolvedValue(settings(true));
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.expanded).toBe(true));
    act(() => result.current.hidePane());
    expect(result.current.kind).toBe('setup');
    expect(result.current.expanded).toBe(false);
    expect(result.current.hasRail).toBe(true);
    expect(result.current.extent).toBe(COMPANION_RAIL_WIDTH);
    act(() => result.current.showPane());
    expect(result.current.expanded).toBe(true);
    expect(result.current.hasRail).toBe(false);
  });

  it('keeps the setup content mounted until the close transition has finished', async () => {
    hoisted.fetchGlobalSettings.mockResolvedValue(settings(true));
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.renderedKind).toBe('setup'));
    vi.useFakeTimers();
    try {
      await act(async () => {
        result.current.switchProps?.onChange(false);
        await Promise.resolve();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.kind).toBeNull();
      expect(result.current.extent).toBe(0);
      expect(result.current.renderedKind).toBe('setup');
      await act(async () => {
        await vi.advanceTimersByTimeAsync(COMPANION_TRANSITION_MS + 60);
      });
      expect(result.current.renderedKind).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('has no switch while a past meeting is open', async () => {
    const { result } = renderHook(() => useEmbeddedCompanion(pastUi));
    await waitFor(() => expect(hoisted.fetchGlobalSettings).toHaveBeenCalled());
    expect(result.current.switchProps).toBeUndefined();
  });
});

describe('useEmbeddedCompanion while recording', () => {
  beforeEach(() => {
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
  });

  it('drives the live meeting, not the saved preference', async () => {
    hoisted.fetchGlobalSettings.mockResolvedValue(settings(true));
    const controller = makeController({ isEnabled: false });
    hoisted.controller = controller;
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    expect(result.current.switchProps?.enabled).toBe(false);
    expect(result.current.kind).toBeNull();
    await act(async () => {
      result.current.switchProps?.onChange(true);
    });
    expect(controller.enable).toHaveBeenCalledTimes(1);
    expect(hoisted.updateGlobalSettings).not.toHaveBeenCalled();
  });

  it('surfaces a failed enable beside the switch while the pane is hidden', async () => {
    hoisted.controller = makeController({ isEnabled: false, actionError: 'Companion enable failed (500)' });
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    expect(result.current.kind).toBeNull();
    expect(result.current.switchProps?.error).toBe('Companion enable failed (500)');
  });

  it('shows the recording pane once the Companion is on and leaves the error to the pane', async () => {
    hoisted.controller = makeController({ isEnabled: true, actionError: 'boom' });
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    expect(result.current.kind).toBe('recording');
    expect(result.current.expanded).toBe(true);
    expect(result.current.switchProps?.enabled).toBe(true);
    expect(result.current.switchProps?.error).toBeNull();
  });
});

describe('useEmbeddedCompanion mode choice', () => {
  it('saves the default mode for the next recording while armed and idle', async () => {
    hoisted.fetchGlobalSettings.mockResolvedValue(settings(true));
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.switchProps?.mode?.value).toBe('active'));
    await act(async () => {
      result.current.switchProps?.mode?.onChange('passive');
    });
    expect(hoisted.updateGlobalSettings).toHaveBeenCalledWith(8123, { default_mode: 'passive' });
  });

  it('changes the live meeting mode while recording', async () => {
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
    const controller = makeController({ isEnabled: true });
    hoisted.controller = controller;
    const { result } = renderHook(() => useEmbeddedCompanion(idleUi));
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    act(() => result.current.switchProps?.mode?.onChange('passive'));
    expect(controller.setMode).toHaveBeenCalledWith('passive');
    expect(hoisted.updateGlobalSettings).not.toHaveBeenCalled();
  });
});

describe('useEmbeddedCompanion when the meeting starts from the setup pane', () => {
  type Ui = MeetingUIStateDTO;
  const loading = () => makeController({ state: { phase: 'loading', timeline: emptyTimelineState, status: { mode: 'active' } } });

  async function startFromSetup(dismiss: boolean) {
    hoisted.fetchGlobalSettings.mockResolvedValue(settings(true));
    const hook = renderHook(() => useEmbeddedCompanion(idleUi as Ui));
    await waitFor(() => expect(hook.result.current.kind).toBe('setup'));
    if (dismiss) act(() => hook.result.current.hidePane());
    return hook;
  }

  it('keeps the column at the same width through the moment the new meeting is still loading', async () => {
    const { result, rerender } = await startFromSetup(false);
    const widths = [result.current.extent];
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
    hoisted.controller = loading();
    rerender();
    widths.push(result.current.extent);
    expect(result.current.kind).toBe('recording');
    rerender();
    widths.push(result.current.extent);
    hoisted.controller = makeController({ isEnabled: true });
    rerender();
    widths.push(result.current.extent);
    expect(widths).toEqual([COMPANION_PANE_WIDTH, COMPANION_PANE_WIDTH, COMPANION_PANE_WIDTH, COMPANION_PANE_WIDTH]);
    expect(result.current.expanded).toBe(true);
  });

  it('leaves a pane the reader tucked into the rail in the rail when the meeting starts', async () => {
    const { result, rerender } = await startFromSetup(true);
    expect(result.current.extent).toBe(COMPANION_RAIL_WIDTH);
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
    hoisted.controller = loading();
    rerender();
    expect(result.current.expanded).toBe(false);
    expect(result.current.extent).toBe(COMPANION_RAIL_WIDTH);
    hoisted.controller = makeController({ isEnabled: true });
    rerender();
    expect(result.current.expanded).toBe(false);
    expect(result.current.hasRail).toBe(true);
    expect(result.current.extent).toBe(COMPANION_RAIL_WIDTH);
  });

  it('does not hold the column open once the meeting has loaded without the Companion on', async () => {
    const { result, rerender } = await startFromSetup(false);
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
    hoisted.controller = makeController({ isEnabled: false });
    rerender();
    expect(result.current.kind).toBeNull();
    expect(result.current.extent).toBe(0);
  });

  it('opens a later, different meeting with its pane showing again', async () => {
    const { result, rerender } = await startFromSetup(true);
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
    hoisted.controller = makeController({ isEnabled: true });
    rerender();
    expect(result.current.expanded).toBe(false);
    hoisted.target.meetingId = 'live-2';
    rerender();
    expect(result.current.expanded).toBe(true);
  });
});

describe('useEmbeddedCompanion while the Companion is detached', () => {
  const detachedUi = { isViewingPastMeeting: false, companionApiPort: 8123, isCompanionWindowOpen: true } as unknown as MeetingUIStateDTO;
  const recording = () => {
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
    hoisted.controller = makeController({ isEnabled: true, actionError: 'boom' });
  };

  it('folds the open column to a thin rail that stands for the detached window', async () => {
    recording();
    const { result, rerender } = renderHook(({ ui }) => useEmbeddedCompanion(ui), { initialProps: { ui: idleUi } });
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    expect(result.current.expanded).toBe(true);
    expect(result.current.extent).toBe(COMPANION_PANE_WIDTH);

    rerender({ ui: detachedUi });
    expect(result.current.detached).toBe(true);
    expect(result.current.kind).toBe('recording');
    expect(result.current.expanded).toBe(false);
    expect(result.current.hasRail).toBe(true);
    expect(result.current.extent).toBe(COMPANION_RAIL_WIDTH);
    expect(result.current.hiddenBadge).toBeNull();
  });

  it('restores the column as it was the moment the window closes', async () => {
    recording();
    const { result, rerender } = renderHook(({ ui }) => useEmbeddedCompanion(ui), { initialProps: { ui: detachedUi } });
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    expect(result.current.extent).toBe(COMPANION_RAIL_WIDTH);
    rerender({ ui: idleUi });
    expect(result.current.detached).toBe(false);
    expect(result.current.expanded).toBe(true);
    expect(result.current.extent).toBe(COMPANION_PANE_WIDTH);
  });

  it('keeps a column the reader had tucked into the rail in the rail after the window closes', async () => {
    recording();
    const { result, rerender } = renderHook(({ ui }) => useEmbeddedCompanion(ui), { initialProps: { ui: idleUi } });
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    act(() => result.current.hidePane());
    expect(result.current.extent).toBe(COMPANION_RAIL_WIDTH);
    rerender({ ui: detachedUi });
    act(() => result.current.showPane());
    expect(result.current.expanded).toBe(false);
    rerender({ ui: idleUi });
    expect(result.current.expanded).toBe(true);
  });

  it('ignores a hide request while detached so closing the window restores the prior state', async () => {
    recording();
    const { result, rerender } = renderHook(({ ui }) => useEmbeddedCompanion(ui), { initialProps: { ui: detachedUi } });
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    act(() => result.current.hidePane());
    rerender({ ui: idleUi });
    expect(result.current.expanded).toBe(true);
  });

  it('shows no rail when there is no pane to fold', async () => {
    const { result } = renderHook(() => useEmbeddedCompanion(detachedUi));
    await waitFor(() => expect(hoisted.fetchGlobalSettings).toHaveBeenCalled());
    expect(result.current.kind).toBeNull();
    expect(result.current.detached).toBe(false);
    expect(result.current.extent).toBe(0);
  });

  it('does not report what arrived while detached as new once the window closes', async () => {
    resetCompanionViews();
    hoisted.target.meetingId = 'live-1';
    hoisted.target.isRecording = true;
    const row = (id: string, seq: number) => ({
      id, seq, kind: 'insight', text: id, confidence: 0.5, citations: [], no_source: false,
      transcript_range: { start: 0, end: 1, turn_ids: [] }, trigger: 'periodic', watch_id: null,
      truncated: false, pinned: false, dismissed: false,
    });
    const withItems = (items: unknown[]) =>
      makeController({ isEnabled: true, state: { phase: 'ready', baselineSeq: 1, timeline: { ...emptyTimelineState, items }, status: { mode: 'active' } } });
    hoisted.controller = withItems([row('a', 1)]);
    const { result, rerender } = renderHook(({ ui }) => useEmbeddedCompanion(ui), { initialProps: { ui: detachedUi } });
    await waitFor(() => expect(result.current.globalSettings.settings).not.toBeNull());
    act(() => updateCompanionView('live-1', { lastSeenSeq: 1 }));
    hoisted.controller = withItems([row('a', 1), row('b', 2), row('c', 3)]);
    rerender({ ui: detachedUi });
    expect(getCompanionView('live-1').lastSeenSeq).toBe(1);
    rerender({ ui: idleUi });
    expect(getCompanionView('live-1').lastSeenSeq).toBe(3);
    expect(result.current.hiddenBadge).toBeNull();
  });
});

