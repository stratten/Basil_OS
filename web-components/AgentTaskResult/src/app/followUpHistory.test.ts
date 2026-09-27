import { describe, expect, it } from 'vitest';
import {
  buildDurableFollowUpHistoryBeforeActiveChild,
  buildFollowUpHistoryFromViewedDetail,
} from './followUpHistory';
import type { AgentTaskDetail, AgentTaskHistoryItem, DisplayableAgentTask } from '../types';

function makeHistoryItem(id: string, text: string): AgentTaskHistoryItem {
  return {
    id,
    agentTaskText: text,
    result: `Result for ${text}`,
    files: [],
    reference_paths: [],
    timestamp: '2026-07-08T00:00:00.000Z',
  };
}

function makeDetail(overrides: Partial<DisplayableAgentTask>): DisplayableAgentTask {
  return {
    agentTaskId: 'follow-up-1',
    rootTaskId: 'root-task',
    previousTaskId: 'initial-task',
    originalPrompt: 'Visible follow-up',
    status: 'completed',
    result: 'Visible result',
    delegatedProviderReportCards: [],
    structuredFiles: [],
    referencePaths: [],
    agentTaskHistory: [],
    progressSteps: [],
    executionTimeline: [],
    stepDetails: [],
    showWorkflowPlan: false,
    isStreaming: false,
    checkpointAvailable: false,
    thinkingSegments: [],
    ...overrides,
  };
}

function makeAgentTaskDetail(): AgentTaskDetail {
  return {
    id: 'root-task',
    original_prompt: 'Initial request',
    transcribed_prompt: 'Initial request',
    timestamp: '2026-07-08T00:00:00.000Z',
    status: 'completed',
    result_message: 'Initial result',
    files: [],
    reference_paths: [],
    follow_ups: [
      {
        id: 'follow-up-1',
        original_prompt: 'First follow-up',
        timestamp: '2026-07-08T00:01:00.000Z',
        status: 'completed',
        result_message: 'First follow-up result',
        files: [],
        reference_paths: [],
        root_task_id: 'root-task',
        previous_task_id: 'root-task',
        chain_sequence_number: 1,
      },
      {
        id: 'follow-up-2',
        original_prompt: 'Second follow-up',
        timestamp: '2026-07-08T00:02:00.000Z',
        status: 'completed',
        result_message: 'Second follow-up result',
        files: [],
        reference_paths: [],
        root_task_id: 'root-task',
        previous_task_id: 'follow-up-1',
        chain_sequence_number: 2,
      },
      {
        id: 'follow-up-3',
        original_prompt: 'Third follow-up',
        timestamp: '2026-07-08T00:03:00.000Z',
        status: 'completed',
        result_message: 'Third follow-up result',
        files: [],
        reference_paths: [],
        root_task_id: 'root-task',
        previous_task_id: 'follow-up-2',
        chain_sequence_number: 3,
      },
    ],
  };
}

describe('buildFollowUpHistoryFromViewedDetail', () => {
  it('preserves historical turns before the visible follow-up', () => {
    const initialTurn = makeHistoryItem('initial-task', 'Initial request');
    const detail = makeDetail({ agentTaskHistory: [initialTurn] });

    const history = buildFollowUpHistoryFromViewedDetail(detail);

    expect(history.length).toBe(2);
    expect(history[0]).toBe(initialTurn);
    expect(history[1].id).toBe('follow-up-1');
    expect(history[1].agentTaskText).toBe('Visible follow-up');
    expect(history[1].result).toBe('Visible result');
    expect(history[1].status).toBe('completed');
  });

  it('does not duplicate the visible turn when it is already in history', () => {
    const initialTurn = makeHistoryItem('initial-task', 'Initial request');
    const visibleTurn = makeHistoryItem('follow-up-1', 'Visible follow-up');
    const detail = makeDetail({ agentTaskHistory: [initialTurn, visibleTurn] });

    const history = buildFollowUpHistoryFromViewedDetail(detail);

    expect(history.length).toBe(2);
    expect(history[0]).toBe(initialTurn);
    expect(history[1]).toBe(visibleTurn);
  });
});

describe('buildDurableFollowUpHistoryBeforeActiveChild', () => {
  it('keeps every durable prior turn whether the active child is persisted yet or not', () => {
    const detail = makeAgentTaskDetail();

    expect(buildDurableFollowUpHistoryBeforeActiveChild(detail, 'follow-up-4').map(item => item.id))
      .toEqual(['root-task', 'follow-up-1', 'follow-up-2', 'follow-up-3']);
    expect(buildDurableFollowUpHistoryBeforeActiveChild(detail, 'follow-up-3').map(item => item.id))
      .toEqual(['root-task', 'follow-up-1', 'follow-up-2']);
  });

  it('retains each completed turn’s own persisted reasoning before an active child', () => {
    const detail = makeAgentTaskDetail();
    detail.thinking_history = [{ iteration: 1, text: 'Root reasoning', is_complete: true }];
    detail.follow_ups[0].thinking_history = [{ iteration: 1, text: 'First reasoning', is_complete: true }];
    detail.follow_ups[1].thinking_history = [{ iteration: 1, text: 'Second reasoning', is_complete: true }];

    const history = buildDurableFollowUpHistoryBeforeActiveChild(detail, 'follow-up-3');

    expect(history.map(item => item.thinkingSegments?.[0]?.text)).toEqual([
      'Root reasoning',
      'First reasoning',
      'Second reasoning',
    ]);
  });
});
