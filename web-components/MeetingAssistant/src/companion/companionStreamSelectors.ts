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

/** The one arrival-order stream: items and chat merge by the `seq` of the event that created them, oldest first and newest last. Old meetings saved before `seq` existed carry the order of their replayed events, so the same rule holds for them. */
export function selectCompanionStream(timeline: Pick<CompanionTimelineState, 'items' | 'chat'> & Partial<Pick<CompanionTimelineState, 'evaluations'>>, options: CompanionStreamOptions = {}): CompanionStreamEntry[] {
  const entries: CompanionStreamEntry[] = [];
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
  entries.sort((a, b) => (a.seq as number) - (b.seq as number));

  const persistedChatIds = new Set(timeline.chat.map((message) => message.id));
  const drafts = options.drafts ?? {};
  for (const [messageId, text] of Object.entries(drafts)) {
    if (persistedChatIds.has(messageId)) continue;
    entries.push({ type: 'draft', key: `chat:${messageId}`, seq: null, messageId, text });
  }
  for (const messageId of options.pendingAssistantIds ?? []) {
    if (persistedChatIds.has(messageId) || messageId in drafts) continue;
    entries.push({ type: 'pending', key: `chat:${messageId}`, seq: null, messageId });
  }
  return entries;
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

/** Proposals still waiting for a decision. They stay marked until the user acts, however long ago they arrived. */
export function selectProposalsAwaitingDecision(items: CompanionItem[]): CompanionItem[] {
  return items.filter((item) => item.kind === 'proposal' && !item.dismissed && item.proposal?.state === 'proposed');
}
