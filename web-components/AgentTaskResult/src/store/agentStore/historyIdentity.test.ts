import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskHistoryItem } from '../../types';
import { uniqueHistory, upsertHistoryItem } from './historyIdentity';
import { AgentStore } from './websocketHandlers';

const turn = (id: string, result = `result ${id}`): AgentTaskHistoryItem => ({
  id,
  agentTaskText: `prompt ${id}`,
  result,
  files: [],
  reference_paths: [],
  timestamp: '2026-11-16T12:00:00Z',
});

describe('history turn identity', () => {
  let warn: ReturnType<typeof vi.spyOn>;

  beforeEach(() => { warn = vi.spyOn(console, 'warn').mockImplementation(() => {}); });
  afterEach(() => warn.mockRestore());

  it('appends a new turn without warning', () => {
    const history = [turn('a')];
    expect(upsertHistoryItem(history, turn('b')).map(item => item.id)).toEqual(['a', 'b']);
    expect(history).toHaveLength(1);
    expect(warn).not.toHaveBeenCalled();
  });

  it('replaces a repeated turn in place with the newer copy and says so', () => {
    const history = [turn('a'), turn('b', 'old'), turn('c')];

    const next = upsertHistoryItem(history, turn('b', 'new'));

    expect(next.map(item => `${item.id}:${item.result}`)).toEqual(['a:result a', 'b:new', 'c:result c']);
    expect(history[1].result).toBe('old');
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('keeps an item with no id, because it cannot be matched to another', () => {
    expect(upsertHistoryItem([turn('')], turn('')).length).toBe(2);
  });

  it('returns a list that is already unique as the same array', () => {
    const history = [turn('a'), turn('b')];
    expect(uniqueHistory(history)).toBe(history);
    expect(warn).not.toHaveBeenCalled();
  });

  it('collapses the same turn listed three times to one, in its first position with its last data', () => {
    const next = uniqueHistory([turn('a'), turn('five', 'first'), turn('b'), turn('five', 'second'), turn('five', 'third')]);

    expect(next.map(item => `${item.id}:${item.result}`)).toEqual(['a:result a', 'five:third', 'b:result b']);
  });

  it('keeps the store free of repeated turns however the history arrives', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');

    store.setAgentTaskHistory('root-1', [turn('t1'), turn('t5'), turn('t5'), turn('t5')]);
    expect(store.getAgent('root-1')?.agentTaskHistory.map(item => item.id)).toEqual(['t1', 't5']);

    store.addToHistory('root-1', turn('t5', 'latest'));
    expect(store.getAgent('root-1')?.agentTaskHistory.map(item => `${item.id}:${item.result}`)).toEqual(['t1:result t1', 't5:latest']);

    store.beginFollowUpTurn('t6', 'root-1', turn('t5', 'snapshot'));
    store.beginFollowUpTurn('t7', 'root-1', turn('t5', 'snapshot again'));
    const ids = store.getAgent('root-1')?.agentTaskHistory.map(item => item.id);
    expect(ids).toEqual(['t1', 't5']);
    expect(store.getAgent('root-1')?.agentTaskHistory[1].result).toBe('snapshot again');
  });
});
