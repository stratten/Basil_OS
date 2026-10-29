// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { countActiveFilters, endOfLocalDayIso, startOfLocalDayIso } from './historyFilterDates';
import { useHistoryFilters } from './useHistoryFilters';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

interface Filters { status: string; text: string }
const EMPTY: Filters = { status: 'any', text: '' };
const hasActive = (filters: Filters) => filters.status !== 'any' || filters.text !== '';

type HookResult = ReturnType<typeof useHistoryFilters<Filters>>;

function mount(onRefresh: (filters: Filters) => void, refreshEnabled = true) {
  const result: { current: HookResult | null } = { current: null };
  function Harness() {
    result.current = useHistoryFilters<Filters>({ emptyFilters: EMPTY, hasActiveFilters: hasActive, refreshEnabled, onRefresh });
    return null;
  }
  const container = document.createElement('div');
  const root = createRoot(container);
  act(() => { root.render(<Harness />); });
  return { result, unmount: () => act(() => { root.unmount(); }) };
}

describe('history filter dates', () => {
  it('turns a local day into the first and last instants of that day', () => {
    const start = startOfLocalDayIso('2026-03-05');
    const end = endOfLocalDayIso('2026-03-05');
    expect(new Date(start!).getHours()).toBe(0);
    expect(new Date(end!).getHours()).toBe(23);
    expect(new Date(end!).getTime() - new Date(start!).getTime()).toBe(24 * 60 * 60 * 1000 - 1);
  });

  it('rejects malformed days', () => {
    expect(startOfLocalDayIso('03/05/2026')).toBeUndefined();
    expect(endOfLocalDayIso('')).toBeUndefined();
  });

  it('counts only the truthy conditions', () => {
    expect(countActiveFilters([null, '', false, 'x', 1])).toBe(2);
  });
});

describe('useHistoryFilters', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('does not refetch on mount and debounces a change into one refetch with the latest filters', () => {
    const onRefresh = vi.fn();
    const view = mount(onRefresh);
    vi.advanceTimersByTime(1000);
    expect(onRefresh).not.toHaveBeenCalled();

    act(() => { view.result.current!.updateFilters({ status: 'failed' }); });
    act(() => { vi.advanceTimersByTime(200); });
    act(() => { view.result.current!.updateFilters({ text: 'lisbon' }); });
    act(() => { vi.advanceTimersByTime(299); });
    expect(onRefresh).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1); });
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(onRefresh).toHaveBeenCalledWith({ status: 'failed', text: 'lisbon' });
    view.unmount();
  });

  it('clears to the empty filters and refetches once', () => {
    const onRefresh = vi.fn();
    const view = mount(onRefresh);
    act(() => { view.result.current!.updateFilters({ status: 'failed' }); });
    act(() => { vi.advanceTimersByTime(300); });
    onRefresh.mockClear();
    act(() => { view.result.current!.clearFilters(); });
    act(() => { vi.advanceTimersByTime(300); });
    expect(onRefresh).toHaveBeenCalledWith(EMPTY);
    view.unmount();
  });

  it('resets for a view switch without scheduling a refetch and collapses the panel', () => {
    const onRefresh = vi.fn();
    const view = mount(onRefresh);
    act(() => { view.result.current!.toggleFiltersExpanded(); });
    act(() => { view.result.current!.updateFilters({ status: 'failed' }); });
    act(() => { vi.advanceTimersByTime(300); });
    onRefresh.mockClear();
    act(() => { view.result.current!.resetForViewSwitch(); });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onRefresh).not.toHaveBeenCalled();
    expect(view.result.current!.filters).toEqual(EMPTY);
    expect(view.result.current!.filtersExpanded).toBe(false);
    view.unmount();
  });

  it('does not refetch while refresh is disabled', () => {
    const onRefresh = vi.fn();
    const view = mount(onRefresh, false);
    act(() => { view.result.current!.updateFilters({ status: 'failed' }); });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onRefresh).not.toHaveBeenCalled();
    view.unmount();
  });
});
