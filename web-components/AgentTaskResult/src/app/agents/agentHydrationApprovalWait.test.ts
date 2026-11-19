import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '../../types';
import * as api from '../../services/api';
import { agentStore } from '../../store/agentStore';
import { resetLiveActivityClockForTests } from '../../store/liveActivityClock';
import { hydrateAgentFromBackend } from './agentHydration';

const pendingApproval = {
  approval_id: 'approval-1',
  agent_task_id: 'wait-task',
  command: 'python3 -c "print(1)"',
  reason: 'Python 3 is not on the read-only list',
  risk_level: 'medium' as const,
  generalized_pattern: 'python3',
  execution_type: 'shell',
  revision: 1,
};

function processingDetail(taskId: string): AgentTaskDetail {
  return {
    id: taskId,
    original_prompt: 'Check something',
    transcribed_prompt: 'Check something',
    timestamp: '2026-11-18T21:00:00.000Z',
    // A shell approval wait never changes the backend status, so the backend reports the task as running.
    status: 'processing',
    files: [],
    reference_paths: [],
    follow_ups: [],
    execution_timeline: [],
  } as AgentTaskDetail;
}

describe('hydrateAgentFromBackend while an approval is waiting', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetLiveActivityClockForTests();
    vi.spyOn(api, 'getPendingCommandInputs').mockResolvedValue({ requests: [] } as Awaited<ReturnType<typeof api.getPendingCommandInputs>>);
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
  });

  it('never drops the task out of its waiting state while the approval is still pending', async () => {
    const taskId = 'wait-task';
    agentStore.registerAgent(taskId);
    agentStore.showApproval(taskId, pendingApproval as Parameters<typeof agentStore.showApproval>[1]);
    expect(agentStore.getAgent(taskId)?.status).toBe('awaitingInput');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(processingDetail(taskId));

    const statuses: string[] = [];
    const unsubscribe = agentStore.subscribe(() => statuses.push(agentStore.getAgent(taskId)?.status ?? ''));
    // The read of the pending approvals is where the old code had already left the waiting state, so the status is recorded at every change until it resolves.
    vi.spyOn(api, 'getPendingExecutionApprovals').mockImplementation(async () => {
      statuses.push(`during-read:${agentStore.getAgent(taskId)?.status}`);
      return { approvals: [pendingApproval], orphaned_approval_ids: [] } as Awaited<ReturnType<typeof api.getPendingExecutionApprovals>>;
    });

    await hydrateAgentFromBackend(taskId);
    unsubscribe();

    expect(statuses).not.toContain('processing');
    expect(statuses).toContain('during-read:awaitingInput');
    expect(agentStore.getAgent(taskId)?.status).toBe('awaitingInput');
    expect(agentStore.getAgent(taskId)?.showApprovalPrompt).toBe(true);
  });

  it('returns the task to running once the backend no longer lists the approval', async () => {
    const taskId = 'answered-elsewhere';
    agentStore.registerAgent(taskId);
    agentStore.showApproval(taskId, { ...pendingApproval, agent_task_id: taskId } as Parameters<typeof agentStore.showApproval>[1]);
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(processingDetail(taskId));
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({ approvals: [], orphaned_approval_ids: [] });

    await hydrateAgentFromBackend(taskId);

    expect(agentStore.getAgent(taskId)?.status).toBe('processing');
  });

  it('still marks a task with no approval showing as running', async () => {
    const taskId = 'plain-running';
    agentStore.registerAgent(taskId);
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(processingDetail(taskId));
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({ approvals: [], orphaned_approval_ids: [] });

    await hydrateAgentFromBackend(taskId);

    expect(agentStore.getAgent(taskId)?.status).toBe('processing');
  });
});
