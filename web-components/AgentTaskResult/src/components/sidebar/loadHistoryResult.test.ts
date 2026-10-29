import { beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHistoryResult } from './loadHistoryResult';

const { getAgentTaskDetail, getAgentTaskSearchMatches } = vi.hoisted(() => ({
  getAgentTaskDetail: vi.fn(),
  getAgentTaskSearchMatches: vi.fn(),
}));

vi.mock('../../services/api', () => ({ getAgentTaskDetail, getAgentTaskSearchMatches }));

const detail = {
  id: 'root',
  original_prompt: 'Plan the Lisbon trip',
  transcribed_prompt: 'Plan the Lisbon trip',
  timestamp: '2026-09-24T12:00:00.000Z',
  status: 'completed',
  files: [],
  reference_paths: [],
  follow_ups: [],
};

describe('loadHistoryResult', () => {
  beforeEach(() => {
    getAgentTaskDetail.mockReset().mockResolvedValue(detail);
    getAgentTaskSearchMatches.mockReset();
  });

  it('asks only for the detail when the search box is empty', async () => {
    const result = await loadHistoryResult('root', '   ');
    expect(getAgentTaskSearchMatches).not.toHaveBeenCalled();
    expect(result.focus).toBeNull();
    expect(result.displayable.agentTaskId).toBe('root');
  });

  it('builds a focus from the matching turns, using the trimmed query', async () => {
    getAgentTaskSearchMatches.mockResolvedValue({ tokens: ['lisbon'], matched_turn_ids: ['root'] });
    const result = await loadHistoryResult('root', '  Lisbon ');
    expect(getAgentTaskSearchMatches).toHaveBeenCalledWith('root', 'Lisbon');
    expect(result.focus).toEqual({ scopeId: 'root', query: 'Lisbon', tokens: ['lisbon'], matchedIds: ['root'] });
  });

  it('opens the task without a focus when no turn matched', async () => {
    getAgentTaskSearchMatches.mockResolvedValue({ tokens: ['zebra'], matched_turn_ids: [] });
    expect((await loadHistoryResult('root', 'zebra')).focus).toBeNull();
  });

  it('opens the task normally when the match lookup fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    getAgentTaskSearchMatches.mockRejectedValue(new Error('404'));
    const result = await loadHistoryResult('root', 'lisbon');
    expect(result.focus).toBeNull();
    expect(result.displayable.agentTaskId).toBe('root');
    warn.mockRestore();
  });

  it('still fails when the detail itself cannot be loaded', async () => {
    getAgentTaskDetail.mockRejectedValue(new Error('boom'));
    getAgentTaskSearchMatches.mockResolvedValue({ tokens: ['lisbon'], matched_turn_ids: ['root'] });
    await expect(loadHistoryResult('root', 'lisbon')).rejects.toThrow('boom');
  });
});
