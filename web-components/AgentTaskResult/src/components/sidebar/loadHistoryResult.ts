import * as api from '../../services/api';
import type { DisplayableAgentTask } from '../../types';
import type { SearchFocus } from '@shared/search/searchFocusStore';
import { mapDetailToDisplayable } from './sidebarUtils';

export interface LoadedHistoryResult {
  displayable: DisplayableAgentTask;
  /** Present only when the search box had text and at least one turn of the chain matched it. */
  focus: Omit<SearchFocus, 'nonce'> | null;
}

/**
 * Load a finished chain for the result window. When the sidebar search box has text, the turns that matched it are
 * fetched alongside the detail so the window can open the right turn. The matches call is best-effort: if it fails the
 * chain still opens normally, because the search jump is a convenience and never a reason to refuse to show the task.
 */
export async function loadHistoryResult(rootTaskId: string, searchText: string): Promise<LoadedHistoryResult> {
  const query = searchText.trim();
  const [detail, matches] = await Promise.all([
    api.getAgentTaskDetail(rootTaskId),
    query
      ? api.getAgentTaskSearchMatches(rootTaskId, query).catch((err: unknown) => {
        console.warn('[Sidebar] Search-match lookup failed; opening the task without a jump:', err);
        return null;
      })
      : Promise.resolve(null),
  ]);
  const displayable = mapDetailToDisplayable(detail);
  const matchedTurnIds = matches?.matched_turn_ids ?? [];
  if (!matches || matchedTurnIds.length === 0) return { displayable, focus: null };
  return {
    displayable,
    focus: {
      scopeId: displayable.rootTaskId || displayable.agentTaskId,
      query,
      tokens: matches.tokens,
      matchedIds: matchedTurnIds,
    },
  };
}
