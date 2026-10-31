import type { CompanionTimelineState } from './companionReducer';
import type { ChatMessage, CompanionItem, TimelineEvent } from './types';

/** One row of the Companion stream. Persisted rows carry the `seq` of the event that created them; a streaming or pending assistant reply has none yet and always sits at the end. */
export type CompanionStreamEntry =
  | { type: 'item'; key: string; seq: number; item: CompanionItem }
  | { type: 'chat'; key: string; seq: number; message: ChatMessage }
  /** One evaluation from the ledger, shown only when the reader asks to see what the Companion considered. */
  | { type: 'considered'; key: string; seq: number; event: TimelineEvent }
  | { type: 'draft'; key: string; seq: null; messageId: string; text: string }
  | { type: 'pending'; key: string; seq: null; messageId: string };

/** Which Companion items the stream shows. The reader's conversation with the Companion is never filtered. */
export type CompanionKindFilter = 'all' | 'suggestion' | 'answer' | 'context_note' | 'pinned';

export const COMPANION_KIND_FILTERS: ReadonlyArray<{ value: CompanionKindFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'suggestion', label: 'Suggestions' },
  { value: 'answer', label: 'Answers' },
  { value: 'context_note', label: 'From your sources' },
  { value: 'pinned', label: 'Pinned' },
];

/** Whether an item shows under a filter. A proposal waiting for the reader's decision always shows, so a filter can never hide something that needs an answer. */
export function itemMatchesKindFilter(item: CompanionItem, filter: CompanionKindFilter): boolean {
  if (filter === 'all') return true;
  if (item.kind === 'proposal' && item.proposal?.state === 'proposed') return true;
  if (filter === 'pinned') return item.pinned;
  return item.kind === filter;
}

/** How many shown-eligible items each filter would match, for the counts on the filter buttons. Dismissed items are not counted. */
export function countKindFilters(items: CompanionItem[]): Record<CompanionKindFilter, number> {
  const counts: Record<CompanionKindFilter, number> = { all: 0, suggestion: 0, answer: 0, context_note: 0, pinned: 0 };
  for (const item of items) {
    if (item.dismissed) continue;
    counts.all += 1;
    if (item.pinned) counts.pinned += 1;
    if (item.kind === 'suggestion' || item.kind === 'answer' || item.kind === 'context_note') counts[item.kind] += 1;
  }
  return counts;
}

export interface CompanionStreamOptions {
  includeDismissed?: boolean;
  kindFilter?: CompanionKindFilter;
  /** Adds a row for every evaluation in the timeline's ledger. */
  showConsidered?: boolean;
  drafts?: Record<string, string>;
  pendingAssistantIds?: string[];
}

/** The trigger the backend gives an item made from an audit finding. */
export const AUDIT_ITEM_TRIGGER = 'audit';

type PersistedStreamEntry = Exclude<CompanionStreamEntry, { seq: null }>;

function entryMeetingTime(entry: PersistedStreamEntry): number {
  if (entry.type === 'item') return entry.item.transcript_range.end;
  if (entry.type === 'chat') return entry.message.meeting_time;
  return entry.event.meeting_time;
}

function isAuditEntry(entry: PersistedStreamEntry): boolean {
  return entry.type === 'item' && entry.item.trigger === AUDIT_ITEM_TRIGGER;
}

/** An audit finding arrives long after the moment it points at, so it is shown where that moment happened: after the last row at or before the end of the finding's transcript range. Every other row keeps its arrival order, and `seq` is untouched so the finding still counts as new when it arrives. */
function placeAuditFindingsByMeetingTime(arrivalOrdered: PersistedStreamEntry[]): PersistedStreamEntry[] {
  const findings = arrivalOrdered.filter(isAuditEntry);
  if (findings.length === 0) return arrivalOrdered;
  const placed = arrivalOrdered.filter((entry) => !isAuditEntry(entry));
  const byTime = [...findings].sort((a, b) => entryMeetingTime(a) - entryMeetingTime(b) || a.seq - b.seq);
  for (const finding of byTime) {
    const time = entryMeetingTime(finding);
    let insertAt = 0;
    placed.forEach((entry, index) => {
      if (entryMeetingTime(entry) <= time) insertAt = index + 1;
    });
    placed.splice(insertAt, 0, finding);
  }
  return placed;
}

/** The one stream: items and chat merge by the `seq` of the event that created them, oldest first and newest last, except that audit findings sit at the point in the meeting they refer to. Old meetings saved before `seq` existed carry the order of their replayed events, so the same rule holds for them. */
export function selectCompanionStream(timeline: Pick<CompanionTimelineState, 'items' | 'chat'> & Partial<Pick<CompanionTimelineState, 'evaluations'>>, options: CompanionStreamOptions = {}): CompanionStreamEntry[] {
  const entries: PersistedStreamEntry[] = [];
  for (const item of timeline.items) {
    if (item.dismissed && !options.includeDismissed) continue;
    if (!itemMatchesKindFilter(item, options.kindFilter ?? 'all')) continue;
    entries.push({ type: 'item', key: `item:${item.id}`, seq: item.seq, item });
  }
  for (const message of timeline.chat) {
    entries.push({ type: 'chat', key: `chat:${message.id}`, seq: message.seq, message });
  }
  if (options.showConsidered) {
    for (const event of timeline.evaluations ?? []) {
      entries.push({ type: 'considered', key: `eval:${event.id}`, seq: event.seq, event });
    }
  }
  entries.sort((a, b) => a.seq - b.seq);
  const ordered: CompanionStreamEntry[] = placeAuditFindingsByMeetingTime(entries);

  const persistedChatIds = new Set(timeline.chat.map((message) => message.id));
  const drafts = options.drafts ?? {};
  for (const [messageId, text] of Object.entries(drafts)) {
    if (persistedChatIds.has(messageId)) continue;
    ordered.push({ type: 'draft', key: `chat:${messageId}`, seq: null, messageId, text });
  }
  for (const messageId of options.pendingAssistantIds ?? []) {
    if (persistedChatIds.has(messageId) || messageId in drafts) continue;
    ordered.push({ type: 'pending', key: `chat:${messageId}`, seq: null, messageId });
  }
  return ordered;
}

/** Pinned items for the strip, in the order they arrived. A dismissed item is not shown even when pinned. */
export function selectPinnedItems(items: CompanionItem[]): CompanionItem[] {
  return items.filter((item) => item.pinned && !item.dismissed).sort((a, b) => a.seq - b.seq);
}

/** True for a row that should count toward "new" awareness: the reader's own messages never do. */
export function countsAsUnseen(entry: CompanionStreamEntry): boolean {
  if (entry.seq === null) return false;
  if (entry.type === 'chat') return entry.message.role === 'assistant';
  if (entry.type === 'considered') return false;
  return true;
}

/** Persisted rows that arrived after the reader last saw the stream, oldest first. */
export function selectUnseenEntries(entries: CompanionStreamEntry[], lastSeenSeq: number): CompanionStreamEntry[] {
  return entries.filter((entry) => entry.seq !== null && entry.seq > lastSeenSeq && countsAsUnseen(entry));
}

/** The reader's questions paired with the saved answers that follow them. An answer belongs to the latest question before it; a streaming or pending reply is not paired until it is saved. Both maps are keyed the way the fold state is: by the question's message id for answers, and by the answer row's key for questions. */
export interface ChatPairs {
  /** Question message id to the keys of its saved answer rows, in order. A question with no saved answer has no entry. */
  answerKeysByQuestion: Map<string, string[]>;
  /** Answer row key to the id of the question it answers. */
  questionByAnswerKey: Map<string, string>;
}

export function selectChatPairs(entries: CompanionStreamEntry[]): ChatPairs {
  const answerKeysByQuestion = new Map<string, string[]>();
  const questionByAnswerKey = new Map<string, string>();
  let questionId: string | null = null;
  for (const entry of entries) {
    if (entry.type !== 'chat') continue;
    if (entry.message.role === 'user') {
      questionId = entry.message.id;
      continue;
    }
    if (questionId === null) continue;
    answerKeysByQuestion.set(questionId, [...(answerKeysByQuestion.get(questionId) ?? []), entry.key]);
    questionByAnswerKey.set(entry.key, questionId);
  }
  return { answerKeysByQuestion, questionByAnswerKey };
}

/** The stream without the answers of folded questions, so a folded pair takes only the room of its question. */
export function hideFoldedAnswers(entries: CompanionStreamEntry[], pairs: ChatPairs, foldedQuestionIds: readonly string[]): CompanionStreamEntry[] {
  const hidden = new Set<string>();
  for (const questionId of foldedQuestionIds) {
    for (const key of pairs.answerKeysByQuestion.get(questionId) ?? []) hidden.add(key);
  }
  return hidden.size === 0 ? entries : entries.filter((entry) => !hidden.has(entry.key));
}

/** Proposals still waiting for a decision. They stay marked until the user acts, however long ago they arrived. */
export function selectProposalsAwaitingDecision(items: CompanionItem[]): CompanionItem[] {
  return items.filter((item) => item.kind === 'proposal' && !item.dismissed && item.proposal?.state === 'proposed');
}
