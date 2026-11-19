import type { ChecklistItem, ChecklistRef, ChecklistStatus } from '../../services/checklistApi';
import type { ChecklistLiveCounts } from '../../store/checklistStore';

export const CHECKLIST_STATUS_LABEL: Record<ChecklistStatus, string> = {
  pending: 'To do',
  in_progress: 'In progress',
  waiting_external: 'Waiting on someone else',
  waiting_user: 'Needs your input',
  done: 'Done',
  dropped: 'Dropped',
};

export const CHECKLIST_STATUS_OPTIONS: ChecklistStatus[] = ['pending', 'in_progress', 'waiting_user', 'waiting_external', 'done', 'dropped'];

// What the reader most needs first: what is waiting on them, then what is moving, then what has not started, then what waits on others.
const OPEN_RANK: Record<ChecklistStatus, number> = {
  waiting_user: 0,
  in_progress: 1,
  pending: 2,
  waiting_external: 3,
  done: 4,
  dropped: 5,
};

/** The longest step text the checklist stores. It matches the backend limit, so typed text is never silently cut. */
export const CHECKLIST_TITLE_MAX_CHARS = 500;

/** The most rows the Run overview shows before "Show all". */
export const OVERVIEW_ROW_LIMIT = 5;

export type ChecklistPillTone = 'attention' | 'complete' | 'neutral';

export function isOpenStatus(status: ChecklistStatus): boolean {
  return status !== 'done' && status !== 'dropped';
}

/** True for an item Basil closed on judgment, which the reader can confirm or reopen. */
export function isInferredDone(item: Pick<ChecklistItem, 'status' | 'done_basis'>): boolean {
  return item.status === 'done' && item.done_basis === 'inferred';
}

/** Items in reading order: open ones by priority, then done, then dropped; the list's own order breaks ties. Archived items are left out. */
export function prioritizeChecklistItems(items: readonly ChecklistItem[]): ChecklistItem[] {
  return items
    .filter(item => !item.archived_at)
    .sort((left, right) => OPEN_RANK[left.status] - OPEN_RANK[right.status] || left.sort_order - right.sort_order || left.created_at.localeCompare(right.created_at));
}

export function checklistCounterText(counts: Pick<ChecklistLiveCounts, 'done' | 'total'>): string {
  return `${counts.done}/${counts.total}`;
}

export function checklistCounterLabel(counts: ChecklistLiveCounts): string {
  const base = `Checklist, ${counts.done} of ${counts.total} done`;
  if (counts.waitingUser > 0) return `${base}, ${counts.waitingUser} need${counts.waitingUser === 1 ? 's' : ''} your input`;
  return counts.closed ? `${base}, tracking stopped` : base;
}

export function checklistPillTone(counts: ChecklistLiveCounts): ChecklistPillTone {
  if (counts.waitingUser > 0) return 'attention';
  if (counts.total > 0 && counts.done === counts.total) return 'complete';
  return 'neutral';
}

export function checklistItemAriaLabel(item: ChecklistItem): string {
  const waiting = item.status === 'waiting_user' || item.status === 'waiting_external';
  const waitingOn = waiting && item.waiting_on ? `: ${item.waiting_on}` : '';
  const required = item.required ? ', required' : '';
  const inferred = isInferredDone(item) ? ', marked done by Basil from what it could see' : '';
  return `${item.title}, ${CHECKLIST_STATUS_LABEL[item.status].toLowerCase()}${waitingOn}${required}${inferred}`;
}

export function checklistRefLabel(ref: ChecklistRef): string {
  return ref.label || ref.external_id;
}

export function checklistRefSystem(ref: ChecklistRef): string {
  return [ref.source_system, ref.ref_kind].filter(Boolean).join(' ').replace(/_/g, ' ');
}

/** Only http and https references become links; anything else (a file path, a custom scheme) is shown as text. */
export function safeChecklistRefUrl(ref: ChecklistRef): string | null {
  if (!ref.open_url) return null;
  try {
    const url = new URL(ref.open_url);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null;
  } catch {
    return null;
  }
}

const EVENT_VERB: Record<string, string> = {
  added: 'Added',
  status: 'Changed status',
  edited: 'Edited',
  note: 'Noted',
  archived: 'Archived',
  restored: 'Restored',
  carried: 'Carried over',
  todo_offered: 'Offered as a To-Do',
  ref_added: 'Linked',
};

const STATUS_WORD = /\b(pending|in_progress|waiting_external|waiting_user|done|dropped)\b/g;

/** A status change is logged with the raw status names ("pending to done"); show them as the labels the reader sees. */
function readableEventText(kind: string, text: string): string {
  if (kind !== 'status') return text;
  return text.replace(STATUS_WORD, word => CHECKLIST_STATUS_LABEL[word as ChecklistStatus].toLowerCase());
}

export function checklistEventSummary(kind: string, text: string): string {
  const verb = EVENT_VERB[kind] ?? kind.replace(/_/g, ' ');
  const detail = readableEventText(kind, text);
  return detail ? `${verb}: ${detail}` : verb;
}

export function checklistActorLabel(actor: string): string {
  if (actor === 'user') return 'You';
  if (actor === 'agent') return 'Basil';
  return actor || 'Basil';
}
