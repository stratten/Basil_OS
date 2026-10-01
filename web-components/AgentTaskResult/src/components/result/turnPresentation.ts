import type { ResultSeverity } from '../../types';

export type TurnStatus = 'success' | 'partial' | 'failed' | 'active';

export interface TurnStatusInput {
  status?: string;
  outcome?: string;
  errorMessage?: string;
  resultSeverity?: ResultSeverity;
}

const ACTIVE_STATUSES = new Set(['capturing', 'routing', 'processing', 'awaitingInput']);

export const TURN_STATUS_LABELS: Record<TurnStatus, string> = {
  success: 'Completed',
  partial: 'Partial result',
  failed: 'Failed',
  active: 'In progress',
};

// Precedence matches deriveAgentRunPresentation's terminalState so a turn label and its rail agree.
export function resolveTurnStatus({ status, outcome, errorMessage, resultSeverity }: TurnStatusInput): TurnStatus {
  const normalizedStatus = status?.trim() ?? '';
  const normalizedOutcome = outcome?.trim().toLowerCase() ?? '';
  if (ACTIVE_STATUSES.has(normalizedStatus)) return 'active';
  if (normalizedOutcome === 'partial' || normalizedOutcome === 'completed_with_warnings' || normalizedStatus === 'partial') {
    return 'partial';
  }
  if (normalizedStatus === 'failed' || normalizedStatus === 'canceled' || normalizedOutcome === 'failure') return 'failed';
  if (errorMessage) return resultSeverity === 'warning' ? 'partial' : 'failed';
  return 'success';
}
