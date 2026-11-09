import { describe, expect, it } from 'vitest';
import type { CheckpointData } from '../../types';
import { settledInteractionId } from './progressEvent';
import { AgentStore } from './websocketHandlers';

function interactionEvent(id: string, kind: string, status: string) {
  return {
    event_type: 'agent_task_step_detail' as const,
    agent_task_id: 'task-1',
    timeline_entry: {
      id: `user_interaction_${id}`,
      type: 'step' as const,
      timestamp: '2026-11-02T17:10:00+00:00',
      content: 'A request',
      detail_kind: 'user_interaction',
      metadata: { user_interaction: { interaction_id: id, kind, status, prompt: 'A request' } },
    },
  };
}

const approval = {
  approval_id: 'approval-1',
  agent_task_id: 'task-1',
  command: 'weasyprint page.html page.pdf',
  reason: 'Render the PDF',
  risk_level: 'low' as const,
};

const question: CheckpointData = { checkpoint_id: 'cp-1', prompt: 'How should I proceed?', input_type: 'data' };

function workingStore() {
  const store = new AgentStore();
  store.registerAgent('task-1');
  store.updateStatus('task-1', 'processing');
  return store;
}

describe('settledInteractionId', () => {
  it('names the request for every settled status and never for a waiting one', () => {
    for (const status of ['approved', 'denied', 'answered', 'timed_out', 'canceled', 'resolved', 'dismissed']) {
      expect(settledInteractionId(interactionEvent('x-1', 'approval', status).timeline_entry)).toBe('x-1');
    }
    expect(settledInteractionId(interactionEvent('x-1', 'approval', 'waiting').timeline_entry)).toBeNull();
  });

  it('ignores entries that are not recorded exchanges or have no usable id', () => {
    const base = interactionEvent('x-1', 'approval', 'denied').timeline_entry;
    expect(settledInteractionId({ ...base, detail_kind: 'step_note' })).toBeNull();
    expect(settledInteractionId({ ...base, metadata: undefined })).toBeNull();
    expect(settledInteractionId(interactionEvent('', 'approval', 'denied').timeline_entry)).toBeNull();
  });
});

describe('AgentStore request settled in another window', () => {
  it('clears an approval that was denied in a different window', () => {
    const store = workingStore();
    store.showApproval('task-1', approval);
    expect(store.getAgent('task-1')?.showApprovalPrompt).toBe(true);

    store.handleWSEvent(interactionEvent('approval-1', 'approval', 'denied'));

    const agent = store.getAgent('task-1')!;
    expect(agent.approvalRequests).toHaveLength(0);
    expect(agent.showApprovalPrompt).toBe(false);
  });

  it('clears an approval that was approved in a different window', () => {
    const store = workingStore();
    store.showApproval('task-1', approval);

    store.handleWSEvent(interactionEvent('approval-1', 'approval', 'approved'));

    expect(store.getAgent('task-1')?.showApprovalPrompt).toBe(false);
  });

  it('keeps an approval that is still waiting, and one for a different request', () => {
    const store = workingStore();
    store.showApproval('task-1', approval);

    store.handleWSEvent(interactionEvent('approval-1', 'approval', 'waiting'));
    store.handleWSEvent(interactionEvent('approval-2', 'approval', 'denied'));

    const agent = store.getAgent('task-1')!;
    expect(agent.approvalRequests.map(request => request.approval_id)).toEqual(['approval-1']);
    expect(agent.showApprovalPrompt).toBe(true);
  });

  it('does not bring the approval back if its request event is replayed afterwards', () => {
    const store = workingStore();
    store.showApproval('task-1', approval);
    store.handleWSEvent(interactionEvent('approval-1', 'approval', 'denied'));

    store.showApproval('task-1', approval);

    expect(store.getAgent('task-1')?.approvalRequests).toHaveLength(0);
  });

  it('closes a question that was answered in a different window and lets the run show as working', () => {
    const store = workingStore();
    store.showCheckpoint('task-1', question);
    expect(store.getAgent('task-1')?.status).toBe('awaitingInput');

    store.handleWSEvent(interactionEvent('cp-1', 'clarification', 'answered'));

    const agent = store.getAgent('task-1')!;
    expect(agent.currentCheckpoint).toBeUndefined();
    expect(agent.showCheckpointPrompt).toBe(false);
    expect(agent.status).toBe('processing');
  });
});
