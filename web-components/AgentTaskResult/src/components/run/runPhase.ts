import type { DisplayableAgentTask } from '../../types';

export type RunPhaseKind = 'working' | 'awaiting' | 'paused' | 'verifying' | 'settled' | 'canceled';
export type SettledOutcome = 'success' | 'partial' | 'failed';

export interface RunPhase {
  kind: RunPhaseKind;
  /** Only meaningful for `settled`; every other phase has no final outcome yet. */
  outcome: SettledOutcome | null;
  label: string;
  /** True while Basil is still doing work (the header bubble pulses purple). */
  isBusy: boolean;
  /** True when the user can be offered Retry / Continue / Run again. */
  offersRecovery: boolean;
}

export type RunPhaseInput = Pick<
  DisplayableAgentTask,
  'status' | 'isCanceled' | 'verificationStatus' | 'outcome' | 'errorMessage' | 'resultSeverity' | 'isStreaming'
>;

const SETTLED_STATUSES = new Set(['completed', 'failed', 'partial']);

function settledOutcome(task: RunPhaseInput): SettledOutcome {
  const outcome = task.outcome?.trim().toLowerCase() ?? '';
  if (outcome === 'completed_with_warnings') return 'success';
  if (task.errorMessage) {
    return task.resultSeverity === 'warning' || outcome === 'partial' ? 'partial' : 'failed';
  }
  if (outcome === 'partial' || task.status === 'partial') return 'partial';
  if (task.status === 'failed' || outcome === 'failure') return 'failed';
  return 'success';
}

// One precedence for every surface: canceled, then in-flight work, then pending verification, then the settled outcome.
export function deriveRunPhase(task: RunPhaseInput): RunPhase {
  if (task.isCanceled) {
    return { kind: 'canceled', outcome: null, label: 'Canceled', isBusy: false, offersRecovery: true };
  }
  if (task.status === 'paused') {
    return { kind: 'paused', outcome: null, label: 'Paused', isBusy: false, offersRecovery: false };
  }
  if (task.status === 'awaitingInput') {
    return { kind: 'awaiting', outcome: null, label: 'Needs attention', isBusy: false, offersRecovery: false };
  }
  if (task.status === 'capturing' || task.status === 'routing' || task.status === 'processing' || task.isStreaming) {
    return { kind: 'working', outcome: null, label: 'Working', isBusy: true, offersRecovery: false };
  }
  if (SETTLED_STATUSES.has(task.status) && task.verificationStatus === 'pending') {
    return { kind: 'verifying', outcome: null, label: 'Verifying the outcome', isBusy: true, offersRecovery: false };
  }
  const outcome = settledOutcome(task);
  return {
    kind: 'settled',
    outcome,
    label: outcome === 'partial' ? 'Partial result' : outcome === 'failed' ? "Couldn't complete" : 'Completed',
    isBusy: false,
    offersRecovery: outcome !== 'success',
  };
}

export function isActivityInCard(phase: RunPhase): boolean {
  return phase.kind === 'working'
    || phase.kind === 'awaiting'
    || phase.kind === 'paused'
    || phase.kind === 'verifying';
}

export function showsRunStatusCard(phase: RunPhase): boolean {
  return phase.kind !== 'settled' || phase.outcome !== 'success';
}
