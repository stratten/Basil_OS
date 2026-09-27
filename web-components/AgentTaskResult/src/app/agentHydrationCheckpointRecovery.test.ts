import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { hydrateAgentFromBackend } from './agentHydration';

function makeDetail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 'awaiting-task',
    original_prompt: 'Prepare the report',
    transcribed_prompt: 'Prepare the report',
    timestamp: '2026-07-31T00:00:00.000Z',
    status: 'awaiting_user_input',
    result_message: 'Which reporting period should I use?',
    files: [],
    reference_paths: [],
    follow_ups: [],
    ...overrides,
  };
}

describe('hydrateAgentFromBackend checkpoint recovery', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [],
      orphaned_approval_ids: [],
    });
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
  });

  it('restores the exact durable checkpoint after its WebSocket event was missed', async () => {
    agentStore.registerAgent('awaiting-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      checkpoint_data: {
        checkpoint_id: 'period-choice',
        prompt: 'Which reporting period should I use?',
        input_type: 'selection',
        options: ['This quarter', 'Last quarter'],
      },
    }));

    hydrateAgentFromBackend('awaiting-task');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('awaiting-task');
      expect(agent?.status).toBe('awaitingInput');
      expect(agent?.showCheckpointPrompt).toBe(true);
      expect(agent?.currentCheckpoint).toMatchObject({
        checkpoint_id: 'period-choice',
        input_type: 'choice',
        options: [
          { id: 'option-0', label: 'This quarter', value: 'This quarter' },
          { id: 'option-1', label: 'Last quarter', value: 'Last quarter' },
        ],
      });
    });
  });

  it('preserves an optimistic retry when hydration still reads the preceding failed attempt', async () => {
    agentStore.registerAgent('retrying-task');
    agentStore.setError('retrying-task', 'OperationalError: database is locked');
    agentStore.resetForRetry('retrying-task');
    const getDetail = vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'retrying-task',
      status: 'failed',
      result_message: 'Prior partial result',
      error_message: 'OperationalError: database is locked',
    }));

    hydrateAgentFromBackend('retrying-task');

    await vi.waitFor(() => expect(getDetail).toHaveBeenCalledWith('retrying-task'));
    expect(agentStore.getAgent('retrying-task')).toMatchObject({
      status: 'processing',
      result: '',
      errorMessage: undefined,
      isRetryPending: true,
    });
  });

  it('restores a live provider form after its WebSocket event was missed', async () => {
    agentStore.registerAgent('provider-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'provider-task',
      status: 'processing',
    }));
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({
      interaction: {
        id: 'provider-interaction-1',
        message: 'Choose a strategy',
        fields: [
          {
            name: 'strategy',
            label: 'Strategy',
            kind: 'choice',
            required: true,
            options: [{ id: 'balanced', label: 'Balanced', value: 'balanced' }],
          },
        ],
      },
    });

    hydrateAgentFromBackend('provider-task');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('provider-task');
      expect(agent?.status).toBe('awaitingInput');
      expect(agent?.currentCheckpoint).toMatchObject({
        checkpoint_id: 'provider-interaction-1',
        input_type: 'provider_form',
        metadata: { source: 'provider_user_input' },
      });
    });
  });

  it('restores a durable execution approval after its WebSocket event was missed', async () => {
    agentStore.registerAgent('approval-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'approval-task',
      status: 'awaiting_user_input',
    }));
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [{
        approval_id: 'approval-1',
        agent_task_id: 'task-1',
        command: 'pwd',
        reason: 'Not whitelisted',
        risk_level: 'low',
        generalized_pattern: 'pwd',
        execution_type: 'shell',
        revision: 0,
        context: {},
      }],
      orphaned_approval_ids: [],
    });

    hydrateAgentFromBackend('approval-task');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('approval-task');
      expect(agent?.status).toBe('awaitingInput');
      expect(agent?.showApprovalPrompt).toBe(true);
      expect(agent?.approvalRequests).toMatchObject([{
        approval_id: 'approval-1',
        revision: 0,
      }]);
      expect(agent?.currentStep).toBe('Waiting for your approval');
    });
  });

  it('retires an approval orphaned by backend restart without rendering its command', async () => {
    agentStore.registerAgent('orphaned-approval-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'orphaned-approval-task',
      status: 'awaiting_user_input',
    }));
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [],
      orphaned_approval_ids: ['approval-orphaned'],
    });
    const recover = vi.spyOn(api, 'recoverOrphanedExecutionApprovals').mockResolvedValue({
      cancelled_approval_ids: ['approval-orphaned'],
    });

    hydrateAgentFromBackend('orphaned-approval-task');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('orphaned-approval-task')?.errorMessage)
        .toContain('restarted while waiting for command approval');
    });
    expect(recover).toHaveBeenCalledWith('orphaned-approval-task', ['approval-orphaned']);
    expect(agentStore.getAgent('orphaned-approval-task')?.approvalRequests).toEqual([]);
  });

  it('uses a safe free-text recovery prompt only for a resumable legacy checkpoint', async () => {
    agentStore.registerAgent('legacy-awaiting-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'legacy-awaiting-task',
      checkpoint_data: undefined,
    }));
    vi.spyOn(api, 'getCheckpointStatus').mockResolvedValue({
      agent_task_id: 'legacy-awaiting-task',
      has_checkpoint: true,
      can_resume: true,
      message: 'Checkpoint is available',
    });

    hydrateAgentFromBackend('legacy-awaiting-task');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('legacy-awaiting-task');
      expect(agent?.showCheckpointPrompt).toBe(true);
      expect(agent?.currentCheckpoint).toEqual({
        checkpoint_id: 'recovered-legacy-awaiting-task',
        session_agent_task_id: 'legacy-awaiting-task',
        prompt: 'Which reporting period should I use?',
        input_type: 'data',
        metadata: { source: 'checkpoint_recovery' },
      });
    });
  });

  it('exposes a retryable failure when the durable checkpoint cannot resume', async () => {
    agentStore.registerAgent('expired-awaiting-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'expired-awaiting-task',
      checkpoint_data: undefined,
    }));
    vi.spyOn(api, 'getCheckpointStatus').mockResolvedValue({
      agent_task_id: 'expired-awaiting-task',
      has_checkpoint: false,
      can_resume: false,
      message: 'No checkpoint is available',
    });

    hydrateAgentFromBackend('expired-awaiting-task');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('expired-awaiting-task');
      expect(agent?.status).toBe('failed');
      expect(agent?.errorMessage).toBe('The saved input request is no longer resumable. Retry the task to start a new run.');
      expect(agent?.showCheckpointPrompt).toBe(false);
    });
  });

  it('applies the most recent follow-up turn, not the root turn, when the whole chain is terminal', async () => {
    // Regression test for a detached multi-run window snapping back to the
    // root's own turn after correctly hydrating the latest follow-up: this
    // function can race hydrateDetachedChain (see useHostBridge.ts) and, if
    // it resolves later, must not clobber the merged follow-up data with the
    // root's own independently-terminal record.
    agentStore.registerAgent('chain-root');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'chain-root',
      status: 'completed',
      original_prompt: 'Inspect the integration workflow.',
      result_message: 'Run 1 is ready for history review.',
      follow_ups: [
        {
          id: 'follow-up-1',
          original_prompt: 'Add the deploy step.',
          timestamp: '2026-08-16T00:01:00.000Z',
          status: 'completed',
          result_message: 'Run 2 is ready for history review.',
          files: [],
          reference_paths: [],
          root_task_id: 'chain-root',
          previous_task_id: 'chain-root',
          chain_sequence_number: 1,
        },
        {
          id: 'follow-up-2',
          original_prompt: 'Produce the final implementation brief.',
          timestamp: '2026-08-16T00:02:00.000Z',
          status: 'completed',
          result_message: 'Run 3 is ready for history review.',
          files: [],
          reference_paths: [],
          root_task_id: 'chain-root',
          previous_task_id: 'follow-up-1',
          chain_sequence_number: 2,
        },
      ],
    }));

    hydrateAgentFromBackend('chain-root');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('chain-root');
      expect(agent?.originalPrompt).toBe('Produce the final implementation brief.');
      expect(agent?.result).toBe('Run 3 is ready for history review.');
      expect(agent?.status).toBe('completed');
      expect(agent?.currentTurnTaskId).toBe('follow-up-2');
    });
  });

  it('restores a durable legacy clarification as an input checkpoint', async () => {
    agentStore.registerAgent('clarification-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'clarification-task',
      status: 'needs_clarification',
      checkpoint_data: {
        checkpoint_id: 'clarification-clarification-task',
        prompt: 'Please provide the target date.',
        input_type: 'data',
        metadata: { source: 'clarification' },
      },
    }));

    hydrateAgentFromBackend('clarification-task');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('clarification-task');
      expect(agent?.status).toBe('awaitingInput');
      expect(agent?.showCheckpointPrompt).toBe(true);
      expect(agent?.currentCheckpoint).toMatchObject({
        checkpoint_id: 'clarification-clarification-task',
        prompt: 'Please provide the target date.',
        input_type: 'data',
        metadata: { source: 'clarification' },
      });
    });
  });

  it('restores a durable execution approval for a task still reported as processing', async () => {
    // Regression: a shell/execution-approval wait never flips backend status
    // to awaiting_user_input, so a task can sit at a live approval
    // checkpoint indefinitely while status stays "processing". Reopening it
    // must still resurface the approval instead of silently ignoring it.
    agentStore.registerAgent('processing-approval-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'processing-approval-task',
      status: 'processing',
    }));
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [{
        approval_id: 'approval-processing-1',
        agent_task_id: 'processing-approval-task',
        command: "head -n 50 build/scripts/build_and_sign.sh",
        reason: 'Not whitelisted',
        risk_level: 'low',
        generalized_pattern: 'head -n <N> <path>',
        execution_type: 'shell',
        revision: 0,
        context: {},
      }],
      orphaned_approval_ids: [],
    });

    hydrateAgentFromBackend('processing-approval-task');

    await vi.waitFor(() => {
      const agent = agentStore.getAgent('processing-approval-task');
      expect(agent?.status).toBe('awaitingInput');
      expect(agent?.showApprovalPrompt).toBe(true);
      expect(agent?.approvalRequests).toMatchObject([{
        approval_id: 'approval-processing-1',
        revision: 0,
      }]);
    });
  });

  it('does not resurface anything for a genuinely in-flight processing task with no pending approval', async () => {
    agentStore.registerAgent('plain-processing-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(makeDetail({
      id: 'plain-processing-task',
      status: 'processing',
    }));

    hydrateAgentFromBackend('plain-processing-task');

    await vi.waitFor(() => {
      expect(api.getPendingExecutionApprovals).toHaveBeenCalledWith('plain-processing-task');
    });
    const agent = agentStore.getAgent('plain-processing-task');
    expect(agent?.status).toBe('processing');
    expect(agent?.showApprovalPrompt ?? false).toBe(false);
  });
});
