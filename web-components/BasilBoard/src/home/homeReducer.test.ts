import { describe, expect, it } from 'vitest';
import type { HomeTimelineItem } from '../contracts';
import {
  applyHydrationTimeline,
  applyReconciledTurn,
  applyTurnResponse,
  applyWsEvent,
  isTerminalAgentTaskEvent,
  rejectUnknownTabKind,
} from './homeReducer';

describe('homeReducer', () => {
  it('hydrates timeline from server payload', () => {
    const timeline: HomeTimelineItem[] = [
      { kind: 'user_message', messageId: 'u1', content: 'Hello', createdAt: '2026-01-01T00:00:00Z' },
    ];
    const state = applyHydrationTimeline(timeline);
    expect(state.timeline).toHaveLength(1);
  });

  it('adds conversation answer from turn response', () => {
    const base = applyHydrationTimeline([]);
    const optimisticUser = {
      kind: 'user_message' as const,
      messageId: 'u1',
      content: 'Hello',
      displayMarkdown: '**Hello**',
      referencePaths: ['/tmp/a.txt'],
      createdAt: '2026-01-01T00:00:00Z',
    };
    const next = applyTurnResponse(base, {
      inquiry_id: 'inq-1',
      user_message_id: 'u1',
      route_kind: 'conversation',
      route_reason: 'Direct chat',
      route_confidence: 0.9,
      state: 'completed',
      assistant_message_id: 'a1',
      assistant_content: 'Hi there',
    }, optimisticUser);
    expect(next.timeline.some((item) => item.kind === 'conversation_answer')).toBe(true);
    const user = next.timeline.find((item) => item.kind === 'user_message');
    expect(user && user.kind === 'user_message' ? user.displayMarkdown : undefined).toBe('**Hello**');
    expect(user && user.kind === 'user_message' ? user.referencePaths : undefined).toEqual(['/tmp/a.txt']);
  });

  it('updates linked agent task from websocket event', () => {
    const timeline: HomeTimelineItem[] = [
      {
        kind: 'user_message',
        messageId: 'u1',
        content: 'Find files',
        displayMarkdown: 'Find files',
        referencePaths: ['/tmp/docs'],
        createdAt: '2026-01-01T00:00:00Z',
      },
      {
        kind: 'agent_task',
        messageId: 'u1',
        inReplyTo: 'u1',
        agentTaskId: 'task-1',
        state: 'running',
        createdAt: '2026-01-01T00:00:00Z',
      },
    ];
    const state = applyHydrationTimeline(timeline);
    const next = applyWsEvent(state, {
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      status: 'completed',
      result: 'Done',
    });
    const task = next.timeline.find((item) => item.kind === 'agent_task');
    const user = next.timeline.find((item) => item.kind === 'user_message');
    expect(task && task.kind === 'agent_task' ? task.state : undefined).toBe('completed');
    expect(user && user.kind === 'user_message' ? user.referencePaths : undefined).toEqual(['/tmp/docs']);
  });

  it('renders a failed agent-task result as failed', () => {
    const state = applyHydrationTimeline([
      {
        kind: 'agent_task',
        messageId: 'u1',
        inReplyTo: 'u1',
        agentTaskId: 'task-1',
        state: 'running',
        createdAt: '2026-01-01T00:00:00Z',
      },
    ]);
    const next = applyWsEvent(state, {
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: false,
      error: 'Tool failed',
    });
    const task = next.timeline.find((item) => item.kind === 'agent_task');
    expect(task && task.kind === 'agent_task' ? task.state : undefined).toBe('failed');
    expect(task && task.kind === 'agent_task' ? task.result : undefined).toBe('Tool failed');
  });

  it('does not overwrite a submitted user message during reconciliation', () => {
    const state = applyHydrationTimeline([
      { kind: 'user_message', messageId: 'u1', content: 'Search my history', createdAt: '2026-01-01T00:00:00Z' },
      {
        kind: 'agent_task',
        messageId: 'u1',
        inReplyTo: 'u1',
        agentTaskId: 'task-1',
        state: 'running',
        createdAt: '2026-01-01T00:00:00Z',
      },
    ]);
    const next = applyReconciledTurn(state, {
      inquiry_id: 'inq-1',
      user_message_id: 'u1',
      route_kind: 'agent_task',
      route_reason: 'Needs retrieval',
      state: 'running',
      agent_task_id: 'task-1',
    });
    expect(next.timeline.find((item) => item.kind === 'user_message')?.content).toBe('Search my history');
  });

  it('identifies only terminal agent-task websocket events', () => {
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_progress',
      agent_task_id: 'task-1',
      status: 'running',
    })).toBe(false);
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      status: 'completed',
    })).toBe(true);
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: false,
    })).toBe(true);
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_result',
      status: 'completed',
    })).toBe(false);
  });

  it('rejects unknown tab kinds', () => {
    expect(rejectUnknownTabKind('home')).toBe(false);
    expect(rejectUnknownTabKind('capability')).toBe(false);
    expect(rejectUnknownTabKind('system_embed')).toBe(false);
    expect(rejectUnknownTabKind('agent_report')).toBe(false);
    expect(rejectUnknownTabKind('custom_html')).toBe(true);
  });
});
