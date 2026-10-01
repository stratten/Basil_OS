import type { ConversationMessageItem, WSEvent } from '../contracts';
import {
  initialConversationStreamState,
  reduceConversationToken,
  type ConversationStreamState,
} from './chatsPresentation';
import {
  buildAgentTaskPlaceholderMessage,
  conversationAgentTurnMetadata,
  isTerminalConversationAgentStatusLifecycle,
  mergeAgentStatusIntoMessage,
} from './conversationAgentStatusPresentation';
import {
  conversationAgentActivityMetadata,
  parseConversationAgentActivityEvent,
  type ConversationAgentActivityPresentation,
} from './conversationAgentActivityPresentation';

export const DRAFT_THREAD_KEY = '__draft__';
const PENDING_THREAD_KEY_PREFIX = '__pending_conversation__:';

export function pendingConversationThreadKey(requestId: string): string {
  return `${PENDING_THREAD_KEY_PREFIX}${requestId}`;
}

export function isPendingConversationThreadKey(key: string): boolean {
  return key.startsWith(PENDING_THREAD_KEY_PREFIX);
}

export interface ConversationDraftSubmission {
  requestId: string;
  messageId: string;
  content: string;
  displayMarkdown: string;
  conversationId?: string;
  modelId?: string;
  filePaths: string[];
  delegationOptOut: boolean;
  source: 'composer' | 'voice';
  editorHtml: string;
}

export interface ConversationRequestSession {
  requestId: string;
  conversationId?: string;
  submission: ConversationDraftSubmission;
  streamState: ConversationStreamState;
  agentTaskId?: string;
  canceling: boolean;
  ownedByThisSocket: boolean;
}

export interface ConversationThreadSession {
  key: string;
  conversationId?: string;
  messages: ConversationMessageItem[];
  messagesLoading: boolean;
  messagesError?: string;
  draftText: string;
  draftHtml: string;
  attachmentPaths: string[];
  activeFormats: Record<string, boolean>;
  delegationOptOut: boolean;
  delegationOptOutSource?: 'user' | 'resolved';
  responseError?: string;
  unsentSubmission?: ConversationDraftSubmission;
  persistedFailedSubmission?: ConversationDraftSubmission;
  activeRequestId?: string;
}

export interface ConversationSessionStore {
  threadsByKey: Record<string, ConversationThreadSession>;
  requestsById: Record<string, ConversationRequestSession>;
  requestIdToThreadKey: Record<string, string>;
}

export function initialConversationSessionStore(): ConversationSessionStore {
  return { threadsByKey: {}, requestsById: {}, requestIdToThreadKey: {} };
}

// ConversationWorkspace unmounts and remounts whenever the surrounding Board
// tab switches away from Conversation and back (BasilBoardShell only renders
// the active tab's content). Module-level state here survives that
// unmount/remount cycle for the lifetime of the page, so an unsent draft,
// attachments, and the "Conversation only" choice are not lost just from
// switching tabs and back. This is intentionally in-memory only (not
// persisted to disk) and resets on a full page reload.
let persistedConversationSessionStore: ConversationSessionStore | undefined;
let persistedSelectedConversationId: string | undefined;
let persistedSelectedPendingThreadKey: string | undefined;

export function getPersistedConversationSessionStore(): ConversationSessionStore {
  if (!persistedConversationSessionStore) {
    persistedConversationSessionStore = initialConversationSessionStore();
  }
  return persistedConversationSessionStore;
}

export function setPersistedConversationSessionStore(store: ConversationSessionStore): void {
  persistedConversationSessionStore = store;
}

export function getPersistedConversationSelection(): {
  selectedConversationId: string | undefined;
  selectedPendingThreadKey: string | undefined;
} {
  return {
    selectedConversationId: persistedSelectedConversationId,
    selectedPendingThreadKey: persistedSelectedPendingThreadKey,
  };
}

export function setPersistedConversationSelection(
  selectedConversationId: string | undefined,
  selectedPendingThreadKey: string | undefined,
): void {
  persistedSelectedConversationId = selectedConversationId;
  persistedSelectedPendingThreadKey = selectedPendingThreadKey;
}

/** Test-only: clears the module-level persistence so each test starts fresh. */
export function resetPersistedConversationSessionStateForTests(): void {
  persistedConversationSessionStore = undefined;
  persistedSelectedConversationId = undefined;
  persistedSelectedPendingThreadKey = undefined;
}

export function createDraftThreadSession(key: string): ConversationThreadSession {
  return {
    key,
    conversationId: key === DRAFT_THREAD_KEY ? undefined : key,
    messages: [],
    messagesLoading: false,
    messagesError: undefined,
    draftText: '',
    draftHtml: '',
    attachmentPaths: [],
    activeFormats: {},
    delegationOptOut: false,
    responseError: undefined,
    unsentSubmission: undefined,
    persistedFailedSubmission: undefined,
    activeRequestId: undefined,
  };
}

export function getOrCreateThread(
  store: ConversationSessionStore,
  key: string,
): ConversationThreadSession {
  return store.threadsByKey[key] ?? createDraftThreadSession(key);
}

export function withThread(
  store: ConversationSessionStore,
  key: string,
  updater: (thread: ConversationThreadSession) => ConversationThreadSession,
): ConversationSessionStore {
  const current = getOrCreateThread(store, key);
  const next = updater(current);
  return {
    ...store,
    threadsByKey: { ...store.threadsByKey, [key]: next },
  };
}

export function moveThreadSession(
  store: ConversationSessionStore,
  sourceThreadKey: string,
  destinationThreadKey: string,
): ConversationSessionStore {
  if (sourceThreadKey === destinationThreadKey) return store;
  const sourceThread = store.threadsByKey[sourceThreadKey];
  if (!sourceThread) return store;
  const nextThreadsByKey = { ...store.threadsByKey };
  delete nextThreadsByKey[sourceThreadKey];
  nextThreadsByKey[destinationThreadKey] = {
    ...sourceThread,
    key: destinationThreadKey,
    conversationId: destinationThreadKey.startsWith(PENDING_THREAD_KEY_PREFIX)
      || destinationThreadKey === DRAFT_THREAD_KEY
      ? undefined
      : destinationThreadKey,
  };
  const requestIdToThreadKey = Object.fromEntries(
    Object.entries(store.requestIdToThreadKey).map(([requestId, threadKey]) => (
      [requestId, threadKey === sourceThreadKey ? destinationThreadKey : threadKey]
    )),
  );
  return { ...store, threadsByKey: nextThreadsByKey, requestIdToThreadKey };
}

export function activeConversationIds(store: ConversationSessionStore): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const thread of Object.values(store.threadsByKey)) {
    if (thread.activeRequestId && thread.key !== DRAFT_THREAD_KEY) ids.add(thread.key);
  }
  return ids;
}

export function registerSubmission(
  store: ConversationSessionStore,
  threadKey: string,
  submission: ConversationDraftSubmission,
): ConversationSessionStore {
  const preparedStore = (
    submission.conversationId === undefined
    && threadKey === pendingConversationThreadKey(submission.requestId)
  )
    ? moveThreadSession(store, DRAFT_THREAD_KEY, threadKey)
    : store;
  const request: ConversationRequestSession = {
    requestId: submission.requestId,
    conversationId: submission.conversationId,
    submission,
    streamState: initialConversationStreamState(),
    agentTaskId: undefined,
    canceling: false,
    ownedByThisSocket: true,
  };
  const updatedStore: ConversationSessionStore = {
    ...preparedStore,
    requestsById: { ...preparedStore.requestsById, [submission.requestId]: request },
    requestIdToThreadKey: { ...preparedStore.requestIdToThreadKey, [submission.requestId]: threadKey },
  };
  return withThread(updatedStore, threadKey, (thread) => ({
    ...thread,
    activeRequestId: submission.requestId,
    responseError: undefined,
    unsentSubmission: undefined,
    persistedFailedSubmission: undefined,
  }));
}

export function adoptRequestConversationId(
  store: ConversationSessionStore,
  requestId: string,
  conversationId: string,
): ConversationSessionStore {
  const request = store.requestsById[requestId];
  if (!request) return store;
  const previousThreadKey = store.requestIdToThreadKey[requestId];
  const updatedStore: ConversationSessionStore = {
    ...store,
    requestsById: {
      ...store.requestsById,
      [requestId]: {
        ...request,
        conversationId,
        submission: { ...request.submission, conversationId },
      },
    },
  };
  if (!previousThreadKey || previousThreadKey === conversationId) {
    return updatedStore;
  }
  const previousThread = store.threadsByKey[previousThreadKey];
  const existingThread = store.threadsByKey[conversationId];
  const mergedThread: ConversationThreadSession = {
    ...(existingThread ?? createDraftThreadSession(conversationId)),
    ...previousThread,
    key: conversationId,
    conversationId,
  };
  const nextThreadsByKey = { ...updatedStore.threadsByKey };
  delete nextThreadsByKey[previousThreadKey];
  nextThreadsByKey[conversationId] = mergedThread;
  return {
    ...updatedStore,
    threadsByKey: nextThreadsByKey,
    requestIdToThreadKey: { ...updatedStore.requestIdToThreadKey, [requestId]: conversationId },
  };
}

export function applyTokenToRequest(
  store: ConversationSessionStore,
  event: WSEvent,
): {
  store: ConversationSessionStore;
  accepted: boolean;
  threadKey?: string;
  request?: ConversationRequestSession;
} {
  const requestId = event.request_id;
  if (!requestId) return { store, accepted: false };
  const request = store.requestsById[requestId];
  if (!request) return { store, accepted: false };
  const threadKey = store.requestIdToThreadKey[requestId];
  if (!threadKey) return { store, accepted: false, request };
  const reduction = reduceConversationToken(request.streamState, event);
  if (!reduction.accepted) return { store, accepted: false, threadKey, request };
  const updatedRequest: ConversationRequestSession = { ...request, streamState: reduction.state };
  const assistantId = event.message_id ?? `pending-${requestId}`;
  const nextStore = withThread(
    { ...store, requestsById: { ...store.requestsById, [requestId]: updatedRequest } },
    threadKey,
    (thread) => {
      const placeholder = thread.messages.find((message) => message.id === `pending-${requestId}`);
      const existingAssistant = thread.messages.find((message) => message.id === assistantId);
      const withoutPlaceholder = thread.messages.filter((message) => message.id !== `pending-${requestId}`);
      const assistant: ConversationMessageItem = {
        id: assistantId,
        role: 'assistant',
        content: reduction.state.content,
        timestamp: existingAssistant?.timestamp ?? placeholder?.timestamp ?? new Date().toISOString(),
        model_id: request.submission.modelId,
        metadata: { thinking: reduction.state.thinking, streaming: !event.is_final },
      };
      const index = withoutPlaceholder.findIndex((message) => message.id === assistantId);
      const messages = index < 0
        ? [...withoutPlaceholder, assistant]
        : withoutPlaceholder.map((message, messageIndex) => (messageIndex === index ? assistant : message));
      return { ...thread, messages };
    },
  );
  return { store: nextStore, accepted: true, threadKey, request: updatedRequest };
}

export function markRequestCanceling(
  store: ConversationSessionStore,
  requestId: string,
): ConversationSessionStore {
  const request = store.requestsById[requestId];
  if (!request) return store;
  return {
    ...store,
    requestsById: { ...store.requestsById, [requestId]: { ...request, canceling: true } },
  };
}

export function bindAgentTaskToRequest(
  store: ConversationSessionStore,
  requestId: string,
  agentTaskId: string,
): ConversationSessionStore {
  const request = store.requestsById[requestId];
  if (!request) return store;
  return {
    ...store,
    requestsById: { ...store.requestsById, [requestId]: { ...request, agentTaskId } },
  };
}

export function requestIdForAgentTask(
  store: ConversationSessionStore,
  agentTaskId: string,
): string | undefined {
  return Object.values(store.requestsById).find((request) => request.agentTaskId === agentTaskId)?.requestId;
}

export function pendingRequestForConversation(
  store: ConversationSessionStore,
  conversationId: string,
): ConversationRequestSession | undefined {
  return Object.values(store.requestsById).find(
    (request) => request.conversationId === conversationId && request.agentTaskId === undefined,
  );
}

export function clearRequest(
  store: ConversationSessionStore,
  requestId: string,
): ConversationSessionStore {
  const threadKey = store.requestIdToThreadKey[requestId];
  const nextRequestsById = { ...store.requestsById };
  delete nextRequestsById[requestId];
  const nextRequestIdToThreadKey = { ...store.requestIdToThreadKey };
  delete nextRequestIdToThreadKey[requestId];
  let nextStore: ConversationSessionStore = {
    ...store,
    requestsById: nextRequestsById,
    requestIdToThreadKey: nextRequestIdToThreadKey,
  };
  if (threadKey) {
    nextStore = withThread(nextStore, threadKey, (thread) => (
      thread.activeRequestId === requestId ? { ...thread, activeRequestId: undefined } : thread
    ));
  }
  return nextStore;
}

export function replaceThreadMessages(
  store: ConversationSessionStore,
  threadKey: string,
  messages: ConversationMessageItem[],
): ConversationSessionStore {
  return withThread(store, threadKey, (thread) => ({ ...thread, messages }));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function activityPresentationsMatch(
  left: ConversationAgentActivityPresentation,
  right: ConversationAgentActivityPresentation,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function activityLifecycleMatchesTerminalStatus(
  statusLifecycle: unknown,
  activityLifecycle: string,
): boolean {
  return !isTerminalConversationAgentStatusLifecycle(statusLifecycle)
    || statusLifecycle === activityLifecycle;
}

function preserveExistingAgentTaskStatus(
  existingMessage: ConversationMessageItem,
  historyMessage: ConversationMessageItem,
): boolean {
  const existingTurn = conversationAgentTurnMetadata(existingMessage);
  if (!existingTurn) return false;
  const historyTurn = conversationAgentTurnMetadata(historyMessage);
  if (!historyTurn) return true;
  if (isTerminalConversationAgentStatusLifecycle(existingTurn.lifecycle)) {
    return !isTerminalConversationAgentStatusLifecycle(historyTurn.lifecycle)
      || existingTurn.lifecycle !== historyTurn.lifecycle;
  }
  return !isTerminalConversationAgentStatusLifecycle(historyTurn.lifecycle);
}

function mergePreservedAgentTaskMessage(
  historyMessage: ConversationMessageItem,
  existingMessage: ConversationMessageItem,
): ConversationMessageItem {
  const historyTurn = isRecord(historyMessage.metadata.conversation_turn)
    ? historyMessage.metadata.conversation_turn
    : undefined;
  const existingTurn = isRecord(existingMessage.metadata.conversation_turn)
    ? existingMessage.metadata.conversation_turn
    : undefined;
  const persistedActivity = conversationAgentActivityMetadata(historyMessage);
  const mergedTurn = {
    ...(historyTurn ?? {}),
    ...(existingTurn ?? {}),
    ...(persistedActivity === undefined || historyTurn === undefined
      ? {}
      : {
          activity_summary: historyTurn.activity_summary,
          ...(Object.prototype.hasOwnProperty.call(historyTurn, 'activity_summary_fingerprint')
            ? { activity_summary_fingerprint: historyTurn.activity_summary_fingerprint }
            : {}),
        }),
  };
  return {
    ...historyMessage,
    content: historyMessage.content || existingMessage.content,
    model_id: historyMessage.model_id ?? existingMessage.model_id,
    metadata: {
      ...historyMessage.metadata,
      ...existingMessage.metadata,
      conversation_turn: mergedTurn,
    },
  };
}

function mergeExistingActivityIntoHistoryMessage(
  historyMessage: ConversationMessageItem,
  existingMessage: ConversationMessageItem,
): ConversationMessageItem {
  const historyTurn = conversationAgentTurnMetadata(historyMessage);
  const existingTurn = conversationAgentTurnMetadata(existingMessage);
  const existingActivity = conversationAgentActivityMetadata(existingMessage);
  const rawHistoryTurn = historyMessage.metadata.conversation_turn;
  const rawExistingTurn = existingMessage.metadata.conversation_turn;
  if (
    !historyTurn
    || !existingTurn
    || historyTurn.agentTaskId !== existingTurn.agentTaskId
    || !existingActivity
    || !isRecord(rawHistoryTurn)
    || !isRecord(rawExistingTurn)
  ) {
    return historyMessage;
  }
  return {
    ...historyMessage,
    metadata: {
      ...historyMessage.metadata,
      conversation_turn: {
        ...rawHistoryTurn,
        activity_summary: rawExistingTurn.activity_summary,
        ...(Object.prototype.hasOwnProperty.call(rawExistingTurn, 'activity_summary_fingerprint')
          ? { activity_summary_fingerprint: rawExistingTurn.activity_summary_fingerprint }
          : {}),
      },
    },
  };
}

export function applyAgentActivityEvent(
  store: ConversationSessionStore,
  event: WSEvent,
): ConversationSessionStore {
  const activity = parseConversationAgentActivityEvent(event);
  if (activity === undefined || event.summary === undefined) return store;
  const thread = store.threadsByKey[activity.conversationId];
  if (!thread) return store;
  const message = thread.messages.find((candidate) => candidate.id === activity.placeholderMessageId);
  const turn = message ? conversationAgentTurnMetadata(message) : undefined;
  if (
    !message
    || !turn
    || turn.agentTaskId !== activity.agentTaskId
    || !activityLifecycleMatchesTerminalStatus(turn.lifecycle, activity.summary.lifecycle)
  ) {
    return store;
  }
  const currentActivity = conversationAgentActivityMetadata(message);
  if (currentActivity && activityPresentationsMatch(currentActivity, activity.summary)) return store;
  const rawTurn = message.metadata.conversation_turn;
  if (!isRecord(rawTurn)) return store;
  return withThread(store, activity.conversationId, (currentThread) => ({
    ...currentThread,
    messages: currentThread.messages.map((candidate) => (
      candidate.id !== activity.placeholderMessageId
        ? candidate
        : {
            ...candidate,
            metadata: {
              ...candidate.metadata,
              conversation_turn: {
                ...rawTurn,
                activity_summary: event.summary,
              },
            },
          }
    )),
  }));
}

export function mergeHistoryWithInFlightAgentTaskStatus(
  existingMessages: ConversationMessageItem[],
  historyMessages: ConversationMessageItem[],
): ConversationMessageItem[] {
  const existingById = new Map(existingMessages.map((message) => [message.id, message]));
  const historyMessageIds = new Set(historyMessages.map((message) => message.id));
  const mergedHistory = historyMessages.map((historyMessage) => {
    const existingMessage = existingById.get(historyMessage.id);
    if (!existingMessage) return historyMessage;
    return preserveExistingAgentTaskStatus(existingMessage, historyMessage)
      ? mergePreservedAgentTaskMessage(historyMessage, existingMessage)
      : mergeExistingActivityIntoHistoryMessage(historyMessage, existingMessage);
  });
  const unpersistedInFlightMessages = existingMessages.filter((message) => {
    const turn = conversationAgentTurnMetadata(message);
    return Boolean(turn && !isTerminalConversationAgentStatusLifecycle(turn.lifecycle))
      && !historyMessageIds.has(message.id);
  });
  return [...mergedHistory, ...unpersistedInFlightMessages];
}

export function applyAgentStatusEvent(
  store: ConversationSessionStore,
  event: WSEvent & { conversation_id: string; placeholder_message_id: string },
  ownPendingPlaceholderId: string | undefined,
): ConversationSessionStore {
  return withThread(store, event.conversation_id, (thread) => {
    const hasPlaceholder = thread.messages.some((message) => message.id === event.placeholder_message_id);
    if (!hasPlaceholder) {
      const withoutPending = ownPendingPlaceholderId
        ? thread.messages.filter((message) => message.id !== ownPendingPlaceholderId)
        : thread.messages;
      return { ...thread, messages: [...withoutPending, buildAgentTaskPlaceholderMessage(event)] };
    }
    return {
      ...thread,
      messages: thread.messages.map((message) => (
        message.id === event.placeholder_message_id ? mergeAgentStatusIntoMessage(message, event) : message
      )),
    };
  });
}

export function reconcileConnectionLoss(store: ConversationSessionStore): ConversationSessionStore {
  let nextStore = store;
  for (const request of Object.values(store.requestsById)) {
    if (!request.ownedByThisSocket) continue;
    const threadKey = store.requestIdToThreadKey[request.requestId];
    if (threadKey) {
      nextStore = withThread(nextStore, threadKey, (thread) => ({
        ...thread,
        messages: thread.messages.filter((message) => message.id !== `pending-${request.requestId}`),
        persistedFailedSubmission: request.submission,
        responseError: 'Connection closed before the response completed. Your message may already be saved.',
        activeRequestId: thread.activeRequestId === request.requestId ? undefined : thread.activeRequestId,
      }));
    }
    nextStore = clearRequest(nextStore, request.requestId);
  }
  return nextStore;
}
