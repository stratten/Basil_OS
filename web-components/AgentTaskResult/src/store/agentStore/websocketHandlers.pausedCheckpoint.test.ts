import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';

function pausedStore() {
  const store = new AgentStore();
  store.registerAgent('task-1');
  store.updateStatus('task-1', 'processing');
  store.handleWSEvent({ event_type: 'agent_task_paused', agent_task_id: 'task-1', message: 'Paused' });
  return store;
}

const questionEvent: WSEvent = {
  event_type: 'collaborative_checkpoint_request',
  agent_task_id: 'task-1',
  checkpoint_data: { checkpoint_id: 'checkpoint_abc', prompt: 'Where is the venue?', input_type: 'text' },
};

describe('AgentStore question while the window still shows the run as paused', () => {
  it('opens the question instead of dropping it, because a question proves the run is no longer paused', () => {
    const store = pausedStore();
    expect(store.getAgent('task-1')?.status).toBe('paused');

    store.handleWSEvent(questionEvent);

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.showCheckpointPrompt).toBe(true);
    expect(agent?.currentCheckpoint?.checkpoint_id).toBe('checkpoint_abc');
  });

  it('still ignores ordinary progress while paused', () => {
    const store = pausedStore();

    store.handleWSEvent({ event_type: 'agent_task_progress', agent_task_id: 'task-1', status: 'processing', details: 'Still going' });

    expect(store.getAgent('task-1')?.status).toBe('paused');
  });

  it('does not reopen a question the user already answered', () => {
    const store = pausedStore();
    store.beginCheckpointAnswer('task-1', 'checkpoint_abc', 'Resuming...');

    store.handleWSEvent(questionEvent);

    expect(store.getAgent('task-1')?.currentCheckpoint).toBeUndefined();
  });
});
