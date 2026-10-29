import { useState } from 'react';
import { useHistoryFilters } from '@shared/historyFilters/useHistoryFilters';
import {
  EMPTY_SIDEBAR_FILTERS,
  hasActiveFilters,
  toFilterParams,
  type AgentTaskFilterParams,
  type SidebarFilters,
} from './sidebarFilters';

/** The `options` slice of a list or search request that carries the filters; empty when none is active, so an unfiltered request is unchanged. */
export function filterRequestOptions(filters: SidebarFilters): { filters?: AgentTaskFilterParams } {
  return hasActiveFilters(filters) ? { filters: toFilterParams(filters) } : {};
}

interface UseSidebarFiltersArgs {
  /** Whether a filter change should refetch right now (the list is on screen and loadable). */
  refreshEnabled: boolean;
  /** Refetches whatever list or search is showing, using the filters of the render that scheduled it. */
  onRefresh: (filters: SidebarFilters) => void;
}

/**
 * Task list filter state: the shared filter hook configured for Agent Task filters, plus the ids the backend returned for the current filters.
 * `resetForViewSwitch` clears the filters without scheduling a refetch, because the view change reloads the list itself.
 */
export function useSidebarFilters({ refreshEnabled, onRefresh }: UseSidebarFiltersArgs) {
  const shared = useHistoryFilters<SidebarFilters>({
    emptyFilters: EMPTY_SIDEBAR_FILTERS,
    hasActiveFilters,
    refreshEnabled,
    onRefresh,
  });
  // Ids the backend returned for the current filters, so a live task whose application the store cannot see still passes an application filter.
  const [filteredBackendIds, setFilteredBackendIds] = useState<ReadonlySet<string>>(() => new Set());
  return { ...shared, filteredBackendIds, setFilteredBackendIds };
}
