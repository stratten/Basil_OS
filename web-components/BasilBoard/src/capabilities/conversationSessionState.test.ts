import { describe, expect, it } from 'vitest';
import type { ConversationMessageItem } from '../contracts';
import type { ConversationDraftSubmission } from './conversationSessionState';
import {
  activeConversationIds,
  adoptRequestConversationId,
  applyAgentActivityEvent,
  applyTokenToRequest,
  clearRequest,
  createDraftThreadSession,
  DRAFT_THREAD_KEY,
  initialConversationSessionStore,
  mergeHistoryWithInFlightAgentTaskStatus,
  pendingConversationThreadKey,
  reconcileConnectionLoss,
  registerSubmission,
} from './conversationSessionState';

function submission(overrides: Partial<ConversationDraftSubmission> = {}): ConversationDraftSubmission {
  return {
    requestId: 'request-1',
    messageId: 'message-1',
    content: 'Hello',
    displayMarkdown: 'Hello',
    conversationId: undefined,
    modelId: 'model-1',
    filePaths: [],
    delegationOptOut: false,
    source: 'composer',
    editorHtml: 'Hello',
    ...overrides,
  };
}

function activitySummary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    agent_task_id: 'task-1',
    lifecycle: 'processing',
    latest_activity: 'Writing the requested report.',
    workflow: { completed_steps: 1, total_steps: 3 },
    artifacts: [{
      artifact_id: 'artifact-1',
      display_name: 'report.md',
      artifact_kind: 'file',
      lifecycle: 'ready',
      verification: { status: 'unknown' },
    }],
    artifact_count: 1,
    verification_status: 'unknown',
    requires_user_attention: false,
    ...overrides,
  };
}

function activityEvent(overrides: Record<string, unknown> = {}) {
  return {
    event_type: 'conversation_agent_activity',
    conversation_id: 'conversation-1',
    placeholder_message_id: 'assistant-agent-1',
    agent_task_id: 'task-1',
    summary: activitySummary(),
    ...overrides,
  };
}

function agentTaskMessage(overrides: Record<string, unknown> = {}): ConversationMessageItem {
  return {
    id: 'assistant-agent-1',
    role: 'assistant',
    content: '',
    timestamp: '2026-08-09T12:00:00Z',
    metadata: {
      conversation_turn: {
        route: 'agent_task',
        lifecycle: 'running',
        agent_task_id: 'task-1',
        status_text: 'Agent task is working.',
        narration: { lifecycle: 'pending' },
        ...overrides,
      },
    },
  };
}

describe('conversationSessionState', () => {
  it('registers a submission under the draft key and marks the thread active', () => {
    const store = registerSubmission(initialConversationSessionStore(), DRAFT_THREAD_KEY, submission());

    expect(store.threadsByKey[DRAFT_THREAD_KEY].activeRequestId).toBe('request-1');
    expect(store.requestsById['request-1'].requestId).toBe('request-1');
    expect(activeConversationIds(store)).toEqual(new Set());
  });

  it('adopts a durable conversation ID and migrates the draft thread state', () => {
    const registered = registerSubmission(initialConversationSessionStore(), DRAFT_THREAD_KEY, submission());
    const adopted = adoptRequestConversationId(registered, 'request-1', 'conversation-1');

    expect(adopted.threadsByKey[DRAFT_THREAD_KEY]).toBeUndefined();
    expect(adopted.threadsByKey['conversation-1'].activeRequestId).toBe('request-1');
    expect(adopted.requestIdToThreadKey['request-1']).toBe('conversation-1');
    expect(activeConversationIds(adopted)).toEqual(new Set(['conversation-1']));
  });

  it('moves an outgoing draft into a request-scoped thread so a new draft remains independent', () => {
    const threadKey = pendingConversationThreadKey('request-1');
    const registered = registerSubmission(
      initialConversationSessionStore(),
      threadKey,
      submission(),
    );

    expect(registered.threadsByKey[DRAFT_THREAD_KEY]).toBeUndefined();
    expect(registered.threadsByKey[threadKey].activeRequestId).toBe('request-1');
    expect(registered.requestIdToThreadKey['request-1']).toBe(threadKey);
  });

  it('isolates tokens between two independent requests', () => {
    let store = registerSubmission(initialConversationSessionStore(), 'conversation-1', submission({
      requestId: 'request-a',
      conversationId: 'conversation-1',
    }));
    store = registerSubmission(store, 'conversation-2', submission({
      requestId: 'request-b',
      conversationId: 'conversation-2',
    }));

    const afterA = applyTokenToRequest(store, {
      event_type: 'conversation_token',
      request_id: 'request-a',
      conversation_id: 'conversation-1',
      message_id: 'assistant-a',
      chunk_id: 0,
      token: 'Alpha chunk',
      is_final: false,
    } as never);
    expect(afterA.accepted).toBe(true);
    const afterB = applyTokenToRequest(afterA.store, {
      event_type: 'conversation_token',
      request_id: 'request-b',
      conversation_id: 'conversation-2',
      message_id: 'assistant-b',
      chunk_id: 0,
      token: 'Beta chunk',
      is_final: false,
    } as never);
    expect(afterB.accepted).toBe(true);

    expect(afterB.store.requestsById['request-a'].streamState.content).toBe('Alpha chunk');
    expect(afterB.store.requestsById['request-b'].streamState.content).toBe('Beta chunk');
    expect(afterB.store.threadsByKey['conversation-1'].messages.find((message) => message.id === 'assistant-a')?.content).toBe('Alpha chunk');
    expect(afterB.store.threadsByKey['conversation-2'].messages.find((message) => message.id === 'assistant-b')?.content).toBe('Beta chunk');
  });

  it('rejects a duplicate chunk ID without mutating state', () => {
    const registered = registerSubmission(initialConversationSessionStore(), 'conversation-1', submission({
      requestId: 'request-a',
      conversationId: 'conversation-1',
    }));
    const first = applyTokenToRequest(registered, {
      event_type: 'conversation_token',
      request_id: 'request-a',
      conversation_id: 'conversation-1',
      message_id: 'assistant-a',
      chunk_id: 0,
      token: 'One',
      is_final: false,
    } as never);
    const duplicate = applyTokenToRequest(first.store, {
      event_type: 'conversation_token',
      request_id: 'request-a',
      conversation_id: 'conversation-1',
      message_id: 'assistant-a',
      chunk_id: 0,
      token: 'One again',
      is_final: false,
    } as never);

    expect(duplicate.accepted).toBe(false);
    expect(duplicate.store).toBe(first.store);
  });

  it('clears a terminal request while leaving unrelated requests untouched', () => {
    let store = registerSubmission(initialConversationSessionStore(), 'conversation-1', submission({
      requestId: 'request-a',
      conversationId: 'conversation-1',
    }));
    store = registerSubmission(store, 'conversation-2', submission({
      requestId: 'request-b',
      conversationId: 'conversation-2',
    }));

    const cleared = clearRequest(store, 'request-a');

    expect(cleared.requestsById['request-a']).toBeUndefined();
    expect(cleared.threadsByKey['conversation-1'].activeRequestId).toBeUndefined();
    expect(cleared.requestsById['request-b']).toBeDefined();
    expect(cleared.threadsByKey['conversation-2'].activeRequestId).toBe('request-b');
  });

  it('preserves an in-flight Agent Task status when stale history replaces the selected thread', () => {
    const existingMessages: ConversationMessageItem[] = [{
      id: 'assistant-agent-1',
      role: 'assistant',
      content: '',
      timestamp: '2026-08-03T12:00:00Z',
      metadata: {
        conversation_turn: {
          route: 'agent_task',
          lifecycle: 'running',
          agent_task_id: 'task-1',
          status_text: 'Agent task is working.',
          narration: { lifecycle: 'pending' },
        },
      },
    }];
    const historyMessages: ConversationMessageItem[] = [{
      id: 'assistant-agent-1',
      role: 'assistant',
      content: '',
      timestamp: '2026-08-03T12:00:00Z',
      metadata: {},
    }];

    const merged = mergeHistoryWithInFlightAgentTaskStatus(existingMessages, historyMessages);

    expect(merged).toHaveLength(1);
    expect(merged[0].metadata.conversation_turn).toMatchObject({
      lifecycle: 'running',
      agent_task_id: 'task-1',
      status_text: 'Agent task is working.',
    });
  });

  it('reconciles a dropped connection by restoring the draft and clearing the pending placeholder', () => {
    const registered = registerSubmission(initialConversationSessionStore(), 'conversation-1', submission({
      requestId: 'request-a',
      conversationId: 'conversation-1',
    }));

    const reconciled = reconcileConnectionLoss(registered);

    expect(reconciled.requestsById['request-a']).toBeUndefined();
    expect(reconciled.threadsByKey['conversation-1'].activeRequestId).toBeUndefined();
    expect(reconciled.threadsByKey['conversation-1'].persistedFailedSubmission?.requestId).toBe('request-a');
    expect(reconciled.threadsByKey['conversation-1'].responseError).toContain('Connection closed');
  });

  it('reduces a valid activity event into its existing linked placeholder only', () => {
    const store = {
      ...initialConversationSessionStore(),
      threadsByKey: {
        'conversation-1': {
          ...createDraftThreadSession('conversation-1'),
          messages: [agentTaskMessage()],
        },
      },
    };

    const reduced = applyAgentActivityEvent(store, activityEvent() as never);

    expect(reduced.threadsByKey['conversation-1'].messages[0].metadata.conversation_turn).toMatchObject({
      lifecycle: 'running',
      agent_task_id: 'task-1',
      activity_summary: activitySummary(),
    });
  });

  it('ignores malformed, unrelated, duplicate, and terminal-regressing activity events', () => {
    const linkedStore = {
      ...initialConversationSessionStore(),
      threadsByKey: {
        'conversation-1': {
          ...createDraftThreadSession('conversation-1'),
          messages: [agentTaskMessage()],
        },
      },
    };
    const reduced = applyAgentActivityEvent(linkedStore, activityEvent() as never);
    const duplicate = applyAgentActivityEvent(reduced, activityEvent() as never);
    const unrelated = applyAgentActivityEvent(linkedStore, activityEvent({ placeholder_message_id: 'missing' }) as never);
    const malformed = applyAgentActivityEvent(linkedStore, activityEvent({ summary: { agent_task_id: 'task-1' } }) as never);
    const terminalStore = {
      ...linkedStore,
      threadsByKey: {
        'conversation-1': {
          ...linkedStore.threadsByKey['conversation-1'],
          messages: [agentTaskMessage({ lifecycle: 'completed' })],
        },
      },
    };
    const terminalRegression = applyAgentActivityEvent(terminalStore, activityEvent() as never);
    const matchingTerminal = applyAgentActivityEvent(
      terminalStore,
      activityEvent({ summary: activitySummary({ lifecycle: 'completed' }) }) as never,
    );

    expect(duplicate).toBe(reduced);
    expect(unrelated).toBe(linkedStore);
    expect(malformed).toBe(linkedStore);
    expect(terminalRegression).toBe(terminalStore);
    expect(matchingTerminal.threadsByKey['conversation-1'].messages[0].metadata.conversation_turn)
      .toMatchObject({ activity_summary: activitySummary({ lifecycle: 'completed' }) });
  });

  it('uses a valid durable summary to reconcile an in-memory activity summary during history load', () => {
    const existingMessages = [agentTaskMessage({
      activity_summary: activitySummary({ latest_activity: 'Older live activity.' }),
    })];
    const historyMessages = [agentTaskMessage({
      activity_summary: activitySummary({ latest_activity: 'Durable activity.' }),
    })];

    const merged = mergeHistoryWithInFlightAgentTaskStatus(existingMessages, historyMessages);

    expect(merged[0].metadata.conversation_turn).toMatchObject({
      lifecycle: 'running',
      activity_summary: activitySummary({ latest_activity: 'Durable activity.' }),
    });
  });

  it('preserves a valid in-memory activity summary when a stale history response has none', () => {
    const existingMessages = [agentTaskMessage({ activity_summary: activitySummary() })];
    const historyMessages = [agentTaskMessage()];

    const merged = mergeHistoryWithInFlightAgentTaskStatus(existingMessages, historyMessages);

    expect(merged[0].metadata.conversation_turn).toMatchObject({ activity_summary: activitySummary() });
  });

  it('preserves a valid in-memory activity summary when terminal history lacks one', () => {
    const existingMessages = [agentTaskMessage({ activity_summary: activitySummary() })];
    const historyMessages = [agentTaskMessage({ lifecycle: 'completed' })];

    const merged = mergeHistoryWithInFlightAgentTaskStatus(existingMessages, historyMessages);

    expect(merged[0].metadata.conversation_turn).toMatchObject({
      lifecycle: 'completed',
      activity_summary: activitySummary(),
    });
  });
});
