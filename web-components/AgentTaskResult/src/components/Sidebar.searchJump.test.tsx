// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentState } from '../types';
import { clearSearchFocus, getSearchFocus } from '@shared/search/searchFocusStore';
import Sidebar from './Sidebar';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const { listAgentTasks, searchAgentTasks, listScheduledAgentTasks, getAgentTaskDetail, getAgentTaskSearchMatches } = vi.hoisted(() => ({
  listAgentTasks: vi.fn(),
  searchAgentTasks: vi.fn(),
  listScheduledAgentTasks: vi.fn(),
  getAgentTaskDetail: vi.fn(),
  getAgentTaskSearchMatches: vi.fn(),
}));

const { allAgentsRef } = vi.hoisted(() => ({ allAgentsRef: { current: [] as AgentState[] } }));

vi.mock('../services/api', () => ({
  archiveAgentTask: vi.fn(),
  unarchiveAgentTask: vi.fn(),
  searchAgentTasks,
  deleteAgentTask: vi.fn(),
  getAgentTaskDetail,
  getAgentTaskSearchMatches,
  getPendingFollowUps: vi.fn().mockResolvedValue({ follow_ups: [] }),
  isApiReady: () => true,
  listAgentTasks,
  listScheduledAgentTasks,
  deleteScheduledAgentTask: vi.fn(),
}));

vi.mock('../store/agentStore', async importOriginal => ({
  ...(await importOriginal<typeof import('../store/agentStore')>()),
  useAllAgents: () => allAgentsRef.current,
  useSelectAgent: () => () => {},
  agentStore: {
    getSelectedAgentId: () => undefined,
    getAgent: () => undefined,
    removeAgent: vi.fn(),
  },
}));

vi.mock('../services/bridge', () => ({
  openDetachedAgentTask: vi.fn(),
  startNewAgentTaskCapture: vi.fn(),
}));

function historyRow(id: string, prompt: string) {
  return {
    id,
    original_prompt: prompt,
    timestamp: '2026-08-12T19:00:00.000Z',
    status: 'completed',
    result_preview: 'Done',
    file_count: 0,
    follow_up_count: 3,
  };
}

function detailFor(id: string) {
  return {
    id,
    original_prompt: `Prompt ${id}`,
    transcribed_prompt: `Prompt ${id}`,
    timestamp: '2026-08-12T19:00:00.000Z',
    status: 'completed',
    files: [],
    reference_paths: [],
    follow_ups: [],
  };
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('Sidebar search result jump', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onViewHistoricalAgentTask = vi.fn();

  const rows = () => Array.from(container.querySelectorAll<HTMLElement>('.sidebar-row'));
  const clickRow = (index: number) => rows()[index].querySelector<HTMLElement>('.agent-task-row__slide')!.click();
  const searchInput = () => container.querySelector<HTMLInputElement>('.sidebar-search-input')!;

  async function renderSidebar() {
    await act(async () => {
      root.render(
        <Sidebar
          isExpanded
          canLoadData
          onToggle={() => {}}
          onViewHistoricalAgentTask={onViewHistoricalAgentTask}
          onViewAgentTask={() => {}}
          onViewScheduledAgentTask={() => {}}
          onCreateScheduledAgentTask={() => {}}
        />,
      );
    });
    await vi.waitFor(() => expect(rows().length).toBe(2));
  }

  beforeEach(() => {
    clearSearchFocus();
    allAgentsRef.current = [];
    onViewHistoricalAgentTask.mockReset();
    getAgentTaskDetail.mockReset().mockImplementation(async (id: string) => detailFor(id));
    getAgentTaskSearchMatches.mockReset().mockResolvedValue({ tokens: ['lisbon'], matched_turn_ids: ['turn-4'] });
    const response = {
      agentTasks: [historyRow('chain-a', 'Plan the Lisbon trip'), historyRow('chain-b', 'Lisbon weather')],
      total_count: 2,
      has_more: false,
    };
    listAgentTasks.mockReset().mockResolvedValue(response);
    searchAgentTasks.mockReset().mockResolvedValue(response);
    listScheduledAgentTasks.mockReset().mockResolvedValue({ agent_tasks: [] });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    clearSearchFocus();
  });

  it('publishes the matching turns when a result is chosen while the search box has text', async () => {
    await renderSidebar();
    setInputValue(searchInput(), 'lisbon');
    await vi.waitFor(() => expect(searchAgentTasks).toHaveBeenCalled());

    await act(async () => { clickRow(0); });

    await vi.waitFor(() => expect(onViewHistoricalAgentTask).toHaveBeenCalledTimes(1));
    expect(getAgentTaskSearchMatches).toHaveBeenCalledWith('chain-a', 'lisbon');
    expect(getSearchFocus()).toEqual(expect.objectContaining({
      scopeId: 'chain-a',
      query: 'lisbon',
      tokens: ['lisbon'],
      matchedIds: ['turn-4'],
    }));
  });

  it('opens a plain selection without any search lookup and clears an earlier focus', async () => {
    await renderSidebar();
    setInputValue(searchInput(), 'lisbon');
    await vi.waitFor(() => expect(searchAgentTasks).toHaveBeenCalled());
    await act(async () => { clickRow(0); });
    await vi.waitFor(() => expect(getSearchFocus()).not.toBeNull());

    setInputValue(searchInput(), '');
    expect(getSearchFocus()).toBeNull();
    getAgentTaskSearchMatches.mockClear();
    await act(async () => { clickRow(1); });

    await vi.waitFor(() => expect(onViewHistoricalAgentTask).toHaveBeenCalledTimes(2));
    expect(getAgentTaskSearchMatches).not.toHaveBeenCalled();
    expect(getSearchFocus()).toBeNull();
  });

  it('opens the task normally when the match lookup fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    getAgentTaskSearchMatches.mockRejectedValue(new Error('offline'));
    await renderSidebar();
    setInputValue(searchInput(), 'lisbon');
    await vi.waitFor(() => expect(searchAgentTasks).toHaveBeenCalled());

    await act(async () => { clickRow(0); });

    await vi.waitFor(() => expect(onViewHistoricalAgentTask).toHaveBeenCalledTimes(1));
    expect(getSearchFocus()).toBeNull();
    warn.mockRestore();
  });

  it('lets only the latest click open a task when an earlier load finishes late', async () => {
    let releaseFirst: (value: unknown) => void = () => {};
    getAgentTaskDetail.mockImplementation((id: string) => (id === 'chain-a'
      ? new Promise(resolve => { releaseFirst = () => resolve(detailFor('chain-a')); })
      : Promise.resolve(detailFor(id))));
    await renderSidebar();
    setInputValue(searchInput(), 'lisbon');
    await vi.waitFor(() => expect(searchAgentTasks).toHaveBeenCalled());

    await act(async () => { clickRow(0); });
    await act(async () => { clickRow(1); });
    await vi.waitFor(() => expect(onViewHistoricalAgentTask).toHaveBeenCalledTimes(1));
    await act(async () => { releaseFirst(null); });

    expect(onViewHistoricalAgentTask).toHaveBeenCalledTimes(1);
    expect(onViewHistoricalAgentTask.mock.calls[0][0].agentTaskId).toBe('chain-b');
    expect(getSearchFocus()?.scopeId).toBe('chain-b');
  });
});
