import { useCallback, useEffect, useRef, useState } from 'react';

export const HISTORY_FILTER_REFRESH_DEBOUNCE_MS = 300;

interface UseHistoryFiltersArgs<F> {
  /** The unfiltered value, restored by Clear and by a view switch. */
  emptyFilters: F;
  /** Whether any condition of `filters` is narrowing the list. */
  hasActiveFilters: (filters: F) => boolean;
  /** Whether a filter change should refetch right now (the list is on screen and loadable). */
  refreshEnabled: boolean;
  /** Refetches whatever list or search is showing, using the filters of the render that scheduled it. */
  onRefresh: (filters: F) => void;
}

/**
 * History list filter state, its expanded flag, and the debounced refetch that follows a change.
 * `resetForViewSwitch` clears the filters without scheduling a refetch, because the view change reloads the list itself.
 */
export function useHistoryFilters<F extends object>({
  emptyFilters,
  hasActiveFilters,
  refreshEnabled,
  onRefresh,
}: UseHistoryFiltersArgs<F>) {
  const [filters, setFilters] = useState<F>(emptyFilters);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const skipNextRefreshRef = useRef(false);
  const isFirstRunRef = useRef(true);
  const latestRef = useRef({ refreshEnabled, onRefresh, filters, hasActiveFilters, emptyFilters });
  latestRef.current = { refreshEnabled, onRefresh, filters, hasActiveFilters, emptyFilters };

  const updateFilters = useCallback((change: Partial<F>) => {
    setFilters(current => ({ ...current, ...change }));
  }, []);
  const clearFilters = useCallback(() => setFilters(latestRef.current.emptyFilters), []);
  const toggleFiltersExpanded = useCallback(() => setFiltersExpanded(expanded => !expanded), []);

  const cancelPendingRefresh = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const resetForViewSwitch = useCallback(() => {
    cancelPendingRefresh();
    if (latestRef.current.hasActiveFilters(latestRef.current.filters)) skipNextRefreshRef.current = true;
    setFilters(latestRef.current.emptyFilters);
    setFiltersExpanded(false);
  }, [cancelPendingRefresh]);

  const filtersKey = JSON.stringify(filters);
  useEffect(() => {
    if (isFirstRunRef.current) {
      isFirstRunRef.current = false;
      return;
    }
    if (skipNextRefreshRef.current) {
      skipNextRefreshRef.current = false;
      return;
    }
    if (!latestRef.current.refreshEnabled) return;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      latestRef.current.onRefresh(latestRef.current.filters);
    }, HISTORY_FILTER_REFRESH_DEBOUNCE_MS);
    return cancelPendingRefresh;
  }, [filtersKey, cancelPendingRefresh]);

  return {
    filters,
    filtersExpanded,
    updateFilters,
    clearFilters,
    toggleFiltersExpanded,
    resetForViewSwitch,
  };
}
