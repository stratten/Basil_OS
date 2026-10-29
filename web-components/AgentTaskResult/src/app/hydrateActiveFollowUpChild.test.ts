import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { hydrateActiveFollowUpChild } from './agentHydration';

function makeDetail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 'child-task',
    original_prompt: 'Put a copy in my downloads folder',
    transcribed_prompt: 'Put a copy in my downloads folder',
    timestamp: '2026-07-20T00:05:00.000Z',
    status: 'completed',
    result_message: 'Copied best_candidate.docx to Downloads.',
    files: [],
    reference_paths: [],
    follow_ups: [],
    ...overrides,
  };
}

describe('hydrateActiveFollowUpChild', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [],
      orphaned_approval_ids: [],
    });
  });

  it('applies a missed terminal child result onto the root entry and clears the active follow-up marker', async () => {
    // Mirrors what beginFollowUpTurn does when a live WS event starts a
    // follow-up: the child's own id has no store entry, all state lives on
    // the root. This is the exact "stuck at Executing approved tool" bug --
    // the child (agent-child-1) actually finished, but nothing ever polled
    // it directly.
    agentStore.registerAgent('agent-root-1');
    agentStore.beginFollowUpTurn('agent-child-1', 'agent-root-1');
    expect(agentStore.getAgent('agent-root-1')?.status).toBe('processing');
    expect(agentStore.hasActiveFollowUpTurn('agent-root-1')).toBe(true);

    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({ id: 'agent-child-1' }));

    await hydrateActiveFollowUpChild('agent-root-1', 'agent-child-1');

    const root = agentStore.getAgent('agent-root-1');
    expect(root?.status).toBe('completed');
    expect(root?.result).toBe('Copied best_candidate.docx to Downloads.');
    // Clearing the marker un-stalls the App.tsx polling effect and the
    // "ignore terminal parent hydration while a follow-up is active" guard
    // in agentHydration.ts, so subsequent hydrations of the root apply again.
    expect(agentStore.hasActiveFollowUpTurn('agent-root-1')).toBe(false);
  });

  it('preserves an artifact-only terminal child result on the root entry', async () => {
    agentStore.registerAgent('agent-root-artifact-only');
    agentStore.beginFollowUpTurn('agent-child-artifact-only', 'agent-root-artifact-only');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-artifact-only',
      result_message: undefined,
      files: [{
        name: 'report.md',
        path: '/tmp/report.md',
        operation: 'create',
        artifact: {
          artifact_id: 'child-report',
          display_name: 'report.md',
          local_path: '/tmp/report.md',
          artifact_kind: 'file',
          lifecycle: 'ready',
          preview: { capability: 'unknown' },
          verification: { status: 'unknown' },
        },
      }],
    }));

    await hydrateActiveFollowUpChild('agent-root-artifact-only', 'agent-child-artifact-only');

    const root = agentStore.getAgent('agent-root-artifact-only');
    expect(root?.status).toBe('completed');
    expect(root?.result).toBe('');
    expect(root?.structuredFiles).toHaveLength(1);
    expect(root?.structuredFiles[0].artifact?.artifact_id).toBe('child-report');
  });

  it('does not touch the root while the child is still genuinely in-flight', async () => {
    agentStore.registerAgent('agent-root-2');
    agentStore.beginFollowUpTurn('agent-child-2', 'agent-root-2');

    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-2',
      status: 'processing',
      result_message: undefined,
    }));

    await hydrateActiveFollowUpChild('agent-root-2', 'agent-child-2');

    const root = agentStore.getAgent('agent-root-2');
    expect(root?.status).toBe('processing');
    expect(agentStore.hasActiveFollowUpTurn('agent-root-2')).toBe(true);
  });

  it('restores a missed child checkpoint onto the root entry without clearing the follow-up', async () => {
    agentStore.registerAgent('agent-root-checkpoint');
    agentStore.beginFollowUpTurn('agent-child-checkpoint', 'agent-root-checkpoint');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-checkpoint',
      status: 'awaiting_user_input',
      result_message: 'Which reporting period should I use?',
      checkpoint_data: {
        checkpoint_id: 'period-choice',
        prompt: 'Which reporting period should I use?',
        input_type: 'selection',
        options: ['This quarter', 'Last quarter'],
      },
    }));

    await hydrateActiveFollowUpChild('agent-root-checkpoint', 'agent-child-checkpoint');

    const root = agentStore.getAgent('agent-root-checkpoint');
    expect(root?.status).toBe('awaitingInput');
    expect(root?.showCheckpointPrompt).toBe(true);
    expect(root?.currentCheckpoint?.session_agent_task_id).toBe('agent-child-checkpoint');
    expect(root?.currentCheckpoint?.input_type).toBe('choice');
    expect(root?.currentCheckpoint?.options).toEqual([
      { id: 'option-0', label: 'This quarter', value: 'This quarter' },
      { id: 'option-1', label: 'Last quarter', value: 'Last quarter' },
    ]);
    expect(agentStore.getActiveFollowUpId('agent-root-checkpoint')).toBe('agent-child-checkpoint');
  });

  it('restores a durable artifact while the child awaits user input', async () => {
    agentStore.registerAgent('agent-root-artifact-checkpoint');
    agentStore.beginFollowUpTurn('agent-child-artifact-checkpoint', 'agent-root-artifact-checkpoint');
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [],
      orphaned_approval_ids: [],
    });
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-artifact-checkpoint',
      status: 'awaiting_user_input',
      checkpoint_data: {
        checkpoint_id: 'continue-after-write',
        prompt: 'Continue after writing the report?',
        input_type: 'confirmation',
      },
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

    await hydrateActiveFollowUpChild(
      'agent-root-artifact-checkpoint',
      'agent-child-artifact-checkpoint',
    );

    const root = agentStore.getAgent('agent-root-artifact-checkpoint');
    expect(root?.status).toBe('awaitingInput');
    expect(root?.executionTimeline[0]?.id).toBe('artifact_file-0123456789abcdef01234567');
    expect(agentStore.getActiveFollowUpId('agent-root-artifact-checkpoint'))
      .toBe('agent-child-artifact-checkpoint');
  });

  it('uses a recovery prompt when a resumable child lacks checkpoint data', async () => {
    agentStore.registerAgent('agent-root-legacy-checkpoint');
    agentStore.beginFollowUpTurn('agent-child-legacy-checkpoint', 'agent-root-legacy-checkpoint');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-legacy-checkpoint',
      status: 'awaiting_user_input',
      result_message: 'Please provide the missing filename.',
      checkpoint_data: undefined,
    }));
    vi.spyOn(api, 'getCheckpointStatus').mockResolvedValue({
      agent_task_id: 'agent-child-legacy-checkpoint',
      has_checkpoint: true,
      can_resume: true,
      message: 'Checkpoint is available',
    });

    await hydrateActiveFollowUpChild('agent-root-legacy-checkpoint', 'agent-child-legacy-checkpoint');

    expect(agentStore.getAgent('agent-root-legacy-checkpoint')?.currentCheckpoint).toEqual({
      checkpoint_id: 'recovered-agent-child-legacy-checkpoint',
      session_agent_task_id: 'agent-child-legacy-checkpoint',
      prompt: 'Please provide the missing filename.',
      input_type: 'data',
      metadata: { source: 'checkpoint_recovery' },
    });
    expect(api.getCheckpointStatus).toHaveBeenCalledWith('agent-child-legacy-checkpoint');
  });

  it('does not stomp on a newer follow-up that superseded the one being reconciled', async () => {
    agentStore.registerAgent('agent-root-3');
    agentStore.beginFollowUpTurn('agent-child-3a', 'agent-root-3');
    // A second follow-up started (e.g. via a live WS event) before this
    // stale reconciliation for the first child resolved.
    agentStore.beginFollowUpTurn('agent-child-3b', 'agent-root-3');

    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({ id: 'agent-child-3a' }));

    await hydrateActiveFollowUpChild('agent-root-3', 'agent-child-3a');

    // The stale child's result must not overwrite the newer, still-active turn.
    expect(agentStore.getActiveFollowUpId('agent-root-3')).toBe('agent-child-3b');
    expect(agentStore.getAgent('agent-root-3')?.status).toBe('processing');
  });

  it('marks the root failed when the child failed', async () => {
    agentStore.registerAgent('agent-root-4');
    agentStore.beginFollowUpTurn('agent-child-4', 'agent-root-4');

    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-4',
      status: 'failed',
      error_message: 'File not found',
      result_message: undefined,
    }));

    await hydrateActiveFollowUpChild('agent-root-4', 'agent-child-4');

    const root = agentStore.getAgent('agent-root-4');
    expect(root?.status).toBe('failed');
    expect(root?.errorMessage).toBe('File not found');
    expect(agentStore.hasActiveFollowUpTurn('agent-root-4')).toBe(false);
  });

  it('swallows a failed child lookup without throwing', async () => {
    agentStore.registerAgent('agent-root-5');
    agentStore.beginFollowUpTurn('agent-child-5', 'agent-root-5');
    vi.spyOn(api, 'getAgentTaskDetail').mockRejectedValue(new Error('network error'));

    await expect(hydrateActiveFollowUpChild('agent-root-5', 'agent-child-5')).resolves.toBeUndefined();
    expect(agentStore.getAgent('agent-root-5')?.status).toBe('processing');
  });

  it('restores a live execution approval for a genuinely in-flight child', async () => {
    agentStore.registerAgent('agent-root-6');
    agentStore.beginFollowUpTurn('agent-child-6', 'agent-root-6');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-6',
      status: 'processing',
      result_message: undefined,
    }));
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [{
        approval_id: 'approval-child-1',
        agent_task_id: 'agent-child-6',
        command: 'ls',
        reason: 'Not whitelisted',
        risk_level: 'low',
        generalized_pattern: 'ls',
        execution_type: 'shell',
        revision: 0,
        context: {},
      }],
      orphaned_approval_ids: [],
    });

    await hydrateActiveFollowUpChild('agent-root-6', 'agent-child-6');

    const root = agentStore.getAgent('agent-root-6');
    expect(root?.status).toBe('awaitingInput');
    expect(root?.showApprovalPrompt).toBe(true);
    expect(root?.approvalRequests).toMatchObject([{ approval_id: 'approval-child-1' }]);
    expect(agentStore.hasActiveFollowUpTurn('agent-root-6')).toBe(true);
  });

  it('does not surface an approval from a child superseded while its lookup was pending', async () => {
    agentStore.registerAgent('agent-root-7');
    agentStore.beginFollowUpTurn('agent-child-7a', 'agent-root-7');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'agent-child-7a',
      status: 'processing',
      result_message: undefined,
    }));

    let resolveApprovals!: (value: api.PendingExecutionApprovalSet) => void;
    const pendingApprovals = new Promise<api.PendingExecutionApprovalSet>(resolve => {
      resolveApprovals = resolve;
    });
    vi.spyOn(api, 'getPendingExecutionApprovals').mockReturnValueOnce(pendingApprovals);

    const hydration = hydrateActiveFollowUpChild('agent-root-7', 'agent-child-7a');
    await vi.waitFor(() => {
      expect(api.getPendingExecutionApprovals).toHaveBeenCalledWith('agent-child-7a');
    });
    agentStore.beginFollowUpTurn('agent-child-7b', 'agent-root-7');
    resolveApprovals({
      approvals: [{
        approval_id: 'superseded-child-approval',
        agent_task_id: 'agent-child-7a',
        command: 'ls',
        reason: 'Not whitelisted',
        risk_level: 'low',
        generalized_pattern: 'ls',
        execution_type: 'shell',
        revision: 0,
        context: {},
      }],
      orphaned_approval_ids: [],
    });

    await hydration;

    const root = agentStore.getAgent('agent-root-7');
    expect(agentStore.getActiveFollowUpId('agent-root-7')).toBe('agent-child-7b');
    expect(root?.status).toBe('processing');
    expect(root?.showApprovalPrompt).toBe(false);
    expect(root?.approvalRequests).toEqual([]);
  });
});
