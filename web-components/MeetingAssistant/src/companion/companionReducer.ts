import type {
  ChatMessage,
  CompanionItem,
  CompanionRoot,
  CompanionSnapshot,
  CompanionWatch,
  FileCitation,
  TimelineEvent,
} from './types';

export const MAX_DERIVED_RETRIEVALS = 200;

const ITEM_KINDS = new Set<string>(['insight', 'suggestion', 'answer', 'context_note']);
const ROOT_KINDS = new Set<string>(['folder', 'file']);
const CHAT_ROLES = new Set<string>(['user', 'assistant']);
const CHAT_STATUSES = new Set<string>(['complete', 'error']);

/** Everything the feed renders, derived only from timeline events or a snapshot. */
export interface CompanionTimelineState {
  items: CompanionItem[];
  roots: CompanionRoot[];
  watches: CompanionWatch[];
  chat: ChatMessage[];
  retrievals: TimelineEvent[];
  statusEvent: Record<string, unknown> | null;
  lastError: { code: string; message: string } | null;
  lastSeq: number;
}

export const emptyTimelineState: CompanionTimelineState = {
  items: [],
  roots: [],
  watches: [],
  chat: [],
  retrievals: [],
  statusEvent: null,
  lastError: null,
  lastSeq: 0,
};

class MalformedEvent extends Error {}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function requiredText(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  if (typeof value !== 'string') throw new MalformedEvent(`missing text field ${key}`);
  return value;
}

function parseCitation(value: unknown): FileCitation | null {
  if (!isRecord(value)) return null;
  if (typeof value.path !== 'string' || typeof value.excerpt !== 'string') return null;
  if (!isFiniteNumber(value.line_start) || !isFiniteNumber(value.line_end)) return null;
  return { path: value.path, line_start: value.line_start, line_end: value.line_end, excerpt: value.excerpt };
}

/** Structural validation of one item payload; returns null for anything the Python `CompanionItem` model would reject. */
export function parseCompanionItem(value: unknown): CompanionItem | null {
  if (!isRecord(value)) return null;
  if (typeof value.id !== 'string' || typeof value.text !== 'string' || typeof value.trigger !== 'string') return null;
  if (typeof value.kind !== 'string' || !ITEM_KINDS.has(value.kind)) return null;
  if (!isFiniteNumber(value.confidence)) return null;
  const range = value.transcript_range;
  if (!isRecord(range) || !isFiniteNumber(range.start) || !isFiniteNumber(range.end)) return null;
  const citations = Array.isArray(value.citations)
    ? value.citations.map(parseCitation).filter((citation): citation is FileCitation => citation !== null)
    : [];
  const turnIds = Array.isArray(range.turn_ids) ? range.turn_ids.filter((id): id is string => typeof id === 'string') : [];
  return {
    id: value.id,
    kind: value.kind as CompanionItem['kind'],
    text: value.text,
    confidence: value.confidence,
    citations,
    no_source: value.no_source === true,
    transcript_range: { start: range.start, end: range.end, turn_ids: turnIds },
    trigger: value.trigger,
    watch_id: typeof value.watch_id === 'string' ? value.watch_id : null,
    truncated: value.truncated === true,
    pinned: value.pinned === true,
    dismissed: value.dismissed === true,
    ...(isFiniteNumber(value.latency_ms) && value.latency_ms >= 0 ? { latency_ms: Math.round(value.latency_ms) } : {}),
  };
}

function replaceOrAppend<T extends { id: string }>(list: T[], next: T): T[] {
  const index = list.findIndex((entry) => entry.id === next.id);
  if (index < 0) return [...list, next];
  const copy = list.slice();
  copy[index] = next;
  return copy;
}

function updateItem(items: CompanionItem[], itemId: string, patch: Partial<CompanionItem>): CompanionItem[] {
  const index = items.findIndex((item) => item.id === itemId);
  if (index < 0) return items;
  const copy = items.slice();
  copy[index] = { ...items[index], ...patch };
  return copy;
}

function applyFeedback(state: CompanionTimelineState, payload: Record<string, unknown>): CompanionTimelineState {
  const itemId = requiredText(payload, 'item_id');
  const action = requiredText(payload, 'action');
  if (action === 'dismissed') return { ...state, items: updateItem(state.items, itemId, { dismissed: true, pinned: false }) };
  if (action === 'pinned') return { ...state, items: updateItem(state.items, itemId, { pinned: true, dismissed: false }) };
  if (action === 'unpinned') return { ...state, items: updateItem(state.items, itemId, { pinned: false }) };
  return state;
}

function applyChat(state: CompanionTimelineState, event: TimelineEvent, payload: Record<string, unknown>): CompanionTimelineState {
  const messageId = requiredText(payload, 'message_id');
  const role = payload.role;
  if (typeof role !== 'string' || !CHAT_ROLES.has(role)) throw new MalformedEvent('bad chat role');
  const status = payload.status === undefined ? 'complete' : payload.status;
  if (typeof status !== 'string' || !CHAT_STATUSES.has(status)) throw new MalformedEvent('bad chat status');
  const message: ChatMessage = {
    id: messageId,
    role: role as ChatMessage['role'],
    text: requiredText(payload, 'text'),
    meeting_time: event.meeting_time,
    truncated: payload.truncated === true,
    status: status as ChatMessage['status'],
  };
  return { ...state, chat: replaceOrAppend(state.chat, message) };
}

function applyWatch(state: CompanionTimelineState, event: TimelineEvent, payload: Record<string, unknown>): CompanionTimelineState {
  const watchId = requiredText(payload, 'watch_id');
  const watchState = payload.state;
  if (watchState === 'created') {
    const keywords = Array.isArray(payload.keywords) ? payload.keywords.map((keyword) => String(keyword)) : [];
    const watch: CompanionWatch = {
      id: watchId,
      topic: requiredText(payload, 'topic'),
      instruction: requiredText(payload, 'instruction'),
      keywords,
      created_at: event.meeting_time,
      active: true,
      last_triggered_at: null,
    };
    return { ...state, watches: replaceOrAppend(state.watches, watch) };
  }
  const existing = state.watches.find((watch) => watch.id === watchId);
  if (!existing) return state;
  if (watchState === 'triggered') {
    return { ...state, watches: replaceOrAppend(state.watches, { ...existing, last_triggered_at: event.meeting_time }) };
  }
  if (watchState === 'canceled') {
    return { ...state, watches: replaceOrAppend(state.watches, { ...existing, active: false }) };
  }
  return state;
}

function applySource(state: CompanionTimelineState, event: TimelineEvent, payload: Record<string, unknown>): CompanionTimelineState {
  const rootId = requiredText(payload, 'root_id');
  const sourceState = payload.state;
  if (sourceState === 'attached') {
    const kind = payload.kind;
    if (typeof kind !== 'string' || !ROOT_KINDS.has(kind)) throw new MalformedEvent('bad root kind');
    const root: CompanionRoot = {
      id: rootId,
      path: requiredText(payload, 'path'),
      display_name: requiredText(payload, 'display_name'),
      kind: kind as CompanionRoot['kind'],
      attached_at: event.meeting_time,
      detached_at: null,
    };
    return { ...state, roots: replaceOrAppend(state.roots, root) };
  }
  if (sourceState === 'detached') {
    return { ...state, roots: state.roots.filter((root) => root.id !== rootId) };
  }
  return state;
}

function applyPayload(state: CompanionTimelineState, event: TimelineEvent): CompanionTimelineState {
  const payload = isRecord(event.payload) ? event.payload : {};
  switch (event.kind) {
    case 'item': {
      const item = parseCompanionItem(payload.item);
      if (item === null) throw new MalformedEvent('bad item');
      if (state.items.some((existing) => existing.id === item.id)) return state;
      return { ...state, items: [...state.items, item] };
    }
    case 'retrieval': {
      const retrievals = [...state.retrievals, event];
      return {
        ...state,
        retrievals: retrievals.length > MAX_DERIVED_RETRIEVALS ? retrievals.slice(retrievals.length - MAX_DERIVED_RETRIEVALS) : retrievals,
      };
    }
    case 'feedback':
      return applyFeedback(state, payload);
    case 'chat':
      return applyChat(state, event, payload);
    case 'watch':
      return applyWatch(state, event, payload);
    case 'source':
      return applySource(state, event, payload);
    case 'status':
      return { ...state, statusEvent: { ...payload } };
    case 'error':
      return { ...state, lastError: { code: requiredText(payload, 'code'), message: requiredText(payload, 'message') } };
    default:
      return state;
  }
}

/** Applies one event; never throws. A malformed event only advances `lastSeq`. */
export function applyTimelineEvent(state: CompanionTimelineState, event: TimelineEvent): CompanionTimelineState {
  const seq = isFiniteNumber(event.seq) ? event.seq : 0;
  const base = seq > state.lastSeq ? { ...state, lastSeq: seq } : state;
  try {
    return applyPayload(base, event);
  } catch {
    return base;
  }
}

/** Folds events (in `seq` order) into derived state; the TypeScript twin of Python `reduce_timeline`. */
export function reduceTimeline(events: Iterable<TimelineEvent>): CompanionTimelineState {
  let state = emptyTimelineState;
  for (const event of events) state = applyTimelineEvent(state, event);
  return state;
}

/** Seeds the store from a server snapshot, which is already reduced (pinned and dismissed applied). */
export function timelineStateFromSnapshot(snapshot: CompanionSnapshot): CompanionTimelineState {
  const retrievals = snapshot.retrievals ?? [];
  return {
    items: snapshot.items ?? [],
    roots: snapshot.roots ?? [],
    watches: snapshot.watches ?? [],
    chat: snapshot.chat ?? [],
    retrievals: retrievals.length > MAX_DERIVED_RETRIEVALS ? retrievals.slice(retrievals.length - MAX_DERIVED_RETRIEVALS) : retrievals,
    statusEvent: null,
    lastError: null,
    lastSeq: snapshot.last_seq ?? 0,
  };
}

/** Feed order: pinned items first, then the rest, each newest first by the end of their transcript range; dismissed items are hidden unless requested. */
export function selectFeedItems(items: CompanionItem[], options: { includeDismissed?: boolean } = {}): CompanionItem[] {
  const visible = options.includeDismissed ? items : items.filter((item) => !item.dismissed);
  const newestFirst = (a: CompanionItem, b: CompanionItem) => b.transcript_range.end - a.transcript_range.end;
  const pinned = visible.filter((item) => item.pinned).sort(newestFirst);
  const rest = visible.filter((item) => !item.pinned).sort(newestFirst);
  return [...pinned, ...rest];
}
