import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  beginRunningAgentCancellation,
  type RunningAgentCancellationStore,
} from './runningAgentCancellation';

vi.mock('../services/bridge', () => ({
  reportAgentTaskCancellationStage: vi.fn(),
}));

function makeStore(isProvisional = false) {
  const agent: { isCanceling?: boolean; isCanceled?: boolean } = {};
  const store: RunningAgentCancellationStore = {
    isTransientWithoutDurableData: vi.fn(() => isProvisional),
    markCanceling: vi.fn(() => {
      agent.isCanceling = true;
    }),
    markCancellationUnconfirmed: vi.fn(() => {
      agent.isCanceling = false;
    }),
    removeAgent: vi.fn(),
    getAgent: vi.fn(() => agent),
  };
  return { store, agent };
}

describe('running agent cancellation', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('uses the current turn and avoids native fallback after a fast REST acknowledgment', async () => {
    const { store } = makeStore();
    const notifyHost = vi.fn();
    const requestCancellation = vi.fn().mockResolvedValue({
      success: true,
      message: 'canceled',
      finalized_via_agent: false,
      agent_task_id: 'turn-2',
    });

    beginRunningAgentCancellation(
      store,
      'root-task',
      'turn-2',
      notifyHost,
      requestCancellation,
    );
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(350);

    expect(store.markCanceling).toHaveBeenCalledWith('root-task');
    expect(requestCancellation).toHaveBeenCalledWith('turn-2', 'User requested cancellation');
    expect(notifyHost).not.toHaveBeenCalled();
  });

  it('sends one native fallback when REST remains unresolved', async () => {
    const { store } = makeStore();
    const notifyHost = vi.fn();
    const requestCancellation = vi.fn(() => new Promise(() => {}));

    beginRunningAgentCancellation(store, 'root-task-2', 'turn-2', notifyHost, requestCancellation);
    await vi.advanceTimersByTimeAsync(349);
    expect(notifyHost).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);

    expect(notifyHost).toHaveBeenCalledTimes(1);
    expect(notifyHost).toHaveBeenCalledWith('turn-2');
    await vi.advanceTimersByTimeAsync(1000);
    expect(notifyHost).toHaveBeenCalledTimes(1);
    expect(requestCancellation).toHaveBeenCalledTimes(1);
  });

  it('falls back immediately after REST rejection', async () => {
    const { store } = makeStore();
    const notifyHost = vi.fn();
    const requestCancellation = vi.fn().mockRejectedValue(new Error('offline'));

    beginRunningAgentCancellation(store, 'root-task-3', 'turn-3', notifyHost, requestCancellation);
    await Promise.resolve();
    await Promise.resolve();

    expect(notifyHost).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(350);
    expect(notifyHost).toHaveBeenCalledTimes(1);
  });

  it('re-enables retry without marking a durable task terminal when confirmation times out', async () => {
    const { store } = makeStore();
    const requestCancellation = vi.fn().mockResolvedValue({
      success: true,
      message: 'canceled',
      finalized_via_agent: false,
      agent_task_id: 'turn-4',
    });

    beginRunningAgentCancellation(store, 'root-task-4', 'turn-4', vi.fn(), requestCancellation);
    await vi.advanceTimersByTimeAsync(5000);

    expect(store.markCancellationUnconfirmed).toHaveBeenCalledWith(
      'root-task-4',
      'Stop has not been confirmed',
    );
  });

  it('does not roll back a terminal WebSocket cancellation', async () => {
    const { store, agent } = makeStore();

    beginRunningAgentCancellation(
      store,
      'root-task-5',
      'turn-5',
      vi.fn(),
      vi.fn().mockResolvedValue({
        success: true,
        message: 'canceled',
        finalized_via_agent: false,
        agent_task_id: 'turn-5',
      }),
    );
    agent.isCanceling = false;
    agent.isCanceled = true;
    await vi.advanceTimersByTimeAsync(5000);

    expect(store.markCancellationUnconfirmed).not.toHaveBeenCalled();
  });

  it('removes a provisional row while still dispatching REST', () => {
    const { store } = makeStore(true);
    const requestCancellation = vi.fn(() => new Promise(() => {}));

    const wasProvisional = beginRunningAgentCancellation(
      store,
      'root-task-6',
      'turn-6',
      vi.fn(),
      requestCancellation,
    );

    expect(wasProvisional).toBe(true);
    expect(store.removeAgent).toHaveBeenCalledWith('root-task-6');
    expect(requestCancellation).toHaveBeenCalledWith('turn-6', 'User requested cancellation');
  });

  it('starts a fresh idempotent attempt after an unconfirmed timeout', async () => {
    const { store } = makeStore();
    const notifyHost = vi.fn();
    const requestCancellation = vi.fn(() => new Promise(() => {}));

    beginRunningAgentCancellation(
      store,
      'root-task-7',
      'turn-7',
      notifyHost,
      requestCancellation,
    );
    await vi.advanceTimersByTimeAsync(5000);
    expect(store.markCancellationUnconfirmed).toHaveBeenCalledTimes(1);

    beginRunningAgentCancellation(
      store,
      'root-task-7',
      'turn-7',
      notifyHost,
      requestCancellation,
    );
    await vi.advanceTimersByTimeAsync(350);

    expect(requestCancellation).toHaveBeenCalledTimes(2);
    expect(notifyHost).toHaveBeenCalledTimes(2);
    expect(store.markCanceling).toHaveBeenCalledTimes(2);
  });
});
