import { act, renderHook } from '@testing-library/react';
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

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: { subscribe: vi.fn(() => () => undefined) },
}));

const alpha = { id: 'alpha', title: 'Alpha', created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-02T10:00:00Z', message_count: 1 };
const beta = { id: 'beta', title: 'Beta', created_at: '2026-08-02T09:00:00Z', updated_at: '2026-08-02T09:00:00Z', message_count: 2 };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe('useConversationList search continuity', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.listConversationPage.mockReset();
    mocks.getConversationAgentStatuses.mockReset();
    mocks.getConversationAgentStatuses.mockResolvedValue({});
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('keeps the previous results visible until the new search page arrives', async () => {
    const searchPage = deferred<{ conversations: typeof alpha[]; has_more: boolean; next_cursor: null }>();
    mocks.listConversationPage
      .mockResolvedValueOnce({ conversations: [alpha], has_more: false, next_cursor: null })
      .mockReturnValueOnce(searchPage.promise);
    const { result } = renderHook(() => useConversationList());

    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.conversations).toEqual([alpha]);

    act(() => result.current.onQueryChange('Beta'));
    expect(result.current.conversations).toEqual([alpha]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(result.current.loading).toBe(true);
    expect(result.current.conversations).toEqual([alpha]);

    await act(async () => {
      searchPage.resolve({ conversations: [beta], has_more: false, next_cursor: null });
      await searchPage.promise;
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.conversations).toEqual([beta]);
  });
});
