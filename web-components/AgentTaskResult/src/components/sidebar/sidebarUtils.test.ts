import { describe, expect, it } from 'vitest';
import type { AgentTaskDetail } from '../../types';
import type { AgentTaskPresentationSummaryHttpResponse } from '../../artifacts/artifactContract';
import { mapDetailToDisplayable, plainSidebarText } from './sidebarUtils';

function detail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 'root-task',
    original_prompt: 'Investigate the large folder',
    transcribed_prompt: 'Investigate the large folder',
    title: 'Large Folder Investigation',
    timestamp: '2026-07-10T12:00:00Z',
    status: 'completed',
    files: [],
    reference_paths: [],
    follow_ups: [],
    ...overrides,
  };
}

function presentationSummary(
  agentTaskId: string,
  reportCards?: AgentTaskPresentationSummaryHttpResponse['delegated_provider_report_cards'],
): AgentTaskPresentationSummaryHttpResponse {
  return {
    agent_task_id: agentTaskId,
    lifecycle: 'completed',
    workflow: {},
    artifacts: [],
    artifact_count: 0,
    verification_status: 'unknown',
    requires_user_attention: false,
    ...(reportCards === undefined ? {} : { delegated_provider_report_cards: reportCards }),
  };
}

describe('mapDetailToDisplayable', () => {
  it('preserves a direct historical task title', () => {
    const mapped = mapDetailToDisplayable(detail());

    expect(mapped.taskTitle).toBe('Large Folder Investigation');
    expect(mapped.timestamp).toBe('2026-07-10T12:00:00Z');
  });

  it('preserves the root title when displaying the latest follow-up', () => {
    const mapped = mapDetailToDisplayable(detail({
      follow_ups: [{
        id: 'follow-up-task',
        original_prompt: 'Now summarize the findings',
        timestamp: '2026-07-10T12:01:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 1,
        root_task_id: 'root-task',
        previous_task_id: 'root-task',
      }],
    }));

    expect(mapped.agentTaskId).toBe('follow-up-task');
    expect(mapped.taskTitle).toBe('Large Folder Investigation');
    expect(mapped.timestamp).toBe('2026-07-10T12:01:00Z');
  });

  it('uses the latest turn prompt instead of falling back to root display Markdown', () => {
    const mapped = mapDetailToDisplayable(detail({
      display_prompt_markdown: '**Root display prompt**',
      origin_type: 'conversation',
      origin_id: 'conv-1',
      follow_ups: [{
        id: 'follow-up-task',
        original_prompt: 'Actual child request',
        display_prompt_markdown: undefined,
        timestamp: '2026-07-10T12:01:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 1,
        root_task_id: 'root-task',
        previous_task_id: 'root-task',
      }],
    }));

    expect(mapped.displayPromptMarkdown).toBe('Actual child request');
    expect(mapped.displayPromptMarkdown).not.toContain('Root display prompt');
    expect(mapped.originType).toBe('conversation');
    expect(mapped.currentTurnTaskId).toBe('follow-up-task');
  });

  it('maps origin_type and origin_id for a direct historical task', () => {
    const mapped = mapDetailToDisplayable(detail({
      origin_type: 'conversation',
      origin_id: 'conv-123',
    }));

    expect(mapped.originType).toBe('conversation');
    expect(mapped.originId).toBe('conv-123');
  });

  it('maps origin from the root detail when displaying the latest follow-up', () => {
    const mapped = mapDetailToDisplayable(detail({
      origin_type: 'conversation',
      origin_id: 'conv-456',
      follow_ups: [{
        id: 'follow-up-task',
        original_prompt: 'Now summarize the findings',
        timestamp: '2026-07-10T12:01:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 1,
        root_task_id: 'root-task',
        previous_task_id: 'root-task',
      }],
    }));

    expect(mapped.originType).toBe('conversation');
    expect(mapped.originId).toBe('conv-456');
  });

  it('maps an identity-matched root presentation summary', () => {
    const mapped = mapDetailToDisplayable(detail({
      agent_task_presentation_summary: presentationSummary('root-task'),
    }));

    expect(mapped.presentationSummary?.agentTaskId).toBe('root-task');
  });

  it('maps delegated provider report cards for direct and follow-up details', () => {
    const reportCards = {
      items: [{
        delegated_agent_run_id: 'run-1',
        run_status: 'supervision_due',
        run_revision: 2,
        capture_state: 'available',
        evidence_count: 3,
        latest_summary: 'Provider needs supervision.',
        verification_state: 'verified' as const,
      }],
    } satisfies NonNullable<AgentTaskPresentationSummaryHttpResponse['delegated_provider_report_cards']>;
    const direct = mapDetailToDisplayable(detail({
      agent_task_presentation_summary: presentationSummary('root-task', reportCards),
    }));
    const followUp = mapDetailToDisplayable(detail({
      agent_task_presentation_summary: presentationSummary('root-task', reportCards),
      follow_ups: [{
        id: 'follow-up-task',
        original_prompt: 'Now summarize the findings',
        timestamp: '2026-07-10T12:01:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 1,
        root_task_id: 'root-task',
        previous_task_id: 'root-task',
        agent_task_presentation_summary: presentationSummary('follow-up-task'),
      }],
    }));

    expect(direct.delegatedProviderReportCards[0]?.delegatedAgentRunId).toBe('run-1');
    expect(followUp.delegatedProviderReportCards[0]?.latestSummary).toBe('Provider needs supervision.');
  });

  it('maps the latest follow-up summary instead of the root summary', () => {
    const mapped = mapDetailToDisplayable(detail({
      agent_task_presentation_summary: presentationSummary('root-task'),
      follow_ups: [{
        id: 'follow-up-task',
        original_prompt: 'Now summarize the findings',
        timestamp: '2026-07-10T12:01:00Z',
        status: 'completed',
        files: [],
        agent_task_presentation_summary: presentationSummary('follow-up-task'),
        reference_paths: [],
        chain_sequence_number: 1,
        root_task_id: 'root-task',
        previous_task_id: 'root-task',
      }],
    }));

    expect(mapped.agentTaskId).toBe('follow-up-task');
    expect(mapped.presentationSummary?.agentTaskId).toBe('follow-up-task');
  });

  it('propagates each turn\'s backend status onto its agentTaskHistory entry', () => {
    const mapped = mapDetailToDisplayable(detail({
      status: 'completed',
      follow_ups: [{
        id: 'follow-up-task',
        original_prompt: 'Resolve the conflicting literal path',
        timestamp: '2026-07-10T12:01:00Z',
        status: 'completed',
        outcome: 'partial',
        result_severity: 'warning',
        error_message: 'An agent advisory about a conflicting later literal path.',
        files: [],
        reference_paths: [],
        chain_sequence_number: 1,
        root_task_id: 'root-task',
        previous_task_id: 'root-task',
      }, {
        id: 'follow-up-task-2',
        original_prompt: 'Summarize the outcome',
        timestamp: '2026-07-10T12:02:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 2,
        root_task_id: 'root-task',
        previous_task_id: 'follow-up-task',
      }],
    }));

    expect(mapped.agentTaskHistory[0]?.status).toBe('completed');
    expect(mapped.agentTaskHistory[1]?.status).toBe('completed');
    expect(mapped.agentTaskHistory[1]?.outcome).toBe('partial');
    expect(mapped.agentTaskHistory[1]?.resultSeverity).toBe('warning');
  });

  it('suppresses a malformed or mismatched presentation summary', () => {
    expect(mapDetailToDisplayable(detail({
      agent_task_presentation_summary: presentationSummary('other-task'),
    })).presentationSummary).toBeUndefined();
    expect(mapDetailToDisplayable(detail({
      agent_task_presentation_summary: { agent_task_id: 'root-task' } as unknown as AgentTaskPresentationSummaryHttpResponse,
    })).presentationSummary).toBeUndefined();
  });

  it('maps the plain-record model_id onto originalModelId', () => {
    const mapped = mapDetailToDisplayable(detail({ model_id: 'local-qwen-3.5' }));

    expect(mapped.originalModelId).toBe('local-qwen-3.5');
  });

  it('leaves originalModelId undefined for a record that never overrode the model', () => {
    const mapped = mapDetailToDisplayable(detail());

    expect(mapped.originalModelId).toBeUndefined();
  });

  it('maps the most recent follow-up model_id onto originalModelId, not the root record', () => {
    const mapped = mapDetailToDisplayable(detail({
      model_id: 'local-qwen-3.5',
      follow_ups: [{
        id: 'follow-up-1',
        original_prompt: 'Try a different model',
        timestamp: '2026-07-10T12:05:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 1,
        model_id: 'gpt-5-mini',
      }],
    }));

    expect(mapped.originalModelId).toBe('gpt-5-mini');
  });

  it('keeps each turn’s reasoning segments isolated during detail mapping', () => {
    const rootReasoning = [{ iteration: 1, text: 'Root reasoning', is_complete: true }];
    const firstReasoning = [{ iteration: 1, text: 'First follow-up reasoning', is_complete: true }];
    const latestReasoning = [{ iteration: 1, text: 'Latest follow-up reasoning', is_complete: true }];
    const mapped = mapDetailToDisplayable(detail({
      thinking_history: rootReasoning,
      follow_ups: [{
        id: 'follow-up-1',
        original_prompt: 'First follow-up',
        timestamp: '2026-07-10T12:01:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 1,
        thinking_history: firstReasoning,
      }, {
        id: 'follow-up-2',
        original_prompt: 'Latest follow-up',
        timestamp: '2026-07-10T12:02:00Z',
        status: 'completed',
        files: [],
        reference_paths: [],
        chain_sequence_number: 2,
        thinking_history: latestReasoning,
      }],
    }));

    expect(mapped.thinkingSegments).toEqual([{ iteration: 1, text: 'Latest follow-up reasoning', isComplete: true }]);
    expect(mapped.agentTaskHistory[0]?.thinkingSegments).toEqual([{ iteration: 1, text: 'Root reasoning', isComplete: true }]);
    expect(mapped.agentTaskHistory[1]?.thinkingSegments).toEqual([{ iteration: 1, text: 'First follow-up reasoning', isComplete: true }]);
  });
});

describe('plainSidebarText', () => {
  it('removes display-only markdown without changing the text content', () => {
    expect(
      plainSidebarText('## **Inbox Metadata**\n- [Review details](https://example.com) with `ready` status')
    ).toBe('Inbox Metadata Review details with ready status');
  });
});
