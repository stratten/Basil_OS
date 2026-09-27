import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '../types';
import type { AgentTaskPresentationSummaryHttpResponse } from '../artifacts/artifactContract';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { hydrateActiveFollowUpChild, hydrateAgentFromBackend } from './agentHydration';

function makeDetail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 'task-1',
    original_prompt: 'Summarize the report',
    transcribed_prompt: 'Summarize the report',
    timestamp: '2026-07-31T00:00:00.000Z',
    status: 'processing',
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

describe('hydrateAgentFromBackend durable metadata', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [],
      orphaned_approval_ids: [],
    });
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
  });

  it('applies origin_type and origin_id from the backend detail', async () => {
    agentStore.registerAgent('task-1');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      origin_type: 'conversation',
      origin_id: 'conv-789',
    }));

    hydrateAgentFromBackend('task-1');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('task-1');
      expect(agent?.originType).toBe('conversation');
      expect(agent?.originId).toBe('conv-789');
    });
  });

  it('stores a terminal identity-matched presentation summary', async () => {
    agentStore.registerAgent('task-summary-matched');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-summary-matched',
      status: 'completed',
      result_message: 'Completed report.',
      agent_task_presentation_summary: presentationSummary('task-summary-matched'),
    }));

    hydrateAgentFromBackend('task-summary-matched');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-summary-matched')?.presentationSummary?.agentTaskId).toBe('task-summary-matched');
    });
  });

  it('does not store a terminal summary for another task', async () => {
    agentStore.registerAgent('task-summary-mismatched');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-summary-mismatched',
      status: 'completed',
      result_message: 'Completed report.',
      agent_task_presentation_summary: presentationSummary('other-task'),
    }));

    hydrateAgentFromBackend('task-summary-mismatched');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-summary-mismatched')?.status).toBe('completed');
    });
    expect(agentStore.getAgent('task-summary-mismatched')?.presentationSummary).toBeUndefined();
  });

  it('hydrates artifact-backed terminal work without result prose', async () => {
    agentStore.registerAgent('task-artifact-only');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-artifact-only',
      status: 'completed',
      files: [{
        name: 'report.md',
        path: '/tmp/report.md',
        operation: 'create',
        artifact: {
          artifact_id: 'report-artifact',
          display_name: 'report.md',
          local_path: '/tmp/report.md',
          artifact_kind: 'file',
          lifecycle: 'ready',
          preview: { capability: 'unknown' },
          verification: { status: 'unknown' },
        },
      }],
      agent_task_presentation_summary: presentationSummary('task-artifact-only'),
    }));

    hydrateAgentFromBackend('task-artifact-only');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-artifact-only')?.structuredFiles).toHaveLength(1);
    });
  });

  it('hydrates delegated provider report cards for a nonterminal task', async () => {
    agentStore.registerAgent('task-running-cards');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-running-cards',
      status: 'processing',
      agent_task_presentation_summary: presentationSummary('task-running-cards', {
        items: [{
          delegated_agent_run_id: 'run-1',
          run_status: 'running',
          run_revision: 2,
          capture_state: 'available',
          evidence_count: 4,
          latest_summary: 'Provider is still working.',
          verification_state: 'not_applicable',
        }],
      }),
    }));

    hydrateAgentFromBackend('task-running-cards');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-running-cards')?.delegatedProviderReportCards).toHaveLength(1);
    });
  });

  it('hydrates a legacy nonterminal task that lacks the report-card field', async () => {
    agentStore.registerAgent('task-legacy-cards');
    delete (agentStore.getAgent('task-legacy-cards') as { delegatedProviderReportCards?: unknown })
      .delegatedProviderReportCards;
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-legacy-cards',
      status: 'processing',
      agent_task_presentation_summary: presentationSummary('task-legacy-cards', {
        items: [{
          delegated_agent_run_id: 'run-legacy',
          run_status: 'running',
          run_revision: 1,
          capture_state: 'available',
          evidence_count: 1,
          latest_summary: 'Legacy task recovered.',
          verification_state: 'not_applicable',
        }],
      }),
    }));

    hydrateAgentFromBackend('task-legacy-cards');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-legacy-cards')?.delegatedProviderReportCards[0]?.delegatedAgentRunId)
        .toBe('run-legacy');
    });
  });

  it('does not replace a newer nonterminal live card snapshot with durable detail', async () => {
    agentStore.registerAgent('task-live-cards');
    agentStore.setDelegatedProviderReportCards('task-live-cards', [{
      delegatedAgentRunId: 'run-live',
      runStatus: 'running',
      runRevision: 3,
      captureState: 'available',
      evidenceCount: 5,
      latestSummary: 'Live update.',
      verificationState: 'not_applicable',
    }]);
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-live-cards',
      status: 'processing',
      agent_task_presentation_summary: presentationSummary('task-live-cards', {
        items: [{
          delegated_agent_run_id: 'run-live',
          run_status: 'running',
          run_revision: 2,
          capture_state: 'available',
          evidence_count: 4,
          latest_summary: 'Older durable detail.',
          verification_state: 'not_applicable',
        }],
      }),
    }));

    hydrateAgentFromBackend('task-live-cards');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-live-cards')?.presentationSummary?.agentTaskId).toBe('task-live-cards');
    });
    expect(agentStore.getAgent('task-live-cards')?.delegatedProviderReportCards[0]?.runRevision).toBe(3);
    expect(agentStore.getAgent('task-live-cards')?.delegatedProviderReportCards[0]?.evidenceCount).toBe(5);
  });

  it('hydrates delegated provider report cards for a terminal task', async () => {
    agentStore.registerAgent('task-terminal-cards');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-terminal-cards',
      status: 'completed',
      result_message: 'Done.',
      agent_task_presentation_summary: presentationSummary('task-terminal-cards', {
        items: [{
          delegated_agent_run_id: 'run-2',
          run_status: 'settled',
          run_revision: 5,
          capture_state: 'available',
          evidence_count: 8,
          verification_state: 'verified',
        }],
      }),
    }));

    hydrateAgentFromBackend('task-terminal-cards');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-terminal-cards')?.delegatedProviderReportCards[0]?.verificationState).toBe('verified');
    });
  });

  it('ignores a foreign summary identity and leaves report cards empty', async () => {
    agentStore.registerAgent('task-foreign-cards');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-foreign-cards',
      status: 'completed',
      result_message: 'Done.',
      agent_task_presentation_summary: presentationSummary('other-task', {
        items: [{
          delegated_agent_run_id: 'run-foreign',
          run_status: 'settled',
          run_revision: 1,
          capture_state: 'available',
          evidence_count: 1,
          verification_state: 'not_applicable',
        }],
      }),
    }));

    hydrateAgentFromBackend('task-foreign-cards');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-foreign-cards')?.delegatedProviderReportCards).toEqual([]);
    });
  });

  it('hydrates an active follow-up child card onto the root task', async () => {
    agentStore.registerAgent('task-follow-up-root');
    agentStore.beginFollowUpTurn('task-follow-up-child', 'task-follow-up-root');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-follow-up-child',
      status: 'completed',
      result_message: 'Done.',
      agent_task_presentation_summary: presentationSummary('task-follow-up-child', {
        items: [{
          delegated_agent_run_id: 'run-follow-up',
          run_status: 'settled',
          run_revision: 6,
          capture_state: 'available',
          evidence_count: 9,
          verification_state: 'verified',
        }],
      }),
    }));

    await hydrateActiveFollowUpChild('task-follow-up-root', 'task-follow-up-child');

    expect(agentStore.getAgent('task-follow-up-root')?.delegatedProviderReportCards[0]?.delegatedAgentRunId).toBe('run-follow-up');
  });

  it('replaces a live artifact with durable verification during nonterminal hydration', async () => {
    agentStore.registerAgent('task-artifact-hydration');
    agentStore.handleWSEvent({
      event_type: 'agent_task_artifact',
      agent_task_id: 'task-artifact-hydration',
      agent_task_artifact: {
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
      timeline_entry: {
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
      },
    });
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-artifact-hydration',
      status: 'processing',
      execution_timeline: [{
        id: 'artifact_file-0123456789abcdef01234567',
        type: 'artifact',
        timestamp: '2026-08-10T00:00:01.000Z',
        content: 'Failed local file: report.md',
        detail_kind: 'artifact',
        summary: 'Failed local file: report.md',
        body: 'Verification failed.',
        metadata: {
          event_type: 'agent_task_artifact',
          raw_detail: true,
          artifact: {
            artifact_id: 'file-0123456789abcdef01234567',
            display_name: 'report.md',
            local_path: '/tmp/report.md',
            artifact_kind: 'file',
            operation: 'modify',
            lifecycle: 'failed',
            source_timeline_entry_id: 'artifact_file-0123456789abcdef01234567',
            source_step_id: 'step-write',
            preview: { capability: 'unknown' },
            verification: { status: 'failed', summary: 'Verification failed.' },
          },
        },
        streaming: false,
      }],
    }));

    hydrateAgentFromBackend('task-artifact-hydration');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('task-artifact-hydration')?.executionTimeline[0]?.body)
        .toBe('Verification failed.');
    });
  });

  it('retains a persisted artifact while hydrating a cancelled task', async () => {
    agentStore.registerAgent('task-artifact-cancelled');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'task-artifact-cancelled',
      status: 'cancelled',
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
    }));

    hydrateAgentFromBackend('task-artifact-cancelled');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('task-artifact-cancelled');
      expect(agent?.status).toBe('failed');
      expect(agent?.executionTimeline[0]?.id).toBe('artifact_file-0123456789abcdef01234567');
    });
  });
});
