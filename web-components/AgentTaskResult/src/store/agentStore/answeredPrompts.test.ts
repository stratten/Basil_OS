import { describe, expect, it } from 'vitest';
import type { CheckpointData, ExecutionApprovalRequest } from '../../types';
import { forgetAnsweredPrompt, isAnsweredPrompt, rememberAnsweredPrompt } from './answeredPrompts';
import { AgentStore } from './websocketHandlers';

const checkpoint: CheckpointData = {
  checkpoint_id: 'checkpoint-1',
  prompt: 'Which account should I use?',
  input_type: 'data',
};

function approval(overrides: Partial<ExecutionApprovalRequest> = {}): ExecutionApprovalRequest {
  return {
    approval_id: 'approval-1',
    agent_task_id: 'task-1',
    command: 'ls',
    reason: 'List files',
    risk_level: 'low',
    ...overrides,
  };
}

describe('answered prompt bookkeeping', () => {
  it('remembers an id and recognizes it again', () => {
    const answered = rememberAnsweredPrompt(undefined, 'a');
    expect(isAnsweredPrompt(answered, 'a')).toBe(true);
    expect(isAnsweredPrompt(answered, 'b')).toBe(false);
    expect(isAnsweredPrompt(undefined, 'a')).toBe(false);
  });

  it('lets a higher revision of the same prompt through but not the same or an older one', () => {
    const answered = rememberAnsweredPrompt(undefined, 'a', 2);
    expect(isAnsweredPrompt(answered, 'a', 2)).toBe(true);
    expect(isAnsweredPrompt(answered, 'a', 1)).toBe(true);
    expect(isAnsweredPrompt(answered, 'a', 3)).toBe(false);
  });

  it('keeps the highest revision answered for an id', () => {
    const answered = rememberAnsweredPrompt(rememberAnsweredPrompt(undefined, 'a', 3), 'a', 1);
    expect(answered).toEqual([{ id: 'a', revision: 3 }]);
  });

  it('keeps only the newest fifty prompts', () => {
    let answered = rememberAnsweredPrompt(undefined, 'first');
    for (let index = 0; index < 60; index += 1) answered = rememberAnsweredPrompt(answered, `prompt-${index}`);
    expect(answered).toHaveLength(50);
    expect(isAnsweredPrompt(answered, 'first')).toBe(false);
    expect(isAnsweredPrompt(answered, 'prompt-59')).toBe(true);
  });

  it('never remembers a recovered checkpoint id, which every recovery in a session shares', () => {
    expect(rememberAnsweredPrompt(undefined, 'recovered-task-1')).toEqual([]);
    expect(rememberAnsweredPrompt(undefined, '')).toEqual([]);
  });

  it('forgets a prompt so it can be answered again', () => {
    const answered = rememberAnsweredPrompt(undefined, 'a');
    expect(forgetAnsweredPrompt(answered, 'a')).toEqual([]);
    expect(forgetAnsweredPrompt(undefined, 'a')).toEqual([]);
  });
});

describe('answered checkpoint delivery in the store', () => {
  it('keeps the card on screen from the moment of the answer until it settles', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);

    store.beginCheckpointAnswer('task-1', 'checkpoint-1', 'Resuming...');

    const during = store.getAgent('task-1');
    expect(during?.showCheckpointPrompt).toBe(true);
    expect(during?.currentCheckpoint).toEqual(checkpoint);
    expect(during?.isCheckpointResumePending).toBe(true);
    expect(during?.currentStep).toBe('Resuming...');

    store.settleAnsweredCheckpoint('task-1', 'checkpoint-1');

    const after = store.getAgent('task-1');
    expect(after?.showCheckpointPrompt).toBe(false);
    expect(after?.currentCheckpoint).toBeUndefined();
    expect(after?.inlineCheckpoint).toBeUndefined();
    expect(after?.status).toBe('processing');
    expect(after?.isCheckpointResumePending).toBe(false);
  });

  it('does not bring an answered checkpoint back when a stale read reports it', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);
    store.beginCheckpointAnswer('task-1', 'checkpoint-1', 'Resuming...');
    store.settleAnsweredCheckpoint('task-1', 'checkpoint-1');

    store.showCheckpoint('task-1', checkpoint);

    const agent = store.getAgent('task-1');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentCheckpoint).toBeUndefined();
    expect(agent?.status).toBe('processing');
    expect(store.isPromptAnswered('task-1', 'checkpoint-1')).toBe(true);
  });

  it('still shows a different checkpoint after one was answered', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);
    store.beginCheckpointAnswer('task-1', 'checkpoint-1', 'Resuming...');
    store.settleAnsweredCheckpoint('task-1', 'checkpoint-1');

    store.showCheckpoint('task-1', { ...checkpoint, checkpoint_id: 'checkpoint-2' });

    expect(store.getAgent('task-1')?.currentCheckpoint?.checkpoint_id).toBe('checkpoint-2');
    expect(store.getAgent('task-1')?.showCheckpointPrompt).toBe(true);
  });

  it('leaves a newer checkpoint alone when an older answer settles', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);
    store.beginCheckpointAnswer('task-1', 'checkpoint-1', 'Resuming...');
    store.showCheckpoint('task-1', { ...checkpoint, checkpoint_id: 'checkpoint-2' });

    store.settleAnsweredCheckpoint('task-1', 'checkpoint-1');

    expect(store.getAgent('task-1')?.currentCheckpoint?.checkpoint_id).toBe('checkpoint-2');
    expect(store.getAgent('task-1')?.showCheckpointPrompt).toBe(true);
  });

  it('does not revive a finished task when its answer is accepted late', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);
    store.beginCheckpointAnswer('task-1', 'checkpoint-1', 'Resuming...');
    store.updateStatus('task-1', 'completed');

    store.settleAnsweredCheckpoint('task-1', 'checkpoint-1');

    expect(store.getAgent('task-1')?.status).toBe('completed');
  });

  it('settles on the backend resume event and drops the pending window', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);
    store.beginCheckpointAnswer('task-1', 'checkpoint-1', 'Resuming...');

    store.handleWSEvent({ event_type: 'checkpoint_resumed', agent_task_id: 'task-1', message: 'Resumed' });

    const agent = store.getAgent('task-1');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentCheckpoint).toBeUndefined();
    expect(agent?.isCheckpointResumePending).toBe(false);
  });

  it('makes the checkpoint answerable again when delivery fails', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);
    store.beginCheckpointAnswer('task-1', 'checkpoint-1', 'Resuming...');

    store.reopenCheckpointAfterFailedAnswer('task-1', checkpoint);

    const agent = store.getAgent('task-1');
    expect(agent?.showCheckpointPrompt).toBe(true);
    expect(agent?.currentCheckpoint).toEqual(checkpoint);
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.isCheckpointResumePending).toBe(false);
    expect(store.isPromptAnswered('task-1', 'checkpoint-1')).toBe(false);
  });

  it('shows a recovered checkpoint again after an earlier recovery was answered', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    const recovered: CheckpointData = { checkpoint_id: 'recovered-task-1', prompt: 'Reply to continue.', input_type: 'data' };
    store.showCheckpoint('task-1', recovered);
    store.beginCheckpointAnswer('task-1', 'recovered-task-1', 'Resuming...');
    store.settleAnsweredCheckpoint('task-1', 'recovered-task-1');

    store.showCheckpoint('task-1', recovered);

    expect(store.getAgent('task-1')?.currentCheckpoint?.checkpoint_id).toBe('recovered-task-1');
  });
});

describe('answered approvals in the store', () => {
  it('does not bring a resolved approval back when a stale read lists it', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showApproval('task-1', approval());
    store.removeApproval('task-1', 'approval-1');

    store.showApproval('task-1', approval());

    const agent = store.getAgent('task-1');
    expect(agent?.approvalRequests).toHaveLength(0);
    expect(agent?.showApprovalPrompt).toBe(false);
  });

  it('shows a different approval after one was resolved', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showApproval('task-1', approval());
    store.removeApproval('task-1', 'approval-1');

    store.showApproval('task-1', approval({ approval_id: 'approval-2' }));

    expect(store.getAgent('task-1')?.approvalRequests.map(item => item.approval_id)).toEqual(['approval-2']);
  });

  it('shows the same approval again when it comes back at a higher revision', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showApproval('task-1', approval({ revision: 1 }));
    store.removeApproval('task-1', 'approval-1');

    store.showApproval('task-1', approval({ revision: 1 }));
    expect(store.getAgent('task-1')?.approvalRequests).toHaveLength(0);

    store.showApproval('task-1', approval({ revision: 2 }));
    expect(store.getAgent('task-1')?.approvalRequests).toHaveLength(1);
  });

  it('does not bring a resolved command input back when a pending list still includes it', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    const commandInput = approval({ approval_id: 'request-1', execution_type: 'command_input' });
    store.showApproval('task-1', commandInput);
    store.removeApproval('task-1', 'request-1');

    store.showApproval('task-1', commandInput);

    expect(store.getAgent('task-1')?.approvalRequests).toHaveLength(0);
  });
});
