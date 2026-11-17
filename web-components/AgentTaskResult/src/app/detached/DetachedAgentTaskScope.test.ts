import { describe, expect, it } from 'vitest';
import { DetachedAgentTaskScope } from './DetachedAgentTaskScope';

describe('DetachedAgentTaskScope', () => {
  it('admits only its root and follow-up chain', () => {
    const scope = new DetachedAgentTaskScope('root');

    expect(scope.admits({ event_type: 'agent_task_progress', agent_task_id: 'root' })).toBe(true);
    expect(scope.admits({
      event_type: 'agent_task_progress',
      agent_task_id: 'child',
      root_task_id: 'root',
    })).toBe(true);
    expect(scope.admits({ event_type: 'agent_task_result', agent_task_id: 'child' })).toBe(true);
    expect(scope.admits({ event_type: 'agent_task_progress', agent_task_id: 'other' })).toBe(false);
  });

  it('admits a child linked to a known predecessor', () => {
    const scope = new DetachedAgentTaskScope('root');

    expect(scope.admits({
      event_type: 'agent_task_progress',
      agent_task_id: 'child',
      previous_task_id: 'root',
    })).toBe(true);
  });
});
