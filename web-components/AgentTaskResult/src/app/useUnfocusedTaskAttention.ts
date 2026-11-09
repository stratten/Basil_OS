import { useEffect, useRef } from 'react';
import type { AgentState } from '../types';
import { agentStore } from '../store/agentStore';
import { isInFlightAgentStatus } from './agentHydration';

type AttentionFields = Pick<
  AgentState,
  'status' | 'isCanceled' | 'showApprovalPrompt' | 'showTokenConnectPrompt' | 'showCheckpointPrompt' | 'rootTaskId' | 'agentTaskId'
>;

/** True while a task is waiting on the user: an approval, a token connection, a checkpoint, or its own request for input. */
export function taskNeedsInput(agent: Pick<AttentionFields, 'status' | 'showApprovalPrompt' | 'showTokenConnectPrompt' | 'showCheckpointPrompt'>): boolean {
  return agent.showApprovalPrompt === true ||
    agent.showTokenConnectPrompt === true ||
    agent.showCheckpointPrompt === true ||
    agent.status === 'awaitingInput';
}

/** A task another window owns reports through that window, and a canceled task is no longer anyone's business, so neither counts here. */
function isTrackedTask(agent: AttentionFields, detachedRootsElsewhere: ReadonlySet<string>): boolean {
  return !agent.isCanceled && !detachedRootsElsewhere.has(agent.rootTaskId || agent.agentTaskId);
}

/** True when the task is working or waiting on the user, which is what the collapsed header bubble has to show because the sidebar that normally shows it is hidden. */
export function taskNeedsCollapsedAttention(agent: AttentionFields, detachedRootsElsewhere: ReadonlySet<string>): boolean {
  return isTrackedTask(agent, detachedRootsElsewhere) &&
    (isInFlightAgentStatus(agent.status) || taskNeedsInput(agent));
}

interface TaskAttentionState {
  inFlight: boolean;
  needsInput: boolean;
}

interface UseUnfocusedTaskAttentionArgs {
  /** Watching is only useful while the widget is collapsed; the transitions are still tracked while it is not, so one that happened earlier is never replayed on collapse. */
  enabled: boolean;
  detachedRootsElsewhere: ReadonlySet<string>;
  /** A task other than the focused one has just started waiting on the user. */
  onNeedsInput: () => void;
  /** A task other than the focused one has just finished a turn, completed or failed. */
  onTurnCompleted: () => void;
}

/**
 * Reports transitions of every task except the focused one, so a collapsed widget can expand when a task it is not showing needs the user or finishes.
 * The focused task keeps its own paths (the sizing hook for input, the native status report for completion).
 * A task already waiting when watching starts, or first seen in that state, is only recorded: it is not a new request.
 */
export function useUnfocusedTaskAttention({
  enabled,
  detachedRootsElsewhere,
  onNeedsInput,
  onTurnCompleted,
}: UseUnfocusedTaskAttentionArgs): void {
  const enabledRef = useRef(enabled);
  const detachedRef = useRef(detachedRootsElsewhere);
  const onNeedsInputRef = useRef(onNeedsInput);
  const onTurnCompletedRef = useRef(onTurnCompleted);
  enabledRef.current = enabled;
  detachedRef.current = detachedRootsElsewhere;
  onNeedsInputRef.current = onNeedsInput;
  onTurnCompletedRef.current = onTurnCompleted;

  useEffect(() => {
    const previous = new Map<string, TaskAttentionState>();

    const observe = () => {
      const focusedId = agentStore.getSelectedAgentId();
      const seen = new Set<string>();
      let needsInputStarted = false;
      let turnCompleted = false;

      for (const agent of agentStore.getAllAgents()) {
        seen.add(agent.agentTaskId);
        const tracked = isTrackedTask(agent, detachedRef.current);
        const current: TaskAttentionState = {
          inFlight: tracked && isInFlightAgentStatus(agent.status),
          needsInput: tracked && taskNeedsInput(agent),
        };
        const before = previous.get(agent.agentTaskId);
        previous.set(agent.agentTaskId, current);
        if (!before || !tracked || agent.agentTaskId === focusedId) continue;
        if (current.needsInput && !before.needsInput) needsInputStarted = true;
        if (before.inFlight && !current.inFlight && (agent.status === 'completed' || agent.status === 'failed')) {
          turnCompleted = true;
        }
      }
      for (const id of previous.keys()) {
        if (!seen.has(id)) previous.delete(id);
      }

      if (!enabledRef.current) return;
      if (needsInputStarted) onNeedsInputRef.current();
      if (turnCompleted) onTurnCompletedRef.current();
    };

    observe();
    return agentStore.subscribe(observe);
  }, []);
}
