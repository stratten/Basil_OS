import { describe, expect, it } from 'vitest';
import type { CheckpointData } from '../../types';
import { AgentStore } from './websocketHandlers';

const checkpoint: CheckpointData = {
  checkpoint_id: 'checkpoint-1',
  prompt: 'Which account should I use?',
  input_type: 'data',
};

describe('dismissCheckpoint', () => {
  it('closes the prompt but keeps the question and the awaiting status', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);

    store.dismissCheckpoint('task-1');

    const agent = store.getAgent('task-1');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.inlineCheckpoint).toBeUndefined();
    expect(agent?.currentCheckpoint).toEqual(checkpoint);
    expect(agent?.status).toBe('awaitingInput');
  });

  it('can be reopened with showCheckpoint', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);
    store.dismissCheckpoint('task-1');

    store.showCheckpoint('task-1', checkpoint);

    const agent = store.getAgent('task-1');
    expect(agent?.showCheckpointPrompt).toBe(true);
    expect(agent?.inlineCheckpoint).toEqual(checkpoint);
  });

  it('is still discarded entirely by hideCheckpoint', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.showCheckpoint('task-1', checkpoint);

    store.hideCheckpoint('task-1');

    expect(store.getAgent('task-1')?.currentCheckpoint).toBeUndefined();
  });
});
