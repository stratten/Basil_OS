import { describe, expect, it } from 'vitest';
import { AgentStore } from './websocketHandlers';

function workingStore() {
  const store = new AgentStore();
  store.registerAgent('task-1');
  store.updateStatus('task-1', 'processing');
  return store;
}

function interactionEntry(id: string, kind: string, status: string) {
  return {
    id: `user_interaction_${id}`,
    type: 'step',
    timestamp: '2026-10-05T10:00:00+00:00',
    content: 'Paused at your request',
    detail_kind: 'user_interaction',
    metadata: { user_interaction: { interaction_id: id, kind, status, prompt: 'Paused at your request' } },
  };
}

describe('AgentStore pause handling', () => {
  it('marks the run paused when the backend announces it', () => {
    const store = workingStore();

    store.handleWSEvent({ event_type: 'agent_task_paused', agent_task_id: 'task-1', message: 'Paused' });

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('paused');
    expect(agent?.isStreaming).toBe(false);
    expect(agent?.currentStep).toBe('Paused');
  });

  it('ignores ordinary progress while paused but still records timeline entries', () => {
    const store = workingStore();
    store.handleWSEvent({ event_type: 'agent_task_paused', agent_task_id: 'task-1' });

    store.handleWSEvent({ event_type: 'agent_task_progress', agent_task_id: 'task-1', status: 'processing', details: 'Still going' });
    store.handleWSEvent({
      event_type: 'agent_task_step_detail',
      agent_task_id: 'task-1',
      timeline_entry: interactionEntry('pause_1', 'pause', 'waiting'),
    });

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('paused');
    expect(agent?.executionTimeline?.some(entry => entry.id === 'user_interaction_pause_1')).toBe(true);
  });

  it('returns to working when the run resumes', () => {
    const store = workingStore();
    store.handleWSEvent({ event_type: 'agent_task_paused', agent_task_id: 'task-1' });

    store.handleWSEvent({ event_type: 'checkpoint_resumed', agent_task_id: 'task-1', status: 'resumed' });

    expect(store.getAgent('task-1')?.status).toBe('processing');
  });

  it('stops a paused run when it is canceled', () => {
    const store = workingStore();
    store.handleWSEvent({ event_type: 'agent_task_paused', agent_task_id: 'task-1' });

    store.handleWSEvent({ event_type: 'agent_task_canceled', agent_task_id: 'task-1', message: 'Task canceled' });

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('failed');
    expect(agent?.isCanceled).toBe(true);
    expect(agent?.errorMessage).toBeUndefined();
  });

  it('does not revive a task that is waiting on the user when the question entry arrives', () => {
    const store = workingStore();
    store.updateStatus('task-1', 'awaitingInput');

    store.handleWSEvent({
      event_type: 'agent_task_step_detail',
      agent_task_id: 'task-1',
      timeline_entry: interactionEntry('cp', 'clarification', 'waiting'),
    });

    expect(store.getAgent('task-1')?.status).toBe('awaitingInput');
  });

  it('marks a hydrated canceled task as canceled', () => {
    const store = workingStore();

    store.markCanceled('task-1');

    expect(store.getAgent('task-1')?.isCanceled).toBe(true);
    expect(store.getAgent('task-1')?.isCanceling).toBe(false);
  });
});
