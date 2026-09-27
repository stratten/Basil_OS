import { useEffect } from 'react';
import type { DisplayableAgentTask } from '../types';
import { reportAgentStatus } from '../services/bridge';
import { isInFlightAgentStatus } from './agentHydration';

interface UseAgentStatusReportingArgs {
  focusedAgent: DisplayableAgentTask | null;
  selectedScheduledAgentTaskId: string | null;
  createScheduledMode: boolean;
}

export function useAgentStatusReporting({
  focusedAgent,
  selectedScheduledAgentTaskId,
  createScheduledMode,
}: UseAgentStatusReportingArgs): void {
  // Derive the reported values from the focused agent's *fields* (not its
  // object identity). The store mutates the AgentState in place on completion
  // (see storeCore.updateAgent), so the object reference is stable across a
  // status/result change. Depending on the object here would skip the effect
  // on in-place completion, leaving the native focused-row cache stale and
  // breaking follow-up detection until the user navigates away and back.
  // Depending on the primitive values re-fires the effect whenever the
  // reported state actually changes.
  const active = !!focusedAgent && !selectedScheduledAgentTaskId && !createScheduledMode;

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

