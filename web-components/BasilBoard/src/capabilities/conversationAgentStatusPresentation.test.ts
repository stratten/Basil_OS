import { describe, expect, it } from 'vitest';
import type { ConversationMessageItem, WSEvent } from '../contracts';
import {
  buildAgentTaskPlaceholderMessage,
  conversationAgentTurnMetadata,
  isTerminalConversationAgentStatusLifecycle,
  isValidAgentStatusEvent,
  mergeAgentStatusIntoMessage,
  shouldShowAgentTaskStatusCard,
} from './conversationAgentStatusPresentation';

function agentMessage(
  overrides: Partial<Record<string, unknown>> = {},
  content = '',
): ConversationMessageItem {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content,
    timestamp: '2026-07-30T12:00:00Z',
    metadata: {
      conversation_turn: {
        route: 'agent_task',
        lifecycle: 'running',
        agent_task_id: 'task-1',
        terminal_outcome: null,
        status_text: 'Agent task is working.',
        ...overrides,
      },
    },
  };
}

function statusEvent(overrides: Partial<WSEvent> = {}): WSEvent {
  return {
    event_type: 'conversation_agent_status',
    conversation_id: 'conversation-1',
    placeholder_message_id: 'assistant-1',
    agent_task_id: 'task-1',
    lifecycle: 'running',
    status_text: 'Agent task is working.',
    ...overrides,
  };
}

describe('conversationAgentStatusPresentation', () => {
  it('extracts valid agent_task metadata and rejects malformed shapes', () => {
    expect(conversationAgentTurnMetadata(agentMessage())).toEqual({
      route: 'agent_task',
      lifecycle: 'running',
      agentTaskId: 'task-1',
      statusText: 'Agent task is working.',
      terminalOutcome: undefined,
      requiresUserAttention: false,
      attentionId: undefined,
    });
    expect(conversationAgentTurnMetadata(agentMessage({ route: 'direct' }))).toBeUndefined();
    expect(conversationAgentTurnMetadata(agentMessage({ lifecycle: 'bogus' }))).toBeUndefined();
    expect(conversationAgentTurnMetadata(agentMessage({ agent_task_id: '' }))).toBeUndefined();
    expect(conversationAgentTurnMetadata({
      id: 'x', role: 'assistant', content: '', timestamp: 't', metadata: {},
    })).toBeUndefined();
  });

  it('retains the status card as provenance after narration content arrives', () => {
    expect(shouldShowAgentTaskStatusCard(agentMessage())).toBe(true);
    expect(shouldShowAgentTaskStatusCard(agentMessage({}, 'Narration has started'))).toBe(true);
  });

  it('validates conversation_agent_status events strictly', () => {
    expect(isValidAgentStatusEvent(statusEvent())).toBe(true);
    expect(isValidAgentStatusEvent(statusEvent({ conversation_id: undefined }))).toBe(false);
    expect(isValidAgentStatusEvent(statusEvent({ placeholder_message_id: '' }))).toBe(false);
    expect(isValidAgentStatusEvent(statusEvent({ agent_task_id: undefined }))).toBe(false);
    expect(isValidAgentStatusEvent(statusEvent({ lifecycle: 'unknown' }))).toBe(false);
    expect(isValidAgentStatusEvent({ event_type: 'conversation_token' })).toBe(false);
  });

  it('builds a durable-shaped placeholder message from a valid event', () => {
    const built = buildAgentTaskPlaceholderMessage(statusEvent({ terminal_outcome: 'Done' }));
    expect(built.id).toBe('assistant-1');
    expect(built.role).toBe('assistant');
    expect(built.content).toBe('');
    expect(built.metadata.conversation_turn).toEqual({
      route: 'agent_task',
      lifecycle: 'running',
      agent_task_id: 'task-1',
      terminal_outcome: 'Done',
      status_text: 'Agent task is working.',
      requires_user_attention: false,
      narration: { lifecycle: 'pending' },
    });
  });

  it('throws when building a placeholder from an invalid event', () => {
    expect(() => buildAgentTaskPlaceholderMessage(statusEvent({ agent_task_id: undefined })))
      .toThrow();
  });

  it('merges a later status update into an existing message', () => {
    const merged = mergeAgentStatusIntoMessage(
      agentMessage(),
      statusEvent({ lifecycle: 'completed', terminal_outcome: 'Agent task completed.', status_text: undefined }),
    );
    expect(conversationAgentTurnMetadata(merged)?.lifecycle).toBe('completed');
    expect(conversationAgentTurnMetadata(merged)?.terminalOutcome).toBe('Agent task completed.');
  });

  it('retains durable activity metadata when a terminal status arrives later', () => {
    const activitySummary = {
      agent_task_id: 'task-1',
      lifecycle: 'completed',
      workflow: { completed_steps: 1, total_steps: 1 },
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
    };
    const merged = mergeAgentStatusIntoMessage(
      agentMessage({ activity_summary: activitySummary, activity_summary_fingerprint: 'fingerprint-1' }),
      statusEvent({ lifecycle: 'completed', terminal_outcome: 'Agent task completed.' }),
    );

    expect(merged.metadata.conversation_turn).toMatchObject({
      lifecycle: 'completed',
      activity_summary: activitySummary,
      activity_summary_fingerprint: 'fingerprint-1',
    });
  });

  it('ignores a stale non-terminal event once the message is already terminal', () => {
    const terminalMessage = agentMessage({ lifecycle: 'completed', terminal_outcome: 'Agent task completed.' });
    const merged = mergeAgentStatusIntoMessage(terminalMessage, statusEvent({ lifecycle: 'running' }));
    expect(merged).toBe(terminalMessage);
  });

  it('ignores a status event for a different Agent Task', () => {
    const message = agentMessage();
    const merged = mergeAgentStatusIntoMessage(
      message,
      statusEvent({ agent_task_id: 'other-task', lifecycle: 'completed' }),
    );
    expect(merged).toBe(message);
  });

  it('accepts a duplicate terminal event as a harmless no-op update', () => {
    const terminalMessage = agentMessage({ lifecycle: 'failed', terminal_outcome: 'Agent task failed.' });
    const merged = mergeAgentStatusIntoMessage(
      terminalMessage,
      statusEvent({ lifecycle: 'failed', terminal_outcome: 'Agent task failed.' }),
    );
    expect(conversationAgentTurnMetadata(merged)?.lifecycle).toBe('failed');
  });

  it('returns the original message unchanged for an invalid event', () => {
    const message = agentMessage();
    expect(mergeAgentStatusIntoMessage(message, statusEvent({ lifecycle: 'unknown' }))).toBe(message);
  });

  it('classifies terminal lifecycles', () => {
    expect(isTerminalConversationAgentStatusLifecycle('completed')).toBe(true);
    expect(isTerminalConversationAgentStatusLifecycle('failed')).toBe(true);
    expect(isTerminalConversationAgentStatusLifecycle('canceled')).toBe(true);
    expect(isTerminalConversationAgentStatusLifecycle('running')).toBe(false);
    expect(isTerminalConversationAgentStatusLifecycle('pending')).toBe(false);
  });

  it('round-trips a valid attention marker through placeholder metadata', () => {
    const event = statusEvent({
      requires_user_attention: true,
      attention_id: 'checkpoint-2',
      status_text: 'Agent task needs your input.',
    });

    const built = buildAgentTaskPlaceholderMessage(event);

    expect(conversationAgentTurnMetadata(built)).toMatchObject({
      agentTaskId: 'task-1',
      requiresUserAttention: true,
      attentionId: 'checkpoint-2',
    });
  });

  it('rejects malformed or orphaned attention fields', () => {
    expect(isValidAgentStatusEvent(statusEvent({
      requires_user_attention: 'true' as unknown as boolean,
    }))).toBe(false);
    expect(isValidAgentStatusEvent(statusEvent({
      requires_user_attention: false,
      attention_id: 'checkpoint-2',
    }))).toBe(false);
    expect(isValidAgentStatusEvent(statusEvent({
      requires_user_attention: true,
      attention_id: '',
    }))).toBe(false);
    expect(isValidAgentStatusEvent(statusEvent({
      requires_user_attention: true,
    }))).toBe(false);
  });
});
