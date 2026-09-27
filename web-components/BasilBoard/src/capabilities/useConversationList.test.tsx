import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useConversationList } from './useConversationList';

const mocks = vi.hoisted(() => ({
  listConversationPage: vi.fn(),
  getConversationAgentStatuses: vi.fn(),
}));

vi.mock('../services/api', () => ({
  listConversationPage: mocks.listConversationPage,
  getConversationAgentStatuses: mocks.getConversationAgentStatuses,
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

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: { subscribe: websocketMocks.subscribe },
}));

const alpha = {
  id: 'alpha',
  title: 'Alpha',
  created_at: '2026-08-02T10:00:00Z',
  updated_at: '2026-08-02T10:00:00Z',
  message_count: 1,
};

const beta = {
  id: 'beta',
  title: 'Beta',
  created_at: '2026-08-02T09:00:00Z',
  updated_at: '2026-08-02T09:00:00Z',
  message_count: 2,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('useConversationList', () => {
  beforeEach(() => {
    mocks.listConversationPage.mockReset();
    mocks.getConversationAgentStatuses.mockReset();
    mocks.getConversationAgentStatuses.mockResolvedValue({});
    websocketMocks.handlers.splice(0);
    websocketMocks.subscribe.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('loads the initial page, appends the cursor page, and hides Load more at the terminal page', async () => {
    mocks.listConversationPage
      .mockResolvedValueOnce({ conversations: [alpha], has_more: true, next_cursor: 'cursor-1' })
      .mockResolvedValueOnce({ conversations: [beta], has_more: false, next_cursor: null });
    const { result } = renderHook(() => useConversationList());

    await waitFor(() => expect(result.current.conversations).toEqual([alpha]));
    expect(result.current.hasMore).toBe(true);

    await act(async () => {
      await result.current.loadMore();
    });

    expect(mocks.listConversationPage).toHaveBeenNthCalledWith(1, { limit: 30, query: undefined });
    expect(mocks.listConversationPage).toHaveBeenNthCalledWith(2, {
      cursor: 'cursor-1',
      limit: 30,
      query: undefined,
    });
    expect(result.current.conversations).toEqual([alpha, beta]);
    expect(result.current.hasMore).toBe(false);
  });

  it('invalidates a stale page immediately when the search changes', async () => {
    vi.useFakeTimers();
    try {
      const stale = deferred<{ conversations: typeof alpha[]; has_more: boolean; next_cursor: null }>();
      mocks.listConversationPage
        .mockReturnValueOnce(stale.promise)
        .mockResolvedValueOnce({ conversations: [beta], has_more: false, next_cursor: null });
      const { result } = renderHook(() => useConversationList());

      await act(async () => {
        await vi.runAllTimersAsync();
      });
      act(() => result.current.onQueryChange('Beta'));
      expect(result.current.conversations).toEqual([]);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });
      expect(result.current.conversations).toEqual([beta]);

      await act(async () => {
        stale.resolve({ conversations: [alpha], has_more: false, next_cursor: null });
        await stale.promise;
      });

      expect(result.current.conversations).toEqual([beta]);
      expect(mocks.listConversationPage).toHaveBeenLastCalledWith({ limit: 30, query: 'Beta' });
    } finally {
      vi.useRealTimers();
    }
  });

  it('preserves loaded conversations and retries the same cursor after an append failure', async () => {
    mocks.listConversationPage
      .mockResolvedValueOnce({ conversations: [alpha], has_more: true, next_cursor: 'cursor-1' })
      .mockRejectedValueOnce(new Error('Append failed'))
      .mockResolvedValueOnce({ conversations: [beta], has_more: false, next_cursor: null });
    const { result } = renderHook(() => useConversationList());

    await waitFor(() => expect(result.current.conversations).toEqual([alpha]));

    await act(async () => {
      await result.current.loadMore();
    });

    expect(result.current.conversations).toEqual([alpha]);
    expect(result.current.loadMoreError).toBe('Append failed');

    await act(async () => {
      await result.current.loadMore();
    });

    expect(mocks.listConversationPage).toHaveBeenNthCalledWith(3, {
      cursor: 'cursor-1',
      limit: 30,
      query: undefined,
    });
    expect(result.current.conversations).toEqual([alpha, beta]);
    expect(result.current.loadMoreError).toBeUndefined();
  });

  it('surfaces the agent_status already present on the initial page response unchanged', async () => {
    const alphaWithStatus = {
      ...alpha,
      agent_status: {
        agent_task_id: 'agent-task-1', status: 'processing', result_severity: null, is_active: true, updated_at: alpha.updated_at,
      },
    };
    mocks.listConversationPage.mockResolvedValueOnce({ conversations: [alphaWithStatus], has_more: false, next_cursor: null });

    const { result } = renderHook(() => useConversationList());

    await waitFor(() => expect(result.current.conversations).toEqual([alphaWithStatus]));
  });

  it('merges a debounced getConversationAgentStatuses refresh after a WebSocket event carrying agent_task_id', async () => {
    vi.useFakeTimers();
    try {
      mocks.listConversationPage.mockResolvedValueOnce({ conversations: [alpha], has_more: false, next_cursor: null });
      const { result } = renderHook(() => useConversationList());

      await act(async () => {
        await vi.runAllTimersAsync();
      });
      expect(result.current.conversations).toEqual([alpha]);
      expect(mocks.getConversationAgentStatuses).toHaveBeenCalledWith(['alpha']);

      const liveStatus = {
        agent_task_id: 'agent-task-2', status: 'processing', result_severity: null, is_active: true, updated_at: '2026-08-02T10:05:00Z',
      };
      mocks.getConversationAgentStatuses.mockResolvedValueOnce({ alpha: liveStatus });

      act(() => websocketMocks.emit({ agent_task_id: 'agent-task-2' }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(299);
      });
      expect(result.current.conversations).toEqual([alpha]);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
        await Promise.resolve();
      });
      expect(result.current.conversations).toEqual([{ ...alpha, agent_status: liveStatus }]);
    } finally {
      vi.useRealTimers();
    }
  });
});
