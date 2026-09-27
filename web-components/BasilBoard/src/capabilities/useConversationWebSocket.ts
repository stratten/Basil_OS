import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';
import type { ConversationConnectionState, WSEvent } from '../contracts';
import { basilBoardWebSocket } from '../services/websocket';
import {
  adoptRequestConversationId,
  applyAgentActivityEvent,
  applyAgentStatusEvent,
  applyTokenToRequest,
  bindAgentTaskToRequest,
  clearRequest,
  markRequestCancelling,
  pendingRequestForConversation,
  reconcileConnectionLoss,
  registerSubmission,
  requestIdForAgentTask,
  withThread,
  type ConversationSessionStore,
} from './conversationSessionState';
import {
  isTerminalConversationAgentStatusLifecycle,
  isValidAgentStatusEvent,
} from './conversationAgentStatusPresentation';

export type { ConversationDraftSubmission } from './conversationSessionState';

import type { ConversationDraftSubmission } from './conversationSessionState';

type ConversationSessionEffect = (
  loadHistory: (conversationId: string) => Promise<void>,
  refreshConversations: () => Promise<void>,
) => void;

function reduceConversationEvent(
  store: ConversationSessionStore,
  event: WSEvent,
): { store: ConversationSessionStore; effects: ConversationSessionEffect[] } {
  const effects: ConversationSessionEffect[] = [];
  const refresh = () => effects.push((_loadHistory, refreshConversations) => void refreshConversations());
  const reload = (conversationId: string) => effects.push((loadHistory) => void loadHistory(conversationId));

  if (event.event_type === 'conversation_agent_status') {
    if (!isValidAgentStatusEvent(event)) return { store, effects };
    const pendingRequest = event.request_id
      ? store.requestsById[event.request_id]
      : pendingRequestForConversation(store, event.conversation_id);
    const ownPendingPlaceholderId = pendingRequest ? `pending-${pendingRequest.requestId}` : undefined;
    let nextStore = store;
    if (pendingRequest && requestIdForAgentTask(nextStore, event.agent_task_id) === undefined) {
      nextStore = bindAgentTaskToRequest(nextStore, pendingRequest.requestId, event.agent_task_id);
      nextStore = adoptRequestConversationId(nextStore, pendingRequest.requestId, event.conversation_id);
      refresh();
    }
    nextStore = applyAgentStatusEvent(nextStore, event, ownPendingPlaceholderId);
    const owningRequestId = requestIdForAgentTask(nextStore, event.agent_task_id);
    if (
      owningRequestId
      && isTerminalConversationAgentStatusLifecycle(event.lifecycle)
      && ['completed', 'failed', 'cancelled'].includes(event.narration_state ?? '')
    ) {
      nextStore = clearRequest(nextStore, owningRequestId);
      refresh();
    }
    return { store: nextStore, effects };
  }

  if (event.event_type === 'conversation_agent_activity') {
    return { store: applyAgentActivityEvent(store, event), effects };
  }

  const requestId = event.request_id;
  const owningThreadKey = requestId ? store.requestIdToThreadKey[requestId] : undefined;

  if (event.event_type === 'conversation_token') {
    if (!requestId || !owningThreadKey) {
      const conversationId = event.conversation_id;
      const messageId = event.message_id;
      if (typeof conversationId === 'string' && typeof messageId === 'string') {
        const thread = store.threadsByKey[conversationId];
        if (thread?.messages.some((message) => message.id === messageId)) {
          const nextStore = withThread(store, conversationId, (current) => ({
            ...current,
            messages: current.messages.map((message) => (
              message.id === messageId
                ? {
                    ...message,
                    content: `${message.content}${typeof event.token === 'string' ? event.token : ''}`,
                    metadata: { ...message.metadata, streaming: !event.is_final },
                  }
                : message
            )),
          }));
          if (event.is_final) refresh();
          return { store: nextStore, effects };
        }
      }
      return { store, effects };
    }
    const result = applyTokenToRequest(store, event);
    if (!result.accepted) {
      if (
        result.request
        && typeof event.chunk_id === 'number'
        && event.chunk_id > result.request.streamState.lastChunkId + 1
      ) {
        let nextStore = withThread(store, owningThreadKey, (thread) => ({
          ...thread,
          responseError: 'Part of the streamed response was missed. Reload the conversation to reconcile it.',
        }));
        if (event.is_final) {
          const conversationId = result.request.conversationId ?? owningThreadKey;
          nextStore = clearRequest(nextStore, requestId);
          reload(conversationId);
        }
        return { store: nextStore, effects };
      }
      return { store, effects };
    }
    let nextStore = result.store;
    if (event.conversation_id && event.conversation_id !== owningThreadKey) {
      nextStore = adoptRequestConversationId(nextStore, requestId, event.conversation_id);
    }
    if (event.is_final) {
      nextStore = clearRequest(nextStore, requestId);
      refresh();
    }
    return { store: nextStore, effects };
  }

  if (event.event_type === 'conversation_message' && typeof event.message === 'string') {
    if (!requestId || !owningThreadKey) return { store, effects };
    const request = store.requestsById[requestId];
    let nextStore = withThread(store, owningThreadKey, (thread) => ({
      ...thread,
      messages: [
        ...thread.messages.filter((message) => message.id !== `pending-${requestId}`),
        {
          id: event.message_id ?? `assistant-${Date.now()}`,
          role: 'assistant' as const,
          content: event.message as string,
          timestamp: new Date().toISOString(),
          model_id: request?.submission.modelId,
          metadata: {},
        },
      ],
    }));
    if (event.conversation_id && event.conversation_id !== owningThreadKey) {
      nextStore = adoptRequestConversationId(nextStore, requestId, event.conversation_id);
    }
    nextStore = clearRequest(nextStore, requestId);
    refresh();
    return { store: nextStore, effects };
  }

  if (event.event_type === 'conversation_cancelled') {
    if (requestId && owningThreadKey) {
      const nextStore = clearRequest(store, requestId);
      refresh();
      if (event.conversation_id) reload(event.conversation_id);
      return { store: nextStore, effects };
    }
    if (event.conversation_id) {
      const observingRequest = Object.values(store.requestsById).find(
        (request) => request.conversationId === event.conversation_id,
      );
      const nextStore = observingRequest ? clearRequest(store, observingRequest.requestId) : store;
      refresh();
      reload(event.conversation_id);
      return { store: nextStore, effects };
    }
    return { store, effects };
  }

  if (event.event_type === 'conversation_cancel_rejected') {
    if (!requestId || !owningThreadKey) return { store, effects };
    let nextStore = withThread(store, owningThreadKey, (thread) => ({
      ...thread,
      responseError: event.message || 'Could not stop the response.',
    }));
    const request = nextStore.requestsById[requestId];
    if (request) {
      nextStore = { ...nextStore, requestsById: { ...nextStore.requestsById, [requestId]: { ...request, cancelling: false } } };
    }
    return { store: nextStore, effects };
  }

  if (event.event_type === 'conversation_error') {
    if (!requestId || !owningThreadKey) return { store, effects };
    let nextStore = store;
    let errorThreadKey = owningThreadKey;
    if (event.conversation_id && event.conversation_id !== owningThreadKey) {
      nextStore = adoptRequestConversationId(nextStore, requestId, event.conversation_id);
      errorThreadKey = nextStore.requestIdToThreadKey[requestId] ?? errorThreadKey;
    }
    const request = nextStore.requestsById[requestId];
    nextStore = withThread(nextStore, errorThreadKey, (thread) => ({
      ...thread,
      messages: thread.messages.filter((message) => message.id !== `pending-${requestId}`),
      persistedFailedSubmission: request?.submission,
      responseError: event.message || 'The response failed. Your message was saved.',
    }));
    nextStore = clearRequest(nextStore, requestId);
    return { store: nextStore, effects };
  }

  return { store, effects };
}

export interface UseConversationWebSocketOptions {
  store: ConversationSessionStore;
  setStore: Dispatch<SetStateAction<ConversationSessionStore>>;
  loadHistory: (conversationId: string) => Promise<void>;
  refreshConversations: () => Promise<void>;
}

export interface UseConversationWebSocketResult {
  connectionState: ConversationConnectionState;
  submit: (threadKey: string, submission: ConversationDraftSubmission) => boolean;
  cancel: (threadKey: string) => boolean;
}

export function useConversationWebSocket({
  store,
  setStore,
  loadHistory,
  refreshConversations,
}: UseConversationWebSocketOptions): UseConversationWebSocketResult {
  const [connectionState, setConnectionState] = useState<ConversationConnectionState>('closed');
  const storeRef = useRef(store);
  storeRef.current = store;
  const loadHistoryRef = useRef(loadHistory);
  loadHistoryRef.current = loadHistory;
  const refreshConversationsRef = useRef(refreshConversations);
  refreshConversationsRef.current = refreshConversations;

  useEffect(() => basilBoardWebSocket.subscribeConnectionState((state) => {
    setConnectionState(state);
    if (state === 'closed') {
      const nextStore = reconcileConnectionLoss(storeRef.current);
      storeRef.current = nextStore;
      setStore(nextStore);
    }
  }), [setStore]);

  useEffect(() => {
    const unsubscribe = basilBoardWebSocket.subscribe((event: WSEvent) => {
      const { store: nextStore, effects } = reduceConversationEvent(storeRef.current, event);
      storeRef.current = nextStore;
      setStore(nextStore);
      for (const effect of effects) effect(loadHistoryRef.current, refreshConversationsRef.current);
    });
    return unsubscribe;
  }, [setStore]);

  const submit = (threadKey: string, submission: ConversationDraftSubmission): boolean => {
    const sent = basilBoardWebSocket.sendConversationMessage(submission);
    if (!sent) return false;
    const nextStore = registerSubmission(storeRef.current, threadKey, submission);
    storeRef.current = nextStore;
    setStore(nextStore);
    return true;
  };

  const cancel = (threadKey: string): boolean => {
    const thread = storeRef.current.threadsByKey[threadKey];
    const requestId = thread?.activeRequestId;
    if (!requestId) return false;
    const request = storeRef.current.requestsById[requestId];
    if (request?.cancelling) return false;
    const sent = basilBoardWebSocket.cancelConversationResponse(requestId, request?.conversationId ?? threadKey);
    if (!sent) return false;
    const nextStore = markRequestCancelling(storeRef.current, requestId);
    storeRef.current = nextStore;
    setStore(nextStore);
    return true;
  };

  return { connectionState, submit, cancel };
}
