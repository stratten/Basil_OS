import { applyProposalUpdate, applyTimelineEvent, emptyTimelineState, timelineStateFromSnapshot, type CompanionTimelineState } from './companionReducer';
import { EMPTY_COMPANION_STATUS, type CompanionProposalResult, type CompanionSnapshot, type CompanionStatus, type TimelineEvent } from './types';

export const MAX_BUFFERED_EVENTS = 500;

export type CompanionPhase = 'idle' | 'loading' | 'ready' | 'error';

export interface CompanionStoreState {
  phase: CompanionPhase;
  loadError: string | null;
  timeline: CompanionTimelineState;
  /** The `last_seq` of the snapshot the pane hydrated from. Everything at or below it is backlog: it never animates in and never counts as unseen. */
  baselineSeq: number;
  status: CompanionStatus;
  buffer: TimelineEvent[];
  resyncNeeded: boolean;
  /** Streaming assistant text keyed by assistant message id; removed when the persisted chat event arrives. */
  drafts: Record<string, string>;
  /** Assistant message ids acknowledged by `POST /chat` that have no text and no persisted message yet. */
  pendingAssistantIds: string[];
}

export const initialCompanionStoreState: CompanionStoreState = {
  phase: 'idle',
  loadError: null,
  timeline: emptyTimelineState,
  baselineSeq: 0,
  status: EMPTY_COMPANION_STATUS,
  buffer: [],
  resyncNeeded: false,
  drafts: {},
  pendingAssistantIds: [],
};

export type CompanionStoreAction =
  | { type: 'reset'; phase: 'idle' | 'loading' }
  | { type: 'hydrated'; snapshot: CompanionSnapshot }
  | { type: 'loadFailed'; message: string }
  | { type: 'event'; event: TimelineEvent }
  | { type: 'status'; status: Partial<CompanionStatus> }
  | { type: 'chatDelta'; messageId: string; textDelta: string }
  | { type: 'chatPending'; messageId: string }
  /** The backend's answer to an approve or dismiss click; also the only update a finished meeting gets, because it has no live event stream. */
  | { type: 'proposalResult'; itemId: string; result: CompanionProposalResult };

function withoutKeys(record: Record<string, string>, keys: string[]): Record<string, string> {
  if (keys.length === 0) return record;
  const next: Record<string, string> = {};
  for (const [key, value] of Object.entries(record)) {
    if (!keys.includes(key)) next[key] = value;
  }
  return next;
}

function chatMessageId(event: TimelineEvent): string | null {
  if (event.kind !== 'chat' || typeof event.payload !== 'object' || event.payload === null) return null;
  const id = (event.payload as Record<string, unknown>).message_id;
  return typeof id === 'string' ? id : null;
}

function applyLiveEvent(state: CompanionStoreState, event: TimelineEvent): CompanionStoreState {
  if (event.seq <= state.timeline.lastSeq) return state;
  if (event.seq > state.timeline.lastSeq + 1) return { ...state, resyncNeeded: true };
  const timeline = applyTimelineEvent(state.timeline, event);
  const persistedChatId = chatMessageId(event);
  if (persistedChatId === null) return { ...state, timeline };
  return {
    ...state,
    timeline,
    drafts: withoutKeys(state.drafts, [persistedChatId]),
    pendingAssistantIds: state.pendingAssistantIds.filter((id) => id !== persistedChatId),
  };
}

export function companionStoreReducer(state: CompanionStoreState, action: CompanionStoreAction): CompanionStoreState {
  switch (action.type) {
    case 'reset':
      return { ...initialCompanionStoreState, phase: action.phase };
    case 'hydrated': {
      const persistedIds = action.snapshot.chat.map((message) => message.id);
      let next: CompanionStoreState = {
        ...state,
        phase: 'ready',
        loadError: null,
        timeline: timelineStateFromSnapshot(action.snapshot),
        baselineSeq: action.snapshot.last_seq,
        status: action.snapshot.status,
        buffer: [],
        resyncNeeded: false,
        drafts: withoutKeys(state.drafts, persistedIds),
        pendingAssistantIds: state.pendingAssistantIds.filter((id) => !persistedIds.includes(id)),
      };
      for (const buffered of [...state.buffer].sort((a, b) => a.seq - b.seq)) {
        next = applyLiveEvent(next, buffered);
      }
      return next;
    }
    case 'loadFailed':
      return {
        ...state,
        phase: state.phase === 'ready' ? 'ready' : 'error',
        loadError: action.message,
        resyncNeeded: false,
      };
    case 'event': {
      if (state.phase !== 'ready') {
        const buffer = [...state.buffer, action.event];
        return { ...state, buffer: buffer.length > MAX_BUFFERED_EVENTS ? buffer.slice(buffer.length - MAX_BUFFERED_EVENTS) : buffer };
      }
      return applyLiveEvent(state, action.event);
    }
    case 'status':
      return { ...state, status: { ...state.status, ...action.status } };
    case 'chatDelta':
      return {
        ...state,
        drafts: { ...state.drafts, [action.messageId]: `${state.drafts[action.messageId] ?? ''}${action.textDelta}` },
        pendingAssistantIds: state.pendingAssistantIds.filter((id) => id !== action.messageId),
      };
    case 'chatPending':
      if (state.timeline.chat.some((message) => message.id === action.messageId) || action.messageId in state.drafts) return state;
      return { ...state, pendingAssistantIds: [...state.pendingAssistantIds, action.messageId] };
    case 'proposalResult': {
      const items = applyProposalUpdate(state.timeline.items, {
        item_id: action.itemId,
        state: action.result.state,
        todo_id: action.result.todo_id,
        agent_task_id: action.result.agent_task_id,
        error: action.result.error,
      });
      return items === state.timeline.items ? state : { ...state, timeline: { ...state.timeline, items } };
    }
    default:
      return state;
  }
}
