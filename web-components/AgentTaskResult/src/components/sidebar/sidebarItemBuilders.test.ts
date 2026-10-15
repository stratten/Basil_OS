import { describe, expect, it } from 'vitest';
import type { AgentState, ScheduledAgentTask } from '../../types';
import { createAgentState } from '../../store/agentStore/stateFactory';
import { buildHistoryItems, buildScheduledItems } from './sidebarItemBuilders';

function noop() {}

describe('buildScheduledItems titles', () => {
  it('renders scheduled task titles without markdown syntax', () => {
    const scheduled: ScheduledAgentTask = {
      id: 'scheduled-1',
      title: '**Weekly** `inbox_triage` summary',
      agent_task_text: 'Summarize my inbox',
      schedule_type: 'recurring',
      schedule_config: {},
      timezone: 'UTC',
      is_active: true,
      source_type: 'manual',
      reference_paths: [],
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-01T00:00:00Z',
      run_count: 0,
    };

    const rows = buildScheduledItems({ scheduled: [scheduled], onViewScheduledAgentTask: noop, deleteScheduledAgentTask: noop });

    expect(rows[0].title).toBe('Weekly inbox_triage summary');
  });
});

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

describe('buildHistoryItems pending follow-up due time', () => {
  it('attaches the due time to a live row by its chain root and to a history row by id', () => {
    const agent = createAgentState('task-live', 'Watch the deploy');
    agent.rootTaskId = 'root-live';
    const rows = buildHistoryItems({
      ...buildArgs([agent]),
      history: [
        {
          id: 'root-history',
          original_prompt: 'Earlier task',
          timestamp: '2026-10-01T00:00:00Z',
          status: 'completed',
          file_count: 0,
          follow_up_count: 0,
        },
        {
          id: 'root-none',
          original_prompt: 'Unrelated task',
          timestamp: '2026-10-01T00:00:00Z',
          status: 'completed',
          file_count: 0,
          follow_up_count: 0,
        },
      ],
      pendingFollowUps: {
        'root-live': '2026-10-12T15:00:00+00:00',
        'root-history': '2026-10-12T16:00:00+00:00',
      },
    });

    expect(rows.find(row => row.id === 'task-live')?.nextFollowUpAt).toBe('2026-10-12T15:00:00+00:00');
    expect(rows.find(row => row.id === 'root-history')?.nextFollowUpAt).toBe('2026-10-12T16:00:00+00:00');
    expect(rows.find(row => row.id === 'root-none')?.nextFollowUpAt).toBeUndefined();
  });
});

describe('buildHistoryItems archive wiring', () => {
  const archive = (_id: string) => {};

  function historyRow(id: string, status: string) {
    return {
      id,
      original_prompt: `Prompt ${id}`,
      timestamp: '2026-10-01T00:00:00Z',
      status,
      file_count: 0,
      follow_up_count: 0,
    };
  }

  it('offers archive on finished history rows and withholds it from running or waiting rows', () => {
    const rows = buildHistoryItems({
      ...buildArgs([]),
      history: [
        historyRow('done', 'completed'),
        historyRow('failed', 'failed'),
        historyRow('running', 'processing'),
        historyRow('waiting', 'awaiting_user_input'),
        historyRow('clarify', 'needs_clarification'),
      ],
      archiveAgentTask: archive,
      archiveLabel: 'Unarchive',
    });

    const byId = Object.fromEntries(rows.map(row => [row.id, row]));
    expect(byId.done.onArchive).toBe(archive);
    expect(byId.done.archiveLabel).toBe('Unarchive');
    expect(byId.failed.onArchive).toBe(archive);
    expect(byId.running.onArchive).toBeUndefined();
    expect(byId.waiting.onArchive).toBeUndefined();
    expect(byId.clarify.onArchive).toBeUndefined();
  });

  it('offers archive on finished store agents only', () => {
    const finished = createAgentState('finished-1', 'Done task');
    finished.status = 'completed';
    const running = createAgentState('running-1', 'Live task');
    running.status = 'processing';

    const rows = buildHistoryItems({
      ...buildArgs([finished, running]),
      archiveAgentTask: archive,
      archiveLabel: 'Archive',
    });

    const byId = Object.fromEntries(rows.map(row => [row.id, row]));
    expect(byId['finished-1'].onArchive).toBe(archive);
    expect(byId['running-1'].onArchive).toBeUndefined();
  });
});
