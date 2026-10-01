import { useEffect, useRef, useState } from 'react';
import type { AgentOriginStatusSummary } from '../contracts';
import { getTodoAgentStatuses } from '../services/api';
import { basilBoardWebSocket } from '../services/websocket';

/** Live-updating map of To-Do id -> its most-relevant Agent Task status.
 * Seeds are already present on each `TodoItemSummary.agent_status` from the
 * workspace hydration response; this hook re-polls the lightweight
 * `/api/v1/todos/agent-status` endpoint (debounced 300ms) whenever a
 * WebSocket event carries an `agent_task_id`, since the originating To-Do
 * cannot be derived from the event alone. */
export default function useTodoListAgentStatus(
  todoIds: string[],
): Record<string, AgentOriginStatusSummary | null> {
  const [statuses, setStatuses] = useState<Record<string, AgentOriginStatusSummary | null>>({});
  const idsKey = todoIds.slice().sort().join(',');
  const debounceRef = useRef<number>();

  useEffect(() => {
    let canceled = false;
    const ids = idsKey ? idsKey.split(',') : [];

    const refresh = () => {
      if (ids.length === 0) {
        setStatuses({});
        return;
      }
      void getTodoAgentStatuses(ids)
        .then((result) => {
          if (canceled) return;
          setStatuses(result as Record<string, AgentOriginStatusSummary | null>);
        })
        .catch(() => {
          // Keep the last-known statuses; a failed live refresh should not blank the UI.
        });
    };

    refresh();

    const unsubscribe = basilBoardWebSocket.subscribe((event) => {
      if (typeof event.agent_task_id !== 'string') return;
      window.clearTimeout(debounceRef.current);
      debounceRef.current = window.setTimeout(refresh, 300);
    });

    return () => {
      canceled = true;
      window.clearTimeout(debounceRef.current);
      unsubscribe();
    };
  }, [idsKey]);

  return statuses;
}
