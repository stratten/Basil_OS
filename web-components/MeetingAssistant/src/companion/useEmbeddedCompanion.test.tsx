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
