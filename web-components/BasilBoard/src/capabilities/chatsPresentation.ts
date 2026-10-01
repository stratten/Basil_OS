import type {
  ConversationFileReference,
  ConversationMessageItem,
  WSEvent,
} from '../contracts';

export interface ConversationStreamState {
  content: string;
  thinking: string;
  buffer: string;
  insideThinking: boolean;
  lastChunkId: number;
}

export interface ConversationStreamReduction {
  state: ConversationStreamState;
  accepted: boolean;
}

export function initialConversationStreamState(): ConversationStreamState {
  return {
    content: '',
    thinking: '',
    buffer: '',
    insideThinking: false,
    lastChunkId: -1,
  };
}

function longestMarkerPrefixSuffix(value: string, marker: string): number {
  const maximum = Math.min(value.length, marker.length - 1);
  for (let length = maximum; length > 0; length -= 1) {
    if (value.endsWith(marker.slice(0, length))) return length;
  }
  return 0;
}

function appendSegment(
  state: ConversationStreamState,
  segment: string,
): ConversationStreamState {
  if (!segment) return state;
  return state.insideThinking
    ? { ...state, thinking: state.thinking + segment }
    : { ...state, content: state.content + segment };
}

export function reduceConversationToken(
  current: ConversationStreamState,
  event: WSEvent,
): ConversationStreamReduction {
  if (
    event.event_type !== 'conversation_token'
    || typeof event.chunk_id !== 'number'
    || !Number.isInteger(event.chunk_id)
    || event.chunk_id !== current.lastChunkId + 1
    || typeof event.token !== 'string'
  ) {
    return { state: current, accepted: false };
  }

  let state: ConversationStreamState = {
    ...current,
    buffer: current.buffer + event.token,
    lastChunkId: event.chunk_id,
  };

  while (state.buffer) {
    const marker = state.insideThinking ? '</think>' : '<think>';
    const markerIndex = state.buffer.indexOf(marker);
    if (markerIndex >= 0) {
      state = appendSegment(state, state.buffer.slice(0, markerIndex));
      state = {
        ...state,
        buffer: state.buffer.slice(markerIndex + marker.length),
        insideThinking: !state.insideThinking,
      };
      continue;
    }

    if (event.is_final) {
      state = appendSegment(state, state.buffer);
      state = { ...state, buffer: '' };
      break;
    }

    const preservedLength = longestMarkerPrefixSuffix(state.buffer, marker);
    const flushLength = state.buffer.length - preservedLength;
    state = appendSegment(state, state.buffer.slice(0, flushLength));
    state = { ...state, buffer: state.buffer.slice(flushLength) };
    break;
  }

  if (event.is_final) {
    state = {
      ...state,
      content: state.content.trim(),
      thinking: state.thinking.trim(),
      insideThinking: false,
    };
  }

  return { state, accepted: true };
}

export function acceptsConversationEvent(
  event: WSEvent,
  displayedConversationId: string | undefined,
  pendingRequestId: string | undefined,
): boolean {
  if (!pendingRequestId || event.request_id !== pendingRequestId) return false;
  if (event.event_type === 'conversation_cancel_rejected') return true;
  if (!event.conversation_id) return false;
  return !displayedConversationId || event.conversation_id === displayedConversationId;
}

export function acceptsPersistedConversationEvent(
  event: WSEvent,
  displayedConversationId: string | undefined,
  knownMessageIds: ReadonlySet<string>,
): boolean {
  if (event.event_type !== 'conversation_token' && event.event_type !== 'conversation_stream_reset') {
    return false;
  }
  if (event.request_id) return false;
  if (!displayedConversationId || event.conversation_id !== displayedConversationId) return false;
  if (!event.message_id || !knownMessageIds.has(event.message_id)) return false;
  return true;
}

export function conversationDisplayMarkdown(message: ConversationMessageItem): string {
  const displayMarkdown = message.metadata?.display_markdown;
  return typeof displayMarkdown === 'string' && displayMarkdown.trim()
    ? displayMarkdown
    : message.content;
}

function isConversationFileReference(value: unknown): value is ConversationFileReference {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.filename === 'string'
    && candidate.filename.length > 0
    && typeof candidate.path === 'string'
    && candidate.path.length > 0
    && typeof candidate.file_type === 'string'
    && typeof candidate.file_size === 'number'
    && Number.isFinite(candidate.file_size)
    && candidate.file_size >= 0
  );
}

export function conversationAttachments(
  message: ConversationMessageItem,
): ConversationFileReference[] {
  const attachedFiles = message.metadata?.attached_files;
  return Array.isArray(attachedFiles)
    ? attachedFiles.filter(isConversationFileReference)
    : [];
}

const OFFSET_LESS_ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

/** Conversation timestamps without an offset are stored as UTC by SQLite, so they must not be parsed as local time. */
export function parseConversationTimestamp(value: string): Date {
  const trimmed = value.trim();
  if (OFFSET_LESS_ISO_DATE_TIME.test(trimmed)) return new Date(`${trimmed.replace(' ', 'T')}Z`);
  return new Date(trimmed);
}

export function formatConversationTimestamp(value: string): string {
  const date = parseConversationTimestamp(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}
