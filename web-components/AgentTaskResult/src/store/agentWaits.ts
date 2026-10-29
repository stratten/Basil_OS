import { useSyncExternalStore } from 'react';
import { wsManager } from '../services/websocket';

/** A running Agent Task that is waiting before it checks again. */
export interface AgentWait {
  /** Absolute resume time in epoch milliseconds, so every client counts down to the same instant. */
  resumeAtMs: number;
  reason: string;
}

export type AgentWaitsByTask = Readonly<Record<string, AgentWait>>;

const EMPTY: AgentWaitsByTask = Object.freeze({});

let snapshot: AgentWaitsByTask = EMPTY;
let detach: (() => void) | null = null;
const listeners = new Set<() => void>();

function publish(next: AgentWaitsByTask) {
  snapshot = next;
  listeners.forEach(listener => listener());
}

function applyEvent(event: { event_type: string; [key: string]: unknown }) {
  const taskId = typeof event.wait_task_id === 'string' ? event.wait_task_id : '';
  if (!taskId) return;
  if (event.event_type === 'agent_wait_started') {
    const resumeAtMs = Number(event.resume_at_epoch_ms);
    if (!Number.isFinite(resumeAtMs)) return;
    publish({ ...snapshot, [taskId]: { resumeAtMs, reason: typeof event.reason === 'string' ? event.reason : '' } });
  } else if (event.event_type === 'agent_wait_finished' || event.event_type === 'agent_task_canceled') {
    if (!(taskId in snapshot)) return;
    const next = { ...snapshot };
    delete next[taskId];
    publish(next);
  }
}

function attach() {
  const stopEvents = wsManager.subscribe(event => {
    if (event.event_type === 'agent_wait_started' || event.event_type === 'agent_wait_finished') {
      applyEvent(event);
    } else if (event.event_type === 'agent_task_canceled' && typeof event.agent_task_id === 'string') {
      applyEvent({ ...event, wait_task_id: event.agent_task_id });
    }
  });
  // A wait that ended while the socket was down never delivers its finish event, so a reconnect drops every countdown rather than showing a stale one.
  const stopConnect = wsManager.onConnect(() => {
    if (snapshot !== EMPTY) publish(EMPTY);
  });
  detach = () => {
    stopEvents();
    stopConnect();
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) attach();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && detach) {
      detach();
      detach = null;
    }
  };
}

/** The in-run wait for one Agent Task, or undefined when it is not waiting. */
export function useAgentWait(agentTaskId: string | undefined): AgentWait | undefined {
  const waits = useSyncExternalStore(subscribe, () => snapshot, () => EMPTY);
  return agentTaskId ? waits[agentTaskId] : undefined;
}

/** Test helper: drop all cached state. */
export function resetAgentWaitsForTests() {
  snapshot = EMPTY;
}
