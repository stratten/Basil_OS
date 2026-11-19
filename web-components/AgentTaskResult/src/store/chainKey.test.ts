import { describe, expect, it } from 'vitest';
import { chainKeyOf } from './chainKey';

describe('chainKeyOf', () => {
  it('uses the root task id once a follow-up has recorded it', () => {
    expect(chainKeyOf({ rootTaskId: 'root-1', agentTaskId: 'turn-2' })).toBe('root-1');
  });

  it('uses the task id when no root is recorded yet', () => {
    expect(chainKeyOf({ agentTaskId: 'turn-1' })).toBe('turn-1');
  });

  it('treats an empty root as not recorded', () => {
    expect(chainKeyOf({ rootTaskId: '', agentTaskId: 'turn-1' })).toBe('turn-1');
  });
});
