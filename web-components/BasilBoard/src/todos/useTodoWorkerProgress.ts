import { useEffect, useRef, useState } from 'react';
import { getAgentTaskDetail } from '@agent-task/services/api';
import type { AgentTaskDetail } from '@agent-task/types';
import type { TodoWorkAttempt, WSEvent } from '../contracts';
import { basilBoardWebSocket } from '../services/websocket';

export interface TodoWorkerLiveState {
  detail?: AgentTaskDetail;
  latestActivity?: string;
}

const DETAIL_REFRESH_EVENTS = new Set([
  'agent_task_progress',
  'agent_progress_update',
  'dynamic_step_added',
  'dynamic_step_updated',
  'agent_task_step_detail',
  'agent_task_artifact',
  'agent_task_result',
  'agent_task_outcome_update',
  'agent_task_canceled',
]);

const TERMINAL_EVENTS = new Set([
  'agent_task_result',
  'agent_task_canceled',
  'agent_task_outcome_update',
]);

const ESCALATION_EVENTS = new Set([
  'execution_approval_request',
  'checkpoint_waiting',
  'agent_task_blocker_waiting',
]);

function latestActivityFromEvent(event: WSEvent): string | undefined {
  const candidates = [
    event.completion_message,
    event.description,
    event.step,
    event.message,
    event.details,
    event.status_text,
  ];
  return candidates.find((candidate): candidate is string => typeof candidate === 'string' && candidate.trim().length > 0);
}

function requiresUserIntervention(detail: AgentTaskDetail | undefined): boolean {
  return detail?.status === 'awaiting_user_input'
    || detail?.status === 'waiting_user_input'
    || detail?.status === 'needs_clarification';
}

function escalationKey(agentTaskId: string, event?: WSEvent, detail?: AgentTaskDetail): string | undefined {
  if (event && ESCALATION_EVENTS.has(event.event_type ?? '')) {
    const identity = event.attention_id ?? event.message ?? event.details ?? event.event_type;
    return `${agentTaskId}:event:${identity}`;
  }
  return requiresUserIntervention(detail) ? `${agentTaskId}:status:${detail?.status}` : undefined;
}

export default function useTodoWorkerProgress(
  attempts: TodoWorkAttempt[],
  onTerminalUpdate: () => void,
  onEscalate: (agentTaskId: string) => void,
): Record<string, TodoWorkerLiveState> {
  const [states, setStates] = useState<Record<string, TodoWorkerLiveState>>({});
  const attemptsKey = attempts.map((attempt) => attempt.agent_task_id).sort().join(',');
  const onTerminalUpdateRef = useRef(onTerminalUpdate);
  const onEscalateRef = useRef(onEscalate);
  const openedEscalationsRef = useRef(new Set<string>());

  onTerminalUpdateRef.current = onTerminalUpdate;
  onEscalateRef.current = onEscalate;

  useEffect(() => {
    const agentTaskIds = attempts.map((attempt) => attempt.agent_task_id);
    const agentTaskIdSet = new Set(agentTaskIds);
    let canceled = false;

    setStates((current) => Object.fromEntries(
      Object.entries(current).filter(([agentTaskId]) => agentTaskIdSet.has(agentTaskId)),
    ));

    const escalateIfNeeded = (agentTaskId: string, event?: WSEvent, detail?: AgentTaskDetail) => {
      const key = escalationKey(agentTaskId, event, detail);
      if (!key || openedEscalationsRef.current.has(key)) return;
      openedEscalationsRef.current.add(key);
      onEscalateRef.current(agentTaskId);
    };

    const hydrateAgentTask = (agentTaskId: string, event?: WSEvent) => {
      void getAgentTaskDetail(agentTaskId)
        .then((detail) => {
          if (canceled) return;
          setStates((current) => ({
            ...current,
            [agentTaskId]: {
              ...current[agentTaskId],
              detail,
            },
          }));
          if (requiresUserIntervention(detail)) {
            escalateIfNeeded(agentTaskId, undefined, detail);
          } else {
            openedEscalationsRef.current.delete(`${agentTaskId}:status:awaiting_user_input`);
            openedEscalationsRef.current.delete(`${agentTaskId}:status:waiting_user_input`);
            openedEscalationsRef.current.delete(`${agentTaskId}:status:needs_clarification`);
          }
          if (event && TERMINAL_EVENTS.has(event.event_type ?? '')) {
            onTerminalUpdateRef.current();
          }
        })
        .catch(() => {
          // The task may not be queryable during its first submission moment.
        });
    };

    for (const agentTaskId of agentTaskIds) {
      hydrateAgentTask(agentTaskId);
    }

    const unsubscribe = basilBoardWebSocket.subscribe((event) => {
      const agentTaskId = event.agent_task_id;
      if (typeof agentTaskId !== 'string' || !agentTaskIdSet.has(agentTaskId)) return;
      const latestActivity = latestActivityFromEvent(event);
      if (latestActivity) {
        setStates((current) => ({
          ...current,
          [agentTaskId]: {
            ...current[agentTaskId],
            latestActivity,
          },
        }));
      }
      escalateIfNeeded(agentTaskId, event);
      if (DETAIL_REFRESH_EVENTS.has(event.event_type ?? '')) {
        hydrateAgentTask(agentTaskId, event);
      }
    });
    const unsubscribeOnConnect = basilBoardWebSocket.onConnect(() => {
      for (const agentTaskId of agentTaskIds) {
        hydrateAgentTask(agentTaskId);
      }
    });

    return () => {
      canceled = true;
      unsubscribe();
      unsubscribeOnConnect();
    };
  }, [attemptsKey]);

  return states;
}
