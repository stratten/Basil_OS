// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WSEvent } from '../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const getPendingFollowUps = vi.fn();
vi.mock('../services/api', () => ({
  isApiReady: () => true,
  getPendingFollowUps: (...args: unknown[]) => getPendingFollowUps(...args),
}));

const wsHandlers: Array<(event: WSEvent) => void> = [];
const connectHandlers: Array<() => void> = [];
vi.mock('../services/websocket', () => ({
  wsManager: {
    subscribe: (handler: (event: WSEvent) => void) => {
      wsHandlers.push(handler);
      return () => wsHandlers.splice(wsHandlers.indexOf(handler), 1);
    },
    onConnect: (handler: () => void) => {
      connectHandlers.push(handler);
      return () => connectHandlers.splice(connectHandlers.indexOf(handler), 1);
    },
  },
}));

import { resetPendingFollowUpsForTests, usePendingFollowUps } from './pendingFollowUps';

function Probe() {
  const pending = usePendingFollowUps();
  return <div data-testid="probe">{JSON.stringify(pending)}</div>;
}

describe('usePendingFollowUps', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    resetPendingFollowUpsForTests();
    getPendingFollowUps.mockReset();
    getPendingFollowUps.mockResolvedValue({ follow_ups: [{ root_task_id: 'root-1', due_at: '2026-10-12T15:00:00+00:00' }] });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const probeText = () => container.querySelector('[data-testid="probe"]')?.textContent;

  it('loads the pending list on mount and refetches when a change event arrives', async () => {
    await act(async () => {
      root.render(<Probe />);
    });
    expect(probeText()).toBe('{"root-1":"2026-10-12T15:00:00+00:00"}');

    getPendingFollowUps.mockResolvedValue({ follow_ups: [] });
    await act(async () => {
      wsHandlers.forEach(handler => handler({ event_type: 'agent_task_follow_up_changed', root_task_id: 'root-1' } as WSEvent));
    });
    expect(probeText()).toBe('{}');
  });

  it('ignores unrelated events and refetches after a reconnect', async () => {
    await act(async () => {
      root.render(<Probe />);
    });
    getPendingFollowUps.mockClear();

    await act(async () => {
      wsHandlers.forEach(handler => handler({ event_type: 'agent_task_progress', agent_task_id: 'a' } as WSEvent));
    });
    expect(getPendingFollowUps).not.toHaveBeenCalled();

    await act(async () => {
      connectHandlers.forEach(handler => handler());
    });
    expect(getPendingFollowUps).toHaveBeenCalledTimes(1);
  });

  it('keeps the last known list when a refresh fails', async () => {
    await act(async () => {
      root.render(<Probe />);
    });
    getPendingFollowUps.mockRejectedValue(new Error('offline'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    await act(async () => {
      wsHandlers.forEach(handler => handler({ event_type: 'agent_task_follow_up_changed' } as WSEvent));
    });
    expect(probeText()).toBe('{"root-1":"2026-10-12T15:00:00+00:00"}');
    warn.mockRestore();
  });

  it('detaches its websocket listeners when the last consumer unmounts', async () => {
    await act(async () => {
      root.render(<Probe />);
    });
    expect(wsHandlers.length).toBe(1);
    act(() => root.render(<div />));
    expect(wsHandlers.length).toBe(0);
    expect(connectHandlers.length).toBe(0);
  });
});
