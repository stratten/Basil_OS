import type { CompanionAudit, CompanionAuditMark, CompanionAuditMoment } from './types';

const MOMENT_KINDS = new Set(['note', 'todo', 'agent_task', 'research']);
const SCOPES = new Set(['so_far', 'meeting']);
const MARKS = new Set(['agree', 'disagree']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function parseMoment(value: unknown): CompanionAuditMoment | null {
  if (!isRecord(value)) return null;
  if (typeof value.id !== 'string' || typeof value.why !== 'string' || typeof value.suggested_text !== 'string') return null;
  if (!finite(value.start) || !finite(value.end) || !finite(value.confidence)) return null;
  if (typeof value.kind !== 'string' || !MOMENT_KINDS.has(value.kind)) return null;
  const mark = typeof value.mark === 'string' && MARKS.has(value.mark) ? (value.mark as CompanionAuditMark) : null;
  return {
    id: value.id,
    start: value.start,
    end: value.end,
    kind: value.kind as CompanionAuditMoment['kind'],
    why: value.why,
    suggested_text: value.suggested_text,
    confidence: value.confidence,
    mark,
  };
}

/** Structural validation of one `audit` payload; returns null for anything the Python `AuditReport` model would reject, so a bad report never replaces a good one. */
export function parseCompanionAudit(value: unknown): CompanionAudit | null {
  if (!isRecord(value)) return null;
  if (typeof value.audit_id !== 'string' || typeof value.scope !== 'string' || !SCOPES.has(value.scope)) return null;
  const rawMoments = Array.isArray(value.moments) ? value.moments : [];
  const moments = rawMoments.map(parseMoment);
  if (moments.some((moment) => moment === null)) return null;
  return {
    audit_id: value.audit_id,
    scope: value.scope as CompanionAudit['scope'],
    summary: typeof value.summary === 'string' ? value.summary : '',
    moments: moments as CompanionAuditMoment[],
    evaluations: finite(value.evaluations) ? value.evaluations : 0,
    spoke: finite(value.spoke) ? value.spoke : 0,
    covered_until: finite(value.covered_until) ? value.covered_until : 0,
  };
}

const MARK_ACTIONS: Record<string, CompanionAuditMark | null> = { audit_agree: 'agree', audit_disagree: 'disagree', audit_clear: null };

/** Applies an `audit_agree`, `audit_disagree` or `audit_clear` feedback event to the matching finding; anything else leaves the audit as it is. */
export function applyAuditMark(audit: CompanionAudit | null, momentId: string, action: string): CompanionAudit | null {
  if (audit === null || !(action in MARK_ACTIONS)) return audit;
  const mark = MARK_ACTIONS[action];
  if (!audit.moments.some((moment) => moment.id === momentId)) return audit;
  return { ...audit, moments: audit.moments.map((moment) => (moment.id === momentId ? { ...moment, mark } : moment)) };
}
