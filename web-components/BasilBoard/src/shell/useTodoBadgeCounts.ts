import { useCallback, useEffect, useRef, useState } from 'react';
import type { TodoBadgeCounts } from '../contracts';
import { getTodoBadgeCounts } from '../services/api';
import { localTodayDateOnly } from '../todos/todoDates';
import { subscribeTodoCountsChanged } from '../todos/todoBadgeEvents';

export const TODO_BADGE_POLL_INTERVAL_MS = 60_000;

/**
 * Open-work counts for the rail badge beside the To-Dos icon. Fetches on mount, when the To-Do view reports a change, when the window regains focus or becomes visible, and on a slow poll while visible. A failed refresh keeps the last counts rather than blanking the badge.
 */
export function useTodoBadgeCounts(enabled: boolean): TodoBadgeCounts | null {
  const [counts, setCounts] = useState<TodoBadgeCounts | null>(null);
  const requestSequence = useRef(0);

  const refresh = useCallback(() => {
    const sequence = ++requestSequence.current;
    getTodoBadgeCounts(localTodayDateOnly())
      .then((next) => {
        if (sequence !== requestSequence.current) return;
        setCounts((previous) =>
          previous && previous.total === next.total && previous.due_today === next.due_today && previous.overdue === next.overdue
            ? previous
            : next,
        );
      })
      .catch((error) => {
        console.warn('[useTodoBadgeCounts] Badge counts could not be refreshed:', error);
      });
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'hidden') return;
      refresh();
    };
    refresh();
    const unsubscribe = subscribeTodoCountsChanged(refresh);
    window.addEventListener('focus', refreshWhenVisible);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    const interval = window.setInterval(refreshWhenVisible, TODO_BADGE_POLL_INTERVAL_MS);
    return () => {
      requestSequence.current += 1;
      unsubscribe();
      window.removeEventListener('focus', refreshWhenVisible);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
      window.clearInterval(interval);
    };
  }, [enabled, refresh]);

  return enabled ? counts : null;
}
