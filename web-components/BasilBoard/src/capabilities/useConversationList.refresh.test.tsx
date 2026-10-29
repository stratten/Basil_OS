import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationListItem } from '../contracts';
import { reconcileConversationFirstPage } from './conversationListReconcile';
import { useConversationList } from './useConversationList';

const mocks = vi.hoisted(() => ({
  listConversationPage: vi.fn(),
  getConversationAgentStatuses: vi.fn(),
}));

vi.mock('../services/api', () => ({
  listConversationPage: mocks.listConversationPage,
  getConversationAgentStatuses: mocks.getConversationAgentStatuses,
}));

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: { subscribe: vi.fn(() => () => {}) },
}));

const alpha: ConversationListItem = {
  id: 'alpha',
  title: 'Alpha',
  created_at: '2026-08-02T10:00:00Z',
  updated_at: '2026-08-02T10:00:00Z',
  message_count: 1,
};

const beta: ConversationListItem = {
  id: 'beta',
  title: 'Beta',
  created_at: '2026-08-02T09:00:00Z',
  updated_at: '2026-08-02T09:00:00Z',
  message_count: 2,
};

const gamma: ConversationListItem = {
  id: 'gamma',
  title: 'Gamma',
  created_at: '2026-08-02T08:00:00Z',
  updated_at: '2026-08-02T08:00:00Z',
  message_count: 3,
};

function page(conversations: ConversationListItem[], hasMore = false, nextCursor: string | null = null) {
  return { conversations, has_more: hasMore, next_cursor: nextCursor };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe('reconcileConversationFirstPage', () => {
  it('returns the current array when nothing changed', () => {
    const current = [alpha, beta];
    expect(reconcileConversationFirstPage(current, [{ ...alpha }, { ...beta }], false)).toBe(current);
  });

  it('keeps unchanged row identity and replaces changed rows', () => {
    const updatedBeta = { ...beta, updated_at: '2026-08-02T11:00:00Z', message_count: 3 };
    const next = reconcileConversationFirstPage([alpha, beta], [updatedBeta, { ...alpha }], false);
    expect(next[0]).toBe(updatedBeta);
    expect(next[1]).toBe(alpha);
  });

  it('drops rows that disappeared from a complete first page', () => {
    expect(reconcileConversationFirstPage([alpha, beta], [{ ...beta }], false)).toEqual([beta]);
  });

  it('keeps later-page rows older than the first page when more pages exist', () => {
    const next = reconcileConversationFirstPage([alpha, beta, gamma], [{ ...alpha }], true);
    expect(next).toEqual([alpha, beta, gamma]);
    expect(next[1]).toBe(beta);
  });

  it('treats an agent status change as a row change', () => {
    const withStatus: ConversationListItem = {
      ...alpha,
      agent_status: {
        agent_task_id: 'task-1',
        status: 'processing',
        result_severity: null,
        is_active: true,
        updated_at: '2026-08-02T10:00:00Z',
      },
    };
    expect(reconcileConversationFirstPage([alpha], [withStatus], false)[0]).toBe(withStatus);
  });
});

describe('useConversationList refresh', () => {
  beforeEach(() => {
    mocks.listConversationPage.mockReset();
    mocks.getConversationAgentStatuses.mockReset();
    mocks.getConversationAgentStatuses.mockResolvedValue({});
  });

  it('refreshes without a loading state and preserves unchanged row identity', async () => {
    mocks.listConversationPage
      .mockResolvedValueOnce(page([alpha, beta]))
      .mockResolvedValueOnce(page([{ ...alpha, message_count: 2, updated_at: '2026-08-02T12:00:00Z' }, { ...beta }]));
    const loadingStates: boolean[] = [];
    const { result } = renderHook(() => {
      const list = useConversationList();
      loadingStates.push(list.loading);
      return list;
    });
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));
    const previousBeta = result.current.conversations[1];
    const loadingStatesBeforeRefresh = loadingStates.length;

    await act(async () => {
      await result.current.refresh();
    });

    expect(loadingStates.slice(loadingStatesBeforeRefresh).every((loading) => loading === false)).toBe(true);
    expect(result.current.conversations[0].message_count).toBe(2);
    expect(result.current.conversations[1]).toBe(previousBeta);
  });

  it('keeps loaded later pages and the terminal cursor state when the first page still has more', async () => {
    mocks.listConversationPage
      .mockResolvedValueOnce(page([alpha], true, 'cursor-1'))
      .mockResolvedValueOnce(page([beta]))
      .mockResolvedValueOnce(page([{ ...alpha }], true, 'cursor-1'));
    const { result } = renderHook(() => useConversationList());
    await waitFor(() => expect(result.current.conversations).toEqual([alpha]));
    await act(async () => {
      await result.current.loadMore();
    });
    expect(result.current.hasMore).toBe(false);

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.conversations).toEqual([alpha, beta]);
    expect(result.current.hasMore).toBe(false);
  });

  it('keeps the visible list when a background refresh fails', async () => {
    mocks.listConversationPage
      .mockResolvedValueOnce(page([alpha, beta]))
      .mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useConversationList());
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.conversations).toEqual([alpha, beta]);
    expect(result.current.loadError).toBeUndefined();
  });

  it('skips a refresh while the first page is still loading', async () => {
    const firstPage = deferred<ReturnType<typeof page>>();
    mocks.listConversationPage.mockReturnValueOnce(firstPage.promise);
    const { result } = renderHook(() => useConversationList());
    await waitFor(() => expect(mocks.listConversationPage).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.refresh();
    });
    expect(mocks.listConversationPage).toHaveBeenCalledTimes(1);

    await act(async () => {
      firstPage.resolve(page([alpha]));
      await firstPage.promise;
    });
    expect(result.current.conversations).toEqual([alpha]);
  });

  it('removes a conversation locally', async () => {
    mocks.listConversationPage.mockResolvedValueOnce(page([alpha, beta]));
    const { result } = renderHook(() => useConversationList());
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    act(() => result.current.removeConversation('alpha'));

    expect(result.current.conversations).toEqual([beta]);
  });
});
