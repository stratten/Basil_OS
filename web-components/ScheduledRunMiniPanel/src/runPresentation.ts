import { deriveRunPhase, type RunPhase } from '@shared/runPhase';
import type { MiniPanelRow } from './types';

// The row's agent task status, with the approval flag taking priority because an approval request reaches the panel before the stored task status reads as waiting.
function rowTaskStatus(row: MiniPanelRow): string {
  if (row.awaitingInput && row.status === 'running') return 'awaitingInput';
  return row.taskStatus ?? 'processing';
}

/** A scheduled run is an ordinary agent task, so its row is read with the same phase logic every other window uses. */
export function phaseOfRow(row: MiniPanelRow): RunPhase {
  return deriveRunPhase({
    status: rowTaskStatus(row),
    verificationStatus: row.verificationStatus,
    outcome: row.outcome,
  });
}

/** The status-dot class: working and verifying share the pulsing dot, and every settled outcome keeps the color it has elsewhere. */
export function dotClassOfPhase(phase: RunPhase): string {
  switch (phase.kind) {
    case 'working':
    case 'verifying':
      return 'running';
    case 'awaiting':
      return 'needs-input';
    case 'paused':
      return 'paused';
    case 'canceled':
      return 'canceled';
    case 'settled':
      if (phase.outcome === 'partial') return 'partial outcome-partial-mark';
      return phase.outcome === 'failed' ? 'failed' : 'completed';
  }
}

/** Text under the title: the live step while working, otherwise the phase's own label. */
export function stepTextOfRow(row: MiniPanelRow, phase: RunPhase): string {
  switch (phase.kind) {
    case 'working':
      return row.currentStep;
    case 'awaiting':
      return 'Needs your approval — click to review';
    default:
      return phase.label;
  }
}

/**
 * What a ``scheduled_agent_task_run_completed`` event changes on its row. The run ends with the agent task's own status and
 * outcome. An older backend sends only the run status, which then stands in for the task status.
 */
export function finishedRowPatch(event: Record<string, unknown>): Partial<MiniPanelRow> {
  const verification = event.verification_status;
  const taskStatus = event.agent_task_status;
  return {
    status: 'finished',
    taskStatus: typeof taskStatus === 'string' ? taskStatus : event.status === 'completed' ? 'completed' : 'failed',
    outcome: typeof event.outcome === 'string' ? event.outcome : undefined,
    verificationStatus: verification === 'pending' || verification === 'resolved' ? verification : undefined,
    awaitingInput: false,
    ...(typeof event.agent_task_id === 'string' ? { agentTaskId: event.agent_task_id } : {}),
  };
}

/** A row that ended cleanly can leave quickly; anything that needs a look stays longer. */
export function rowEndedCleanly(row: MiniPanelRow): boolean {
  const phase = phaseOfRow(row);
  return phase.kind === 'settled' && phase.outcome === 'success';
}
