import type { CompanionAudit, CompanionAuditMoment, CompanionItem } from './types';

export const AUDIT_KIND_LABELS: Record<CompanionAuditMoment['kind'], string> = {
  note: 'Note',
  todo: 'To-do',
  agent_task: 'Agent task',
  research: 'Research',
};

/** The line above the findings: what the audit looked at, so "none found" is a result and not a blank. */
export function auditCounterText(audit: CompanionAudit): string {
  const times = `${audit.evaluations} ${audit.evaluations === 1 ? 'time' : 'times'}`;
  const misses = audit.moments.length === 0 ? 'no missed moments found' : `${audit.moments.length} possible ${audit.moments.length === 1 ? 'miss' : 'misses'}`;
  return `Checked ${times}, spoke ${audit.spoke}, ${misses}`;
}

export function auditButtonLabel(options: { auditing: boolean; isRecording: boolean; hasAudit: boolean }): string {
  if (options.auditing) return 'Auditing…';
  if (options.hasAudit) return 'Audit again';
  return options.isRecording ? 'Audit so far' : 'Audit this meeting';
}

/** A finding presented as a note, so it can use the transcript link and the to-do and agent buttons that notes use. */
export function momentAsItem(moment: CompanionAuditMoment): CompanionItem {
  return {
    id: moment.id,
    seq: 0,
    kind: 'suggestion',
    text: moment.suggested_text,
    confidence: moment.confidence,
    citations: [],
    no_source: false,
    transcript_range: { start: moment.start, end: moment.end, turn_ids: [] },
    trigger: 'audit',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
  };
}
