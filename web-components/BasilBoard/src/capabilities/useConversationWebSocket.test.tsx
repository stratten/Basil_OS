import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import {
  type ConversationDraftSubmission,
  useConversationWebSocket,
} from './useConversationWebSocket';
import {
  initialConversationSessionStore,
  registerSubmission,
  type ConversationSessionStore,
} from './conversationSessionState';
import { basilBoardWebSocket } from '../services/websocket';
import type { WSEvent } from '../contracts';

vi.mock('../services/websocket', () => {
  const listeners: Array<(event: WSEvent) => void> = [];
  return {
    basilBoardWebSocket: {
      subscribe: (listener: (event: WSEvent) => void) => {
        listeners.push(listener);
        return () => {
          const index = listeners.indexOf(listener);
          if (index >= 0) listeners.splice(index, 1);
        };
      },
      subscribeConnectionState: () => () => {},
      sendConversationMessage: vi.fn(() => true),
      cancelConversationResponse: vi.fn(() => true),
      __emit: (event: WSEvent) => {
        for (const listener of [...listeners]) listener(event);
      },
    },
  };
});

function emit(event: WSEvent | Record<string, unknown>) {
  (basilBoardWebSocket as unknown as { __emit: (event: WSEvent) => void }).__emit(event as unknown as WSEvent);
}

function draftSubmission(requestId: string, conversationId = 'conversation-1'): ConversationDraftSubmission {
  return {
    requestId,
    messageId: 'message-1',
    content: 'Plan my week',
    displayMarkdown: 'Plan my week',
    conversationId,
    filePaths: [],
    delegationOptOut: false,
    source: 'composer',
    editorHtml: 'Plan my week',
  };
}

function activitySummary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    agent_task_id: 'task-1',
    lifecycle: 'processing',
    workflow: {},
    artifacts: [],
    artifact_count: 0,
    verification_status: 'unknown',
    requires_user_attention: false,
    ...overrides,
  };
}

function renderConversationWebSocket(initialStore = initialConversationSessionStore()) {
  const refreshConversations = vi.fn().mockResolvedValue(undefined);
  const loadHistory = vi.fn().mockResolvedValue(undefined);
  let latestStore = initialStore;

  const { result } = renderHook(() => {
    const [store, setStore] = useState<ConversationSessionStore>(initialStore);
    latestStore = store;
    const hook = useConversationWebSocket({
      store,
      setStore,
      loadHistory,
      refreshConversations,
    });
    return { ...hook, store };
  });

  return {
    result,
    getStore: () => latestStore,
    refreshConversations,
    loadHistory,
  };
}

describe('useConversationWebSocket', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('routes tokens to the registered request thread and clears the request on final token', () => {
    const registered = registerSubmission(
      initialConversationSessionStore(),
      'conversation-1',
      draftSubmission('request-1'),
    );
    const { getStore, refreshConversations } = renderConversationWebSocket(registered);

    act(() => {
      emit({
        event_type: 'conversation_token',
        request_id: 'request-1',
        conversation_id: 'conversation-1',
        message_id: 'assistant-1',
        token: 'Hello',
        chunk_id: 0,
        is_final: false,
      });
    });

    expect(getStore().requestsById['request-1'].streamState.content).toBe('Hello');
    expect(getStore().threadsByKey['conversation-1'].messages.find((message) => message.id === 'assistant-1')?.content).toBe('Hello');

    act(() => {
      emit({
        event_type: 'conversation_token',
        request_id: 'request-1',
        conversation_id: 'conversation-1',
        message_id: 'assistant-1',
        token: '',
        chunk_id: 1,
        is_final: true,
      });
    });

    expect(getStore().requestsById['request-1']).toBeUndefined();
    expect(refreshConversations).toHaveBeenCalled();
  });

  it('adopts a durable conversation ID from an agent status event for the pending request', () => {
    const registered = registerSubmission(
      initialConversationSessionStore(),
      '__draft__',
      draftSubmission('request-1', undefined),
    );
    const { getStore, refreshConversations } = renderConversationWebSocket(registered);

    act(() => {
      emit({
        event_type: 'conversation_agent_status',
        request_id: 'request-1',
        conversation_id: 'created-conversation',
        placeholder_message_id: 'assistant-1',
        agent_task_id: 'task-1',
        lifecycle: 'pending',
        status_text: 'Agent task is gathering context.',
      });
    });

    expect(getStore().requestIdToThreadKey['request-1']).toBe('created-conversation');
    expect(getStore().requestsById['request-1'].agentTaskId).toBe('task-1');
    expect(refreshConversations).toHaveBeenCalled();
  });

  it('ignores tokens that do not match a registered request', () => {
    const { getStore } = renderConversationWebSocket();

    act(() => {
      emit({
        event_type: 'conversation_token',
        request_id: 'unknown-request',
        conversation_id: 'conversation-1',
        message_id: 'assistant-1',
        token: 'Hello',
        chunk_id: 0,
        is_final: false,
      });
    });

    expect(getStore().requestsById['unknown-request']).toBeUndefined();
  });

  it('reduces activity only after the status event has established its linked placeholder', () => {
    const registered = registerSubmission(
      initialConversationSessionStore(),
      'conversation-1',
      draftSubmission('request-1'),
    );
    const { getStore, refreshConversations, loadHistory } = renderConversationWebSocket(registered);

    act(() => {
      emit({
        event_type: 'conversation_agent_status',
        request_id: 'request-1',
        conversation_id: 'conversation-1',
        placeholder_message_id: 'assistant-1',
        agent_task_id: 'task-1',
        lifecycle: 'running',
        status_text: 'Agent task is working.',
      });
      emit({
        event_type: 'conversation_agent_activity',
        conversation_id: 'conversation-1',
        placeholder_message_id: 'assistant-1',
        agent_task_id: 'task-1',
        summary: activitySummary(),
      });
    });

    expect(getStore().threadsByKey['conversation-1'].messages.find((message) => message.id === 'assistant-1')?.metadata.conversation_turn)
      .toMatchObject({ activity_summary: activitySummary() });
    expect(refreshConversations).toHaveBeenCalledTimes(1);
    expect(loadHistory).not.toHaveBeenCalled();
  });

  it('does not create a placeholder or bind a request for early or unrelated activity', () => {
    const registered = registerSubmission(
      initialConversationSessionStore(),
      'conversation-1',
      draftSubmission('request-1'),
    );
    const { getStore, refreshConversations, loadHistory } = renderConversationWebSocket(registered);

    act(() => {
      emit({
        event_type: 'conversation_agent_activity',
        conversation_id: 'conversation-1',
        placeholder_message_id: 'assistant-1',
        agent_task_id: 'task-1',
        summary: activitySummary(),
      });
    });

    expect(getStore().threadsByKey['conversation-1']?.messages).toEqual([]);
    expect(getStore().requestsById['request-1'].agentTaskId).toBeUndefined();
    expect(refreshConversations).not.toHaveBeenCalled();
    expect(loadHistory).not.toHaveBeenCalled();
  });

  it('ignores a stale activity event after terminal status without changing request completion', () => {
    const registered = registerSubmission(
      initialConversationSessionStore(),
      'conversation-1',
      draftSubmission('request-1'),
    );
    const { getStore } = renderConversationWebSocket(registered);

    act(() => {
      emit({
        event_type: 'conversation_agent_status',
        request_id: 'request-1',
        conversation_id: 'conversation-1',
        placeholder_message_id: 'assistant-1',
        agent_task_id: 'task-1',
        lifecycle: 'completed',
        narration_state: 'completed',
      });
      emit({
        event_type: 'conversation_agent_activity',
        conversation_id: 'conversation-1',
        placeholder_message_id: 'assistant-1',
        agent_task_id: 'task-1',
        summary: activitySummary({ lifecycle: 'processing' }),
      });
    });

    expect(getStore().requestsById['request-1']).toBeUndefined();
    expect(getStore().threadsByKey['conversation-1'].messages.find((message) => message.id === 'assistant-1')?.metadata.conversation_turn)
      .not.toHaveProperty('activity_summary');
  });
});
