import { describe, expect, it } from 'vitest';
import { AgentStore } from './websocketHandlers';

describe('findOpenEntryForTask', () => {
  it('finds a task that has its own entry', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    expect(store.findOpenEntryForTask('task-1')).toBe('task-1');
  });

  it('finds the chain root for a follow-up turn, which has no entry of its own', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.beginFollowUpTurn('turn-2', 'root-1');

    expect(store.getAgent('turn-2')).toBeUndefined();
    expect(store.findOpenEntryForTask('turn-2')).toBe('root-1');
  });

  it('finds the chain root through a turn that followed another turn', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.beginFollowUpTurn('turn-2', 'root-1');
    store.beginFollowUpTurn('turn-3', 'turn-2');

    expect(store.findOpenEntryForTask('turn-3')).toBe('root-1');
  });

  it('finds the chain that lists a task among its earlier turns', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.beginFollowUpTurn('turn-2', 'root-1', {
      id: 'earlier-turn',
      agentTaskText: 'First request',
      result: 'done',
      timestamp: '2026-11-01T10:00:00Z',
    } as never);

    expect(store.findOpenEntryForTask('earlier-turn')).toBe('root-1');
  });

  it('finds the chain whose displayed turn is the task', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.setCurrentTurnTaskId('root-1', 'displayed-turn');

    expect(store.findOpenEntryForTask('displayed-turn')).toBe('root-1');
  });

  it('returns nothing for a task this window does not hold, so it opens as new', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.beginFollowUpTurn('turn-2', 'root-1');

    expect(store.findOpenEntryForTask('unrelated-task')).toBeUndefined();
    expect(new AgentStore().findOpenEntryForTask('anything')).toBeUndefined();
  });

  it('does not map a turn of a chain this window has dropped to a different open chain', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.beginFollowUpTurn('turn-2', 'root-1');
    store.registerAgent('root-other');
    store.removeAgent('root-1');

    expect(store.findOpenEntryForTask('turn-2')).toBeUndefined();
  });
});
