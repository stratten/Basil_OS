import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { notifyTodoCountsChanged } from '../todos/todoBadgeEvents';
import { TODO_BADGE_POLL_INTERVAL_MS, useTodoBadgeCounts } from './useTodoBadgeCounts';

const apiMocks = vi.hoisted(() => ({
  getTodoBadgeCounts: vi.fn(),
}));

vi.mock('../services/api', () => apiMocks);

describe('useTodoBadgeCounts', () => {
  beforeEach(() => {
    apiMocks.getTodoBadgeCounts.mockReset();
    apiMocks.getTodoBadgeCounts.mockResolvedValue({ total: 4, due_today: 1, overdue: 2 });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('fetches with the local calendar day on mount', async () => {
    const { result } = renderHook(() => useTodoBadgeCounts(true));
    await waitFor(() => expect(result.current).toEqual({ total: 4, due_today: 1, overdue: 2 }));
    expect(apiMocks.getTodoBadgeCounts).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/));
  });

  it('does not fetch when disabled', () => {
    const { result } = renderHook(() => useTodoBadgeCounts(false));
    expect(result.current).toBeNull();
    expect(apiMocks.getTodoBadgeCounts).not.toHaveBeenCalled();
  });

  it('refreshes when the To-Do view reports a change', async () => {
    const { result } = renderHook(() => useTodoBadgeCounts(true));
    await waitFor(() => expect(result.current?.total).toBe(4));
    apiMocks.getTodoBadgeCounts.mockResolvedValue({ total: 5, due_today: 0, overdue: 0 });
    act(() => notifyTodoCountsChanged());
    await waitFor(() => expect(result.current).toEqual({ total: 5, due_today: 0, overdue: 0 }));
  });

  it('refreshes when the window regains focus', async () => {
    const { result } = renderHook(() => useTodoBadgeCounts(true));
    await waitFor(() => expect(result.current?.total).toBe(4));
    apiMocks.getTodoBadgeCounts.mockResolvedValue({ total: 9, due_today: 0, overdue: 0 });
    act(() => {
      window.dispatchEvent(new Event('focus'));
    });
    await waitFor(() => expect(result.current?.total).toBe(9));
  });

  it('keeps the last counts when a refresh fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { result } = renderHook(() => useTodoBadgeCounts(true));
    await waitFor(() => expect(result.current?.total).toBe(4));
    apiMocks.getTodoBadgeCounts.mockRejectedValue(new Error('offline'));
    act(() => notifyTodoCountsChanged());
    await waitFor(() => expect(warn).toHaveBeenCalled());
    expect(result.current).toEqual({ total: 4, due_today: 1, overdue: 2 });
    warn.mockRestore();
  });

  it('polls on the slow interval', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = renderHook(() => useTodoBadgeCounts(true));
    await waitFor(() => expect(result.current?.total).toBe(4));
    const callsBefore = apiMocks.getTodoBadgeCounts.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TODO_BADGE_POLL_INTERVAL_MS + 10);
    });
    expect(apiMocks.getTodoBadgeCounts.mock.calls.length).toBeGreaterThan(callsBefore);
  });
});
