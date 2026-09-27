import { describe, expect, it } from 'vitest';
import type { AgentState } from '../../types';
import { createAgentState } from '../../store/agentStore/stateFactory';
import { buildHistoryItems } from './sidebarItemBuilders';

function noop() {}

function buildArgs(allAgents: AgentState[]) {
  return {
    allAgents,
    history: [],
    activeIds: new Set(allAgents.map(a => a.agentTaskId)),
    detachedRoots: new Set<string>(),
    selectedId: null,
    viewedAgentTaskId: null,
    viewedRootId: null,
    selectAgent: noop,
    handleSelectHistoryId: noop,
    requestDeleteId: noop,
    detachAgentTask: noop,
    cancelAgentTask: noop,
    getAgentRootTaskId: () => undefined,
    openContextMenuForId: noop,
  };
}

describe('buildHistoryItems active-row origin badge', () => {
  it('sets originSourceLabel for active agents originating from a conversation', () => {
    const agent = createAgentState('task-1', 'Summarize the report');
    agent.originType = 'conversation';
    agent.originId = 'conv-123';

    const rows = buildHistoryItems(buildArgs([agent]));

    expect(rows).toHaveLength(1);
    expect(rows[0].originSourceLabel).toBe('From Conversation');
  });

  it('leaves originSourceLabel undefined for active agents without origin metadata', () => {
    const agent = createAgentState('task-1', 'Summarize the report');

    const rows = buildHistoryItems(buildArgs([agent]));

    expect(rows).toHaveLength(1);
    expect(rows[0].originSourceLabel).toBeUndefined();
  });

  it('preserves stable row callbacks across independent display builds', () => {
    const agent = createAgentState('task-1', 'Summarize the report');
    const args = buildArgs([agent]);

    const initial = buildHistoryItems(args)[0];
    agent.currentStep = 'Generating summary';
    const updated = buildHistoryItems(args)[0];

    expect(updated.onSelect).toBe(initial.onSelect);
    expect(updated.onDetach).toBe(initial.onDetach);
    expect(updated.onCancel).toBe(initial.onCancel);
    expect(updated.onContextMenu).toBe(initial.onContextMenu);
  });
});

describe('buildHistoryItems preserveHistoryOrder', () => {
  function historyItem(id: string, timestamp: string) {
    return {
      id,
      original_prompt: `Prompt ${id}`,
      timestamp,
      status: 'completed',
      file_count: 0,
      follow_up_count: 0,
    };
  }

  it('keeps the caller-provided history order when preserveHistoryOrder is true', () => {
    const older = historyItem('older-relevant', '2020-01-01T00:00:00Z');
    const newer = historyItem('newer-incidental', '2026-01-01T00:00:00Z');

    const rows = buildHistoryItems({
      ...buildArgs([]),
      history: [older, newer],
      preserveHistoryOrder: true,
    });

    expect(rows.map(r => r.id)).toEqual(['older-relevant', 'newer-incidental']);
  });

  it('still sorts by recency when preserveHistoryOrder is false or omitted', () => {
    const older = historyItem('older-relevant', '2020-01-01T00:00:00Z');
    const newer = historyItem('newer-incidental', '2026-01-01T00:00:00Z');

    const rows = buildHistoryItems({
      ...buildArgs([]),
      history: [older, newer],
    });

    expect(rows.map(r => r.id)).toEqual(['newer-incidental', 'older-relevant']);
  });
});
