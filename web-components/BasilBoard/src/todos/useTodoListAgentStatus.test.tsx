import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import useTodoListAgentStatus from './useTodoListAgentStatus';

const apiMocks = vi.hoisted(() => ({
  getTodoAgentStatuses: vi.fn(),
}));
const websocketMocks = vi.hoisted(() => {
  const handlers: Array<(event: { agent_task_id?: string }) => void> = [];
  return {
    handlers,
    emit(event: { agent_task_id?: string }) {
      for (const handler of [...handlers]) handler(event);
    },
    subscribe: vi.fn((handler: (event: { agent_task_id?: string }) => void) => {
      handlers.push(handler);
      return () => {
        const index = handlers.indexOf(handler);
        if (index !== -1) handlers.splice(index, 1);
      };
    }),
  };
});

vi.mock('../services/api', () => apiMocks);
vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: { subscribe: websocketMocks.subscribe },
}));

describe('useTodoListAgentStatus', () => {
  beforeEach(() => {
    apiMocks.getTodoAgentStatuses.mockReset();
    apiMocks.getTodoAgentStatuses.mockResolvedValue({});
    websocketMocks.handlers.splice(0);
    websocketMocks.subscribe.mockClear();
  });

  it('fetches statuses for the current id set on mount', async () => {
    apiMocks.getTodoAgentStatuses.mockResolvedValue({
      't1': { agent_task_id: 'a1', status: 'processing', result_severity: null, is_active: true, updated_at: '2026-01-01T00:00:00Z' },
    });

    const { result } = renderHook(() => useTodoListAgentStatus(['t1', 't2']));

    await waitFor(() => expect(apiMocks.getTodoAgentStatuses).toHaveBeenCalledWith(['t1', 't2']));
    await waitFor(() => expect(result.current.t1?.status).toBe('processing'));
    expect(result.current.t2).toBeUndefined();
  });

  it('returns an empty map without calling the API for an empty id set', async () => {
    const { result } = renderHook(() => useTodoListAgentStatus([]));

    expect(apiMocks.getTodoAgentStatuses).not.toHaveBeenCalled();
    expect(result.current).toEqual({});
  });

  it('debounces a re-fetch triggered by a WebSocket event carrying agent_task_id', async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useTodoListAgentStatus(['t1']));

      await act(async () => {
        await vi.runAllTimersAsync();
      });
      expect(apiMocks.getTodoAgentStatuses).toHaveBeenCalledTimes(1);

      apiMocks.getTodoAgentStatuses.mockResolvedValueOnce({
        t1: { agent_task_id: 'a2', status: 'completed', result_severity: 'success', is_active: false, updated_at: '2026-01-01T00:05:00Z' },
      });

      act(() => websocketMocks.emit({ agent_task_id: 'a2' }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(299);
      });
      expect(apiMocks.getTodoAgentStatuses).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
        await Promise.resolve();
      });
      expect(apiMocks.getTodoAgentStatuses).toHaveBeenCalledTimes(2);
      expect(result.current.t1?.status).toBe('completed');
    } finally {
      vi.useRealTimers();
    }
  });

  it('ignores WebSocket events with no agent_task_id', async () => {
    vi.useFakeTimers();
    try {
      renderHook(() => useTodoListAgentStatus(['t1']));
      await act(async () => {
        await vi.runAllTimersAsync();
      });
      expect(apiMocks.getTodoAgentStatuses).toHaveBeenCalledTimes(1);

      act(() => websocketMocks.emit({}));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
      expect(apiMocks.getTodoAgentStatuses).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
