import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { isWaitingPhaseEvent } from './progressEvent';
import { AgentStore } from './websocketHandlers';

function phaseEntry(state: string, field: 'timeline_entry' | 'entry' = 'timeline_entry'): WSEvent {
  return {
    event_type: 'agent_task_step_detail',
    agent_task_id: 'task-1',
    [field]: {
      id: `agent_run_x_execution_${state}`,
      type: 'phase',
      detail_kind: 'phase_transition',
      content: 'Working on the task',
      body: 'Working on the task',
      metadata: { error: null, progress_step: 'Working on the task', progress_phase: 'execution', progress_status: state, raw_detail: true },
      streaming: false,
      timestamp: '2026-10-27T22:23:00.493227+00:00',
      title: 'Working on the task',
      summary: 'Working on the task',
      phase: 'execution',
      state,
      source: 'graph_node',
      correlation_id: 'agent_run_x',
    },
  } as unknown as WSEvent;
}

function checkpointRequest(): WSEvent {
  return {
    event_type: 'collaborative_checkpoint_request',
    agent_task_id: 'task-1',
    checkpoint: { checkpoint_id: 'checkpoint-1', prompt: 'Should I move all six?', input_type: 'choice', options: ['Yes', 'No'] },
  } as WSEvent;
}

function workingStore() {
  const store = new AgentStore();
  store.registerAgent('task-1');
  store.updateStatus('task-1', 'processing');
  return store;
}

describe('a phase transition that ends in a waiting state', () => {
  it('recognizes waiting phase transitions in either entry field and ignores ordinary ones', () => {
    expect(isWaitingPhaseEvent(phaseEntry('waiting_user_input'))).toBe(true);
    expect(isWaitingPhaseEvent(phaseEntry('awaiting_user_input', 'entry'))).toBe(true);
    expect(isWaitingPhaseEvent(phaseEntry('started'))).toBe(false);
    expect(isWaitingPhaseEvent(phaseEntry('completed'))).toBe(false);
    expect(isWaitingPhaseEvent({ event_type: 'agent_task_progress', agent_task_id: 'task-1', status: 'waiting_user_input' } as WSEvent)).toBe(false);
  });

  it('keeps the checkpoint prompt that it trails', () => {
    const store = workingStore();
    store.handleWSEvent(checkpointRequest());

    store.handleWSEvent(phaseEntry('waiting_user_input'));

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.showCheckpointPrompt).toBe(true);
    expect(agent?.currentCheckpoint?.checkpoint_id).toBe('checkpoint-1');
  });

  it('keeps an approval prompt that it trails', () => {
    const store = workingStore();
    store.showApproval('task-1', {
      approval_id: 'approval-1',
      agent_task_id: 'task-1',
      command: 'rm -rf build',
      reason: 'Clean the build folder',
      risk_level: 'medium',
    });

    store.handleWSEvent(phaseEntry('waiting_user_input'));

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.showApprovalPrompt).toBe(true);
    expect(agent?.approvalRequests).toHaveLength(1);
  });

  it('still lands in the timeline', () => {
    const store = workingStore();
    store.handleWSEvent(checkpointRequest());

    store.handleWSEvent(phaseEntry('waiting_user_input'));

    const agent = store.getAgent('task-1');
    const recorded = [...(agent?.executionTimeline ?? []), ...(agent?.stepDetails ?? [])];
    expect(recorded.some(entry => entry.content === 'Working on the task')).toBe(true);
  });

  it('does not stop real execution progress from clearing a stale prompt', () => {
    const store = workingStore();
    store.handleWSEvent(checkpointRequest());
    store.handleWSEvent(phaseEntry('waiting_user_input'));

    store.handleWSEvent(phaseEntry('started'));

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentCheckpoint).toBeUndefined();
  });

  it('leaves a waiting task that has no prompt yet waiting', () => {
    const store = workingStore();
    store.handleWSEvent(phaseEntry('waiting_user_input'));
    store.handleWSEvent(checkpointRequest());

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.showCheckpointPrompt).toBe(true);
  });
});
