import { describe, expect, it } from 'vitest';
import type { ConversationMessageItem, WSEvent } from '../contracts';
import {
  conversationAgentActivityMetadata,
  parseConversationAgentActivityEvent,
  parseConversationAgentActivitySummary,
} from './conversationAgentActivityPresentation';

function summary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    agent_task_id: 'task-1',
    lifecycle: 'processing',
    latest_activity: 'Writing the requested report.',
    workflow: { completed_steps: 1, total_steps: 3 },
    artifacts: [
      {
        artifact_id: 'artifact-1',
        display_name: 'report.md',
        artifact_kind: 'file',
        lifecycle: 'ready',
        verification: { status: 'unknown' },
      },
    ],
    artifact_count: 1,
    verification_status: 'unknown',
    requires_user_attention: false,
    ...overrides,
  };
}

function activityEvent(overrides: Record<string, unknown> = {}): WSEvent {
  return {
    event_type: 'conversation_agent_activity',
    conversation_id: 'conversation-1',
    placeholder_message_id: 'assistant-1',
    agent_task_id: 'task-1',
    summary: summary(),
    ...overrides,
  } as unknown as WSEvent;
}

function agentTaskMessage(
  activitySummary: unknown,
  agentTaskId = 'task-1',
): ConversationMessageItem {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: '',
    timestamp: '2026-08-09T12:00:00Z',
    metadata: {
      conversation_turn: {
        route: 'agent_task',
        lifecycle: 'running',
        agent_task_id: agentTaskId,
        status_text: 'Agent task is working.',
        narration: { lifecycle: 'pending' },
        activity_summary: activitySummary,
      },
    },
  };
}

describe('conversationAgentActivityPresentation', () => {
  it('parses the complete selected live event into camelCase presentation state', () => {
    expect(parseConversationAgentActivityEvent(activityEvent())).toEqual({
      conversationId: 'conversation-1',
      placeholderMessageId: 'assistant-1',
      agentTaskId: 'task-1',
      summary: {
        agentTaskId: 'task-1',
        lifecycle: 'processing',
        latestActivity: 'Writing the requested report.',
        workflow: { completedSteps: 1, totalSteps: 3 },
        artifacts: [{
          artifactId: 'artifact-1',
          displayName: 'report.md',
          artifactKind: 'file',
          lifecycle: 'ready',
          verificationStatus: 'unknown',
        }],
        artifactCount: 1,
        verificationStatus: 'unknown',
        requiresUserAttention: false,
      },
    });
  });

  it('parses a durable summary only when it belongs to the existing linked task', () => {
    expect(conversationAgentActivityMetadata(agentTaskMessage(summary()))).toMatchObject({
      agentTaskId: 'task-1',
      latestActivity: 'Writing the requested report.',
      artifactCount: 1,
    });
    expect(conversationAgentActivityMetadata(agentTaskMessage(summary({ agent_task_id: 'other-task' })))).toBeUndefined();
    expect(conversationAgentActivityMetadata({
      id: 'assistant-1', role: 'assistant', content: '', timestamp: 't', metadata: {},
    })).toBeUndefined();
  });

  it('rejects missing, malformed, and cross-linked live identities', () => {
    for (const invalidEvent of [
      activityEvent({ conversation_id: '' }),
      activityEvent({ placeholder_message_id: '  ' }),
      activityEvent({ agent_task_id: undefined }),
      activityEvent({ summary: summary({ agent_task_id: 'other-task' }) }),
      activityEvent({ event_type: 'conversation_agent_status' }),
      activityEvent({ summary: undefined }),
    ]) {
      expect(parseConversationAgentActivityEvent(invalidEvent)).toBeUndefined();
    }
  });

  it('accepts an empty workflow and zero artifacts', () => {
    const raw = summary({
      workflow: {},
      artifacts: [],
      artifact_count: 0,
    });
    delete raw.latest_activity;
    const parsed = parseConversationAgentActivitySummary(raw);

    expect(parsed).toEqual({
      agentTaskId: 'task-1',
      lifecycle: 'processing',
      workflow: {},
      artifacts: [],
      artifactCount: 0,
      verificationStatus: 'unknown',
      requiresUserAttention: false,
    });
  });

  it('accepts exactly six artifacts and rejects seven', () => {
    const artifacts = Array.from({ length: 6 }, (_, index) => ({
      artifact_id: `artifact-${index + 1}`,
      display_name: `report-${index + 1}.md`,
      artifact_kind: 'file',
      lifecycle: 'ready',
      verification: { status: 'unknown' },
    }));
    expect(parseConversationAgentActivitySummary(summary({ artifacts, artifact_count: 6 }))?.artifacts).toHaveLength(6);
    expect(parseConversationAgentActivitySummary(summary({
      artifacts: [...artifacts, {
        artifact_id: 'artifact-7',
        display_name: 'report-7.md',
        artifact_kind: 'file',
        lifecycle: 'ready',
        verification: { status: 'unknown' },
      }],
      artifact_count: 7,
    }))).toBeUndefined();
  });

  it('rejects malformed workflow counts and invalid artifact count relationships', () => {
    for (const invalidSummary of [
      summary({ workflow: { completed_steps: 1 } }),
      summary({ workflow: { completed_steps: 4, total_steps: 3 } }),
      summary({ workflow: { completed_steps: true, total_steps: 3 } }),
      summary({ artifact_count: true }),
      summary({ artifact_count: 0 }),
    ]) {
      expect(parseConversationAgentActivitySummary(invalidSummary)).toBeUndefined();
    }
  });

  it('rejects unsupported lifecycle, kind, and verification vocabulary', () => {
    for (const invalidSummary of [
      summary({ lifecycle: 'unknown' }),
      summary({ verification_status: 'verified' }),
      summary({ artifacts: [{
        artifact_id: 'artifact-1',
        display_name: 'report.md',
        artifact_kind: 'image',
        lifecycle: 'ready',
        verification: { status: 'unknown' },
      }] }),
      summary({ artifacts: [{
        artifact_id: 'artifact-1',
        display_name: 'report.md',
        artifact_kind: 'file',
        lifecycle: 'ready',
        verification: { status: 'unverified' },
      }] }),
    ]) {
      expect(parseConversationAgentActivitySummary(invalidSummary)).toBeUndefined();
    }
  });

  it('rejects invalid optional text and over-limit identifiers without truncating them', () => {
    expect(parseConversationAgentActivitySummary(summary({ latest_activity: 'x'.repeat(241) }))).toBeUndefined();
    expect(parseConversationAgentActivitySummary(summary({ latest_activity: 12 }))).toBeUndefined();
    expect(parseConversationAgentActivitySummary(summary({ agent_task_id: 'x'.repeat(257) }))).toBeUndefined();
    expect(parseConversationAgentActivityEvent(activityEvent({ conversation_id: 'x'.repeat(257) }))).toBeUndefined();
    expect(parseConversationAgentActivityEvent(activityEvent({ placeholder_message_id: 'x'.repeat(257) }))).toBeUndefined();
    expect(parseConversationAgentActivitySummary(summary({ artifacts: [{
      artifact_id: 'x'.repeat(257),
      display_name: 'report.md',
      artifact_kind: 'file',
      lifecycle: 'ready',
      verification: { status: 'unknown' },
    }] }))).toBeUndefined();
  });

  it('rejects raw and unknown fields instead of passing them to later reducer or UI layers', () => {
    expect(parseConversationAgentActivitySummary(summary({ local_path: '/private/report.md' }))).toBeUndefined();
    expect(parseConversationAgentActivitySummary(summary({
      workflow: { completed_steps: 1, total_steps: 3, source_timeline_entry_id: 'timeline-1' },
    }))).toBeUndefined();
    expect(parseConversationAgentActivitySummary(summary({ artifacts: [{
      artifact_id: 'artifact-1',
      display_name: 'report.md',
      artifact_kind: 'file',
      lifecycle: 'ready',
      local_path: '/private/report.md',
      verification: { status: 'unknown' },
    }] }))).toBeUndefined();
    expect(parseConversationAgentActivitySummary(summary({ artifacts: [{
      artifact_id: 'artifact-1',
      display_name: 'report.md',
      artifact_kind: 'file',
      lifecycle: 'ready',
      verification: { status: 'unknown', summary: 'raw evidence' },
    }] }))).toBeUndefined();
  });

  it('accepts a paused task lifecycle', () => {
    expect(parseConversationAgentActivitySummary(summary({ lifecycle: 'paused' }))).toBeDefined();
  });

  it('does not require activity lifecycle to duplicate the linked status lifecycle', () => {
    expect(conversationAgentActivityMetadata(agentTaskMessage(summary({ lifecycle: 'completed' })))).toMatchObject({
      lifecycle: 'completed',
    });
  });
});
