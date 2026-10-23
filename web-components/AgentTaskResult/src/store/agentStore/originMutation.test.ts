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

  it('keeps an agent revision origin on the turn that carries it and out of the root', () => {
    const store = new AgentStore();
    store.registerAgent('root-task', 'Initial request');
    store.updateAgentOrigin('root-task', 'conversation', 'conv-1');

    store.beginFollowUpTurn('turn-1', 'root-task');
    store.setCurrentTurnOrigin('root-task', 'agent_follow_up', 'root-task');
    store.updateAgentTaskText('root-task', 'Basil continued the task');
    store.beginFollowUpTurn('turn-2', 'root-task', undefined, 'turn-1');

    const agent = store.getAgent('root-task');
    expect(agent?.originType).toBe('conversation');
    expect(agent?.agentTaskHistory.map(item => [item.id, item.originType])).toEqual([
      ['root-task', 'conversation'],
      ['turn-1', 'agent_follow_up'],
    ]);
    expect(agent?.currentTurnOriginType).toBeUndefined();
    expect(agent?.currentTurnOriginId).toBeUndefined();
  });

  it('applies an agent_task_origin event for a chain turn to that turn, not to the root', () => {
    const store = new AgentStore();
    store.registerAgent('root-task', 'Initial request');

    store.handleWSEvent({
      event_type: 'agent_task_origin',
      agent_task_id: 'turn-1',
      root_task_id: 'root-task',
      previous_task_id: 'root-task',
      origin_type: 'agent_follow_up',
      origin_id: 'root-task',
    } as never);

    const agent = store.getAgent('root-task');
    expect(agent?.originType).toBeUndefined();
    expect(agent?.currentTurnOriginType).toBe('agent_follow_up');
    expect(agent?.currentTurnOriginId).toBe('root-task');
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
