import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '../types';
import type { AgentTaskPresentationSummaryHttpResponse } from '../artifacts/artifactContract';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';

// bridge.ts (imported by useHostBridge.ts) assigns onto `window` at module
// load time, and there is no jsdom in this project's test environment (see
// Header.test.tsx's identical stub-before-import pattern), so `window` must
// be stubbed before useHostBridge.ts is first imported.
let hydrateDetachedChain: typeof import('./useHostBridge').hydrateDetachedChain;

beforeAll(async () => {
  vi.stubGlobal('window', { setTimeout: () => 0 });
  hydrateDetachedChain = (await import('./useHostBridge')).hydrateDetachedChain;
});

function makeDetail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 'root-task',
    original_prompt: 'Find the best candidate file',
    transcribed_prompt: 'Find the best candidate file',
    timestamp: '2026-07-20T00:00:00.000Z',
    status: 'completed',
    result_message: 'Found best_candidate.docx',
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
    verification_status: 'resolved',
    requires_user_attention: false,
    ...(reportCards === undefined ? {} : { delegated_provider_report_cards: reportCards }),
  };
}

describe('hydrateDetachedChain', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('seeds the earlier turns into agentTaskHistory and shows the latest terminal turn', async () => {
    agentStore.registerAgent('root-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      status: 'processing',
      agent_task_presentation_summary: presentationSummary('root-task', {
        items: [{
          delegated_agent_run_id: 'run-parent',
          run_status: 'supervision_due',
          run_revision: 4,
          capture_state: 'available',
          evidence_count: 2,
          latest_summary: 'Parent-owned provider report.',
          verification_state: 'verified',
        }],
      }),
      follow_ups: [
        {
          id: 'follow-up-1',
          original_prompt: 'Put a copy in my downloads folder',
          timestamp: '2026-07-20T00:05:00.000Z',
          status: 'completed',
          result_message: 'Copied best_candidate.docx to Downloads.',
          files: [],
          agent_task_presentation_summary: presentationSummary('follow-up-1'),
          reference_paths: [],
          root_task_id: 'root-task',
          previous_task_id: 'root-task',
          chain_sequence_number: 2,
        },
      ],
    }));

    await hydrateDetachedChain('root-task');

    const agent = agentStore.getAgent('root-task');
    expect(agent?.status).toBe('completed');
    expect(agent?.result).toBe('Copied best_candidate.docx to Downloads.');
    expect(agent?.presentationSummary?.agentTaskId).toBe('follow-up-1');
    expect(agent?.delegatedProviderReportCards[0]?.delegatedAgentRunId).toBe('run-parent');
    // The root turn (sequence 1) is the only entry before the most recent
    // follow-up, so it must be seeded into history rather than dropped --
    // this is the exact gap #1 (detached window shows only the root task).
    expect(agent?.agentTaskHistory).toHaveLength(1);
    expect(agent?.agentTaskHistory[0].id).toBe('root-task');
    expect(agent?.agentTaskHistory[0].agentTaskText).toBe('Find the best candidate file');
  });

  it('seeds every prior turn for a fully terminal multi-follow-up chain', async () => {
    agentStore.registerAgent('root-multi');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'root-multi',
      status: 'completed',
      result_message: 'Root answer',
      follow_ups: [
        {
          id: 'fu-1',
          original_prompt: 'Second turn',
          timestamp: '2026-07-20T00:05:00.000Z',
          status: 'completed',
          result_message: 'Second answer',
          files: [],
          reference_paths: [],
          root_task_id: 'root-multi',
          previous_task_id: 'root-multi',
          chain_sequence_number: 1,
        },
        {
          id: 'fu-2',
          original_prompt: 'Third turn',
          timestamp: '2026-07-20T00:10:00.000Z',
          status: 'completed',
          result_message: 'Third answer',
          files: [],
          reference_paths: [],
          root_task_id: 'root-multi',
          previous_task_id: 'root-multi',
          chain_sequence_number: 2,
        },
        {
          id: 'fu-3',
          original_prompt: 'Fourth turn',
          timestamp: '2026-07-20T00:15:00.000Z',
          status: 'completed',
          result_message: 'Fourth answer',
          files: [],
          reference_paths: [],
          root_task_id: 'root-multi',
          previous_task_id: 'root-multi',
          chain_sequence_number: 3,
        },
      ],
    }));

    await hydrateDetachedChain('root-multi');

    const agent = agentStore.getAgent('root-multi');
    expect(agent?.status).toBe('completed');
    // The most recent follow-up is the current (displayed) turn.
    expect(agent?.result).toBe('Fourth answer');
    // Every earlier turn -- crucially including the MIDDLE ones -- must be
    // seeded into history in order. This is the exact "root + latest, middle
    // missing" composite the detached window regressed to.
    expect(agent?.agentTaskHistory.map(h => h.id)).toEqual(['root-multi', 'fu-1', 'fu-2']);
    expect(agent?.agentTaskHistory.map(h => h.agentTaskText)).toEqual([
      'Find the best candidate file',
      'Second turn',
      'Third turn',
    ]);
  });

  it('marks the entry failed when the most recent turn failed', async () => {
    agentStore.registerAgent('root-task-2');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'root-task-2',
      follow_ups: [
        {
          id: 'follow-up-2',
          original_prompt: 'Delete the wrong file',
          timestamp: '2026-07-20T00:05:00.000Z',
          status: 'failed',
          error_message: 'File not found',
          files: [],
          reference_paths: [],
          root_task_id: 'root-task-2',
          previous_task_id: 'root-task-2',
          chain_sequence_number: 2,
        },
      ],
    }));

    await hydrateDetachedChain('root-task-2');

    const agent = agentStore.getAgent('root-task-2');
    expect(agent?.status).toBe('failed');
    expect(agent?.errorMessage).toBe('File not found');
  });

  it('restores a missed checkpoint for the active detached follow-up onto the root entry', async () => {
    agentStore.registerAgent('root-awaiting-child');
    vi.spyOn(api, 'getAgentTaskDetail')
      .mockResolvedValueOnce(makeDetail({
        id: 'root-awaiting-child',
        follow_ups: [
          {
            id: 'awaiting-child',
            original_prompt: 'Prepare a report',
            timestamp: '2026-07-20T00:05:00.000Z',
            status: 'awaiting_user_input',
            result_message: 'Which reporting period should I use?',
            files: [],
            reference_paths: [],
            root_task_id: 'root-awaiting-child',
            previous_task_id: 'root-awaiting-child',
            chain_sequence_number: 1,
          },
        ],
      }))
      .mockResolvedValueOnce(makeDetail({
        id: 'awaiting-child',
        status: 'awaiting_user_input',
        result_message: 'Which reporting period should I use?',
        checkpoint_data: {
          checkpoint_id: 'period-choice',
          prompt: 'Which reporting period should I use?',
          input_type: 'selection',
          options: ['This quarter', 'Last quarter'],
        },
      }));

    await hydrateDetachedChain('root-awaiting-child');

    await vi.waitFor(() => {
      const root = agentStore.getAgent('root-awaiting-child');
      expect(root?.status).toBe('awaitingInput');
      expect(root?.showCheckpointPrompt).toBe(true);
      expect(root?.currentCheckpoint).toMatchObject({
        checkpoint_id: 'period-choice',
        session_agent_task_id: 'awaiting-child',
        input_type: 'choice',
      });
    });
  });

  it('restores a durable artifact for an in-flight detached follow-up', async () => {
    agentStore.registerAgent('root-artifact-child');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'root-artifact-child',
      status: 'completed',
      follow_ups: [{
        id: 'artifact-child',
        original_prompt: 'Update the report',
        timestamp: '2026-08-10T00:00:00.000Z',
        status: 'processing',
        files: [],
        reference_paths: [],
        root_task_id: 'root-artifact-child',
        previous_task_id: 'root-artifact-child',
        chain_sequence_number: 1,
        execution_timeline: [{
          id: 'artifact_file-0123456789abcdef01234567',
          type: 'artifact',
          timestamp: '2026-08-10T00:00:00.000Z',
          content: 'Verified local file: report.md',
          detail_kind: 'artifact',
          summary: 'Verified local file: report.md',
          body: 'Verified 13 bytes.',
          metadata: {
            event_type: 'agent_task_artifact',
            raw_detail: true,
            artifact: {
              artifact_id: 'file-0123456789abcdef01234567',
              display_name: 'report.md',
              local_path: '/tmp/report.md',
              artifact_kind: 'file',
              operation: 'modify',
              lifecycle: 'verified',
              source_timeline_entry_id: 'artifact_file-0123456789abcdef01234567',
              source_step_id: 'step-write',
              preview: { capability: 'unknown' },
              verification: { status: 'verified', summary: 'Verified 13 bytes.' },
            },
          },
          streaming: false,
        }],
      }],
    }));

    await hydrateDetachedChain('root-artifact-child');

    expect(agentStore.getAgent('root-artifact-child')?.executionTimeline[0]?.id)
      .toBe('artifact_file-0123456789abcdef01234567');
  });

  it('falls back to single-task hydration when the chain query fails', async () => {
    agentStore.registerAgent('root-task-3');
    vi.spyOn(api, 'getAgentTaskDetail').mockRejectedValue(new Error('network error'));

    await expect(hydrateDetachedChain('root-task-3')).resolves.toBeUndefined();
    // The failure is swallowed here; hydrateAgentFromBackend's own fallback
    // path (invoked internally) independently handles retry/error state.
  });
});
