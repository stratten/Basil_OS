import { describe, expect, it } from 'vitest';
import type { DisplayableAgentTask } from '../types';
import { effectiveRootId, isDisplaySourceDetached } from './detachedPresentation';

function task(ids: Pick<DisplayableAgentTask, 'agentTaskId' | 'rootTaskId'>): DisplayableAgentTask {
  return ids as DisplayableAgentTask;
}

describe('detachedPresentation', () => {
  it('uses the root task id when one is present', () => {
    const source = task({ agentTaskId: 'follow-up', rootTaskId: 'root' });

    expect(effectiveRootId(source)).toBe('root');
    expect(isDisplaySourceDetached(source, new Set(['root']))).toBe(true);
  });

  it('falls back to the task id for an unchained task', () => {
    const source = task({ agentTaskId: 'standalone' });

    expect(effectiveRootId(source)).toBe('standalone');
    expect(isDisplaySourceDetached(source, new Set(['standalone']))).toBe(true);
  });

  it('does not mark an unmatched task as detached', () => {
    expect(isDisplaySourceDetached(task({ agentTaskId: 'task' }), new Set(['other']))).toBe(false);
  });

  it('does not mark a task as detached when no roots are detached', () => {
    expect(isDisplaySourceDetached(task({ agentTaskId: 'task' }), new Set())).toBe(false);
  });

  it('does not mark an absent display source as detached', () => {
    expect(isDisplaySourceDetached(null, new Set(['root']))).toBe(false);
  });
});
