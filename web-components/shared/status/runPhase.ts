/** The one reading of an agent task's phase and settled outcome, shared by every window that draws a task: the result window, the sidebar, and the scheduled-run mini panel. */
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

/** The facts a run phase is read from; an agent task row, a task view model, and a scheduled-run event all supply them. */
export interface RunPhaseInput {
  status: string;
  isCanceled?: boolean;
  verificationStatus?: 'pending' | 'resolved';
  outcome?: string;
  errorMessage?: string;
  resultSeverity?: string;
  isStreaming?: boolean;
}

const SETTLED_STATUSES = new Set(['completed', 'failed', 'partial']);
// The window store spells the waiting status `awaitingInput`; the backend row and its events say `awaiting_user_input` or `needs_clarification`.
const AWAITING_STATUSES = new Set(['awaitingInput', 'awaiting_user_input', 'needs_clarification']);

function settledOutcome(task: RunPhaseInput): SettledOutcome {
  const outcome = task.outcome?.trim().toLowerCase() ?? '';
  if (outcome === 'completed_with_warnings') return 'partial';
  if (task.errorMessage) {
    return task.resultSeverity === 'warning' || outcome === 'partial' ? 'partial' : 'failed';
  }
  if (outcome === 'partial' || task.status === 'partial') return 'partial';
  // `failure` is the finalizer's spelling and `failed` the one scheduled-run events carry.
  if (task.status === 'failed' || outcome === 'failure' || outcome === 'failed') return 'failed';
  return 'success';
}

// One precedence for every surface: canceled, then in-flight work, then pending verification, then the settled outcome.
export function deriveRunPhase(task: RunPhaseInput): RunPhase {
  if (task.isCanceled || task.status === 'canceled') {
    return { kind: 'canceled', outcome: null, label: 'Canceled', isBusy: false, offersRecovery: true };
  }
  if (task.status === 'paused') {
    return { kind: 'paused', outcome: null, label: 'Paused', isBusy: false, offersRecovery: false };
  }
  if (AWAITING_STATUSES.has(task.status)) {
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
