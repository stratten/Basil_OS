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

function page(conversations: typeof alpha[], next_cursor: string | null = null) {
  return { conversations, has_more: next_cursor !== null, next_cursor };
}

describe('useConversationList filters', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.listConversationPage.mockReset();
    mocks.getConversationAgentStatuses.mockReset();
    mocks.getConversationAgentStatuses.mockResolvedValue({});
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function mountLoaded() {
    mocks.listConversationPage.mockResolvedValueOnce(page([alpha, beta]));
    const hook = renderHook(() => useConversationList());
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    return hook;
  }

  it('requests the unfiltered list exactly as before when no filter is set', async () => {
    await mountLoaded();
    expect(mocks.listConversationPage).toHaveBeenCalledTimes(1);
    expect(mocks.listConversationPage).toHaveBeenCalledWith({ query: undefined, limit: 30 });
  });

  it('refetches the first page with the filter after the debounce and keeps the old rows until it arrives', async () => {
    const { result } = await mountLoaded();
    mocks.listConversationPage.mockResolvedValueOnce(page([beta]));

    act(() => result.current.updateFilters({ agentWork: 'failed' }));
    expect(result.current.filtersActive).toBe(true);
    expect(result.current.activeFilterCount).toBe(1);
    expect(mocks.listConversationPage).toHaveBeenCalledTimes(1);
    expect(result.current.conversations.map((item) => item.id)).toEqual(['alpha', 'beta']);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(mocks.listConversationPage).toHaveBeenLastCalledWith({
      query: undefined,
      limit: 30,
      filters: { agent_work: 'failed' },
    });
    expect(result.current.conversations.map((item) => item.id)).toEqual(['beta']);
  });

  it('sends the filters together with the search text and the cursor when loading more', async () => {
    mocks.listConversationPage.mockResolvedValueOnce(page([alpha], 'cursor-1'));
    const { result } = renderHook(() => useConversationList());
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    mocks.listConversationPage.mockResolvedValueOnce(page([alpha], 'cursor-1'));
    act(() => result.current.updateFilters({ length: 'multi' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    mocks.listConversationPage.mockResolvedValueOnce(page([beta]));
    await act(async () => {
      await result.current.loadMore();
    });
    expect(mocks.listConversationPage).toHaveBeenLastCalledWith({
      query: undefined,
      cursor: 'cursor-1',
      limit: 30,
      filters: { length: 'multi' },
    });
  });

  it('applies the active filters to a typed search', async () => {
    const { result } = await mountLoaded();
    mocks.listConversationPage.mockResolvedValue(page([alpha]));
    act(() => result.current.updateFilters({ agentWork: 'none' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    act(() => result.current.onQueryChange('alpha'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(mocks.listConversationPage).toHaveBeenLastCalledWith({
      query: 'alpha',
      limit: 30,
      filters: { agent_work: 'none' },
    });
  });

  it('clears the filters and refetches the unfiltered list', async () => {
    const { result } = await mountLoaded();
    mocks.listConversationPage.mockResolvedValue(page([alpha, beta]));
    act(() => result.current.updateFilters({ agentWork: 'active' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    act(() => result.current.clearFilters());
    expect(result.current.filtersActive).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(mocks.listConversationPage).toHaveBeenLastCalledWith({ query: undefined, limit: 30 });
  });

  it('drops a stale page that was in flight when a filter changed', async () => {
    let resolveStale!: (value: ReturnType<typeof page>) => void;
    mocks.listConversationPage.mockResolvedValueOnce(page([alpha, beta], 'cursor-1'));
    const { result } = renderHook(() => useConversationList());
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    mocks.listConversationPage.mockReturnValueOnce(new Promise((resolve) => { resolveStale = resolve; }));
    let moreStarted!: Promise<void>;
    act(() => {
      moreStarted = result.current.loadMore();
    });
    mocks.listConversationPage.mockResolvedValueOnce(page([beta]));
    act(() => result.current.updateFilters({ agentWork: 'failed' }));
    await act(async () => {
      resolveStale(page([{ ...alpha, id: 'stale' }]));
      await moreStarted;
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(result.current.conversations.map((item) => item.id)).toEqual(['beta']);
  });

  it('keeps the filters when a background refresh runs', async () => {
    const { result } = await mountLoaded();
    mocks.listConversationPage.mockResolvedValue(page([beta]));
    act(() => result.current.updateFilters({ length: 'single' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    await act(async () => {
      await result.current.refresh();
    });
    expect(mocks.listConversationPage).toHaveBeenLastCalledWith({
      query: undefined,
      limit: 30,
      filters: { length: 'single' },
    });
  });
});
