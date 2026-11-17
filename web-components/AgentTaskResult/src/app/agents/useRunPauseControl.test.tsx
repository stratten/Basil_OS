// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  pauseSession: vi.fn(),
  resumeSession: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  pauseSession: mocks.pauseSession,
  resumeSession: mocks.resumeSession,
}));

import { runPauseStateForStatus, useRunPauseControl, type RunPauseControl } from './useRunPauseControl';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let latest: RunPauseControl;

function Probe({ status, rootTaskId = 'root-1' }: { status: string; rootTaskId?: string }) {
  latest = useRunPauseControl({ agentTaskId: rootTaskId, rootTaskId, status });
  return null;
}

function mount(status: string, rootTaskId?: string) {
  act(() => root.render(<Probe status={status} rootTaskId={rootTaskId} />));
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  mocks.pauseSession.mockReset().mockResolvedValue({ success: true, status: 'pause_requested' });
  mocks.resumeSession.mockReset().mockResolvedValue({ success: true, status: 'resuming' });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('runPauseStateForStatus', () => {
  it('offers Pause while the task works, Resume while paused, and nothing otherwise', () => {
    expect(runPauseStateForStatus('processing')).toBe('running');
    expect(runPauseStateForStatus('routing')).toBe('running');
    expect(runPauseStateForStatus('capturing')).toBe('running');
    expect(runPauseStateForStatus('paused')).toBe('paused');
    expect(runPauseStateForStatus('awaitingInput')).toBeUndefined();
    expect(runPauseStateForStatus('completed')).toBeUndefined();
    expect(runPauseStateForStatus(undefined)).toBeUndefined();
  });
});

describe('useRunPauseControl', () => {
  it('pauses the current turn once and then waits for the pause to take effect', async () => {
    mount('processing');
    expect(latest.state).toBe('running');
    act(() => { latest.pause(); latest.pause(); });
    await flush();
    expect(mocks.pauseSession).toHaveBeenCalledTimes(1);
    expect(mocks.pauseSession).toHaveBeenCalledWith('root-1');
    expect(latest.isPausing).toBe(true);
  });

  it('clears the waiting state when the task reaches paused', async () => {
    mount('processing');
    act(() => latest.pause());
    await flush();
    expect(latest.isPausing).toBe(true);
    mount('paused');
    expect(latest.state).toBe('paused');
    expect(latest.isPausing).toBe(false);
  });

  it('resumes without a note', async () => {
    mount('paused');
    act(() => latest.resume());
    await flush();
    expect(mocks.resumeSession).toHaveBeenCalledTimes(1);
    expect(mocks.resumeSession).toHaveBeenCalledWith('root-1');
  });

  it('stays out of the waiting state and allows a retry when the pause request fails', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    mocks.pauseSession.mockRejectedValueOnce(new Error('offline'));
    mount('processing');
    act(() => latest.pause());
    await flush();
    expect(latest.isPausing).toBe(false);
    act(() => latest.pause());
    await flush();
    expect(mocks.pauseSession).toHaveBeenCalledTimes(2);
    expect(latest.isPausing).toBe(true);
    error.mockRestore();
  });
});
