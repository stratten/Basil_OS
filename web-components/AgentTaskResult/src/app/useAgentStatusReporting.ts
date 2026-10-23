import { useEffect } from 'react';
import type { DisplayableAgentTask } from '../types';
import { reportAgentStatus } from '../services/bridge';
import { isInFlightAgentStatus } from './agentHydration';

interface UseAgentStatusReportingArgs {
  focusedAgent: DisplayableAgentTask | null;
  selectedScheduledAgentTaskId: string | null;
  createScheduledMode: boolean;
  /**
   * The focused task is open in its own detached window. That window reports
   * it as its focused task, so this window reports no focused task instead:
   * otherwise native code would expand this window when the detached task
   * completes and route follow-up shortcuts to a task this window only shows
   * a placeholder for.
   */
  focusedAgentDetached?: boolean;
}

export function useAgentStatusReporting({
  focusedAgent,
  selectedScheduledAgentTaskId,
  createScheduledMode,
  focusedAgentDetached = false,
}: UseAgentStatusReportingArgs): void {
  // Derive the reported values from the focused agent's *fields* (not its
  // object identity). The store mutates the AgentState in place on completion
  // (see storeCore.updateAgent), so the object reference is stable across a
  // status/result change. Depending on the object here would skip the effect
  // on in-place completion, leaving the native focused-row cache stale and
  // breaking follow-up detection until the user navigates away and back.
  // Depending on the primitive values re-fires the effect whenever the
  // reported state actually changes.
  const active = !!focusedAgent && !focusedAgentDetached && !selectedScheduledAgentTaskId && !createScheduledMode;

  const agentTaskId = active && focusedAgent
    ? (focusedAgent.rootTaskId || focusedAgent.agentTaskId)
    : null;
  const isProcessing = active && focusedAgent ? isInFlightAgentStatus(focusedAgent.status) : false;
  const hasResult = active && focusedAgent
    ? (!!focusedAgent.result || focusedAgent.status === 'completed' || focusedAgent.status === 'failed')
    : false;
  const isTerminal = active && focusedAgent
    ? (focusedAgent.status === 'completed' || focusedAgent.status === 'failed')
    : false;
  const supportsFollowUp = active ? (!isProcessing && hasResult) : false;

  useEffect(() => {
    reportAgentStatus(isProcessing, hasResult, isTerminal, agentTaskId, supportsFollowUp);
  }, [agentTaskId, isProcessing, hasResult, isTerminal, supportsFollowUp]);
}

