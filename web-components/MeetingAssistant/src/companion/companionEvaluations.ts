import type { TimelineEvent } from './types';

export type CompanionCandidateOutcome = 'kept' | 'confidence_floor' | 'duplicate' | 'over_cap' | 'empty';

export interface CompanionEvaluationCandidate {
  kind: string;
  text: string;
  confidence: number;
  outcome: CompanionCandidateOutcome | string;
}

/** One evaluation ledger event, read defensively so an event from a newer or older backend still renders. */
export interface CompanionEvaluationRecord {
  trigger: string;
  newLines: number;
  considered: string;
  candidates: CompanionEvaluationCandidate[];
  kept: number;
  latencyMs: number | null;
  error: string | null;
  discarded: string | null;
  gateWaits: Array<{ reason: string; count: number }>;
}

const TRIGGER_LABELS: Record<string, string> = {
  question: 'a question',
  topic_shift: 'a topic change',
  periodic: 'a routine check',
  watch: 'a watch',
};

const OUTCOME_LABELS: Record<string, string> = {
  kept: 'shown',
  confidence_floor: 'not confident enough',
  duplicate: 'repeated an earlier note',
  over_cap: 'over the limit for one check',
  empty: 'empty',
};

const WAIT_LABELS: Record<string, string> = {
  'few lines': 'waiting for more speech',
  pacing: 'pacing',
  waiting: 'nothing due yet',
  backchannel: 'only short replies',
  passive: 'passive mode',
  capacity: 'transcription behind',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseEvaluationEvent(event: TimelineEvent): CompanionEvaluationRecord {
  const payload = isRecord(event.payload) ? event.payload : {};
  const candidates = Array.isArray(payload.candidates)
    ? payload.candidates.filter(isRecord).map((candidate) => ({
        kind: typeof candidate.kind === 'string' ? candidate.kind : 'insight',
        text: typeof candidate.text === 'string' ? candidate.text : '',
        confidence: typeof candidate.confidence === 'number' && Number.isFinite(candidate.confidence) ? candidate.confidence : 0,
        outcome: typeof candidate.outcome === 'string' ? candidate.outcome : 'kept',
      }))
    : [];
  const waits = isRecord(payload.gate_waits)
    ? Object.entries(payload.gate_waits)
        .filter((entry): entry is [string, number] => typeof entry[1] === 'number' && entry[1] > 0)
        .map(([reason, count]) => ({ reason, count }))
    : [];
  return {
    trigger: typeof payload.trigger === 'string' ? payload.trigger : 'periodic',
    newLines: typeof payload.new_lines === 'number' ? payload.new_lines : 0,
    considered: typeof payload.considered === 'string' ? payload.considered : '',
    candidates,
    kept: typeof payload.kept === 'number' ? payload.kept : 0,
    latencyMs: typeof payload.latency_ms === 'number' && Number.isFinite(payload.latency_ms) ? Math.round(payload.latency_ms) : null,
    error: typeof payload.error === 'string' && payload.error !== '' ? payload.error : null,
    discarded: typeof payload.discarded === 'string' && payload.discarded !== '' ? payload.discarded : null,
    gateWaits: waits,
  };
}

export function triggerLabel(trigger: string): string {
  return TRIGGER_LABELS[trigger] ?? trigger;
}

export function outcomeLabel(outcome: string): string {
  return OUTCOME_LABELS[outcome] ?? outcome;
}

export function waitLabel(reason: string): string {
  return WAIT_LABELS[reason] ?? reason;
}

/** The one-line counter for the pane: "Considered 67 times, spoke 12". `spoke` is how many notes it showed. */
export function consideredCounterText(total: number, spoke: number): string {
  const times = `${total} ${total === 1 ? 'time' : 'times'}`;
  return `Considered ${times}, spoke ${spoke}`;
}

/** The headline of a Considered row: what the model said it weighed, or a plain fallback when it said nothing. */
export function consideredHeadline(record: CompanionEvaluationRecord): string {
  if (record.error !== null) return `Could not check this time (${record.error})`;
  if (record.considered !== '') return record.considered;
  return record.kept > 0 ? 'Wrote a note.' : 'Nothing worth adding.';
}
