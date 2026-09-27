import { describe, expect, it } from 'vitest';
import { AgentStore } from './websocketHandlers';

describe('AgentStoreCore.updateAgentOrigin', () => {
  it('sets originType and originId on an existing agent', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    store.updateAgentOrigin('task-1', 'conversation', 'conv-1');

    const agent = store.getAgent('task-1');
    expect(agent?.originType).toBe('conversation');
    expect(agent?.originId).toBe('conv-1');
  });

  it('is a no-op when both originType and originId are undefined', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    store.updateAgentOrigin('task-1', undefined, undefined);

    const agent = store.getAgent('task-1');
    expect(agent?.originType).toBeUndefined();
    expect(agent?.originId).toBeUndefined();
  });

  it('retains the last terminal turn as the next follow-up parent', () => {
    const store = new AgentStore();
    store.registerAgent('root-task', 'Initial request');

    store.beginFollowUpTurn('turn-1', 'root-task');
    store.clearActiveFollowUpTurn('root-task', 'turn-1');
    store.beginFollowUpTurn('turn-2', 'root-task', undefined, store.getCurrentTurnTaskId('root-task'));

    expect(store.getAgent('root-task')?.agentTaskId).toBe('root-task');
    expect(store.getAgent('root-task')?.currentTurnTaskId).toBe('turn-2');
    expect(store.getAgent('root-task')?.previousTaskId).toBe('turn-1');
  });
});
