// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentState } from '../types';
import { createAgentState } from '../store/agentStore/stateFactory';
import Sidebar from './Sidebar';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const { listAgentTasks, searchAgentTasks, listScheduledAgentTasks } = vi.hoisted(() => ({
  listAgentTasks: vi.fn(),
  searchAgentTasks: vi.fn(),
  listScheduledAgentTasks: vi.fn(),
}));

const { allAgentsRef } = vi.hoisted(() => ({ allAgentsRef: { current: [] as AgentState[] } }));

vi.mock('../services/api', () => ({
  archiveAgentTask: vi.fn(),
  unarchiveAgentTask: vi.fn(),
  searchAgentTasks,
  deleteAgentTask: vi.fn(),
  getAgentTaskDetail: vi.fn(),
  isApiReady: () => true,
  listAgentTasks,
  listScheduledAgentTasks,
  deleteScheduledAgentTask: vi.fn(),
}));

vi.mock('../store/agentStore', () => ({
  useAllAgents: () => allAgentsRef.current,
  useSelectAgent: () => () => {},
  agentStore: {
    getSelectedAgentId: () => undefined,
    getAgent: (id: string) => allAgentsRef.current.find(agent => agent.agentTaskId === id),
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
    follow_up_count: 0,
  };
}

function listResponse(...rows: ReturnType<typeof historyRow>[]) {
  return { agentTasks: rows, total_count: rows.length, has_more: false };
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('Sidebar task filters', () => {
  let container: HTMLDivElement;
  let root: Root;

  async function renderSidebar() {
    await act(async () => {
      root.render(
        <Sidebar
          isExpanded
          canLoadData
          onToggle={() => {}}
          onViewHistoricalAgentTask={() => {}}
          onViewAgentTask={() => {}}
          onViewScheduledAgentTask={() => {}}
          onCreateScheduledAgentTask={() => {}}
        />,
      );
    });
  }

  const filterButton = () => container.querySelector<HTMLButtonElement>('button.sidebar-filter-button');
  const badge = () => container.querySelector('.sidebar-filter-badge')?.textContent ?? null;
  const input = (label: string) => container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
  const dateInput = (label: string) => Array.from(container.querySelectorAll<HTMLLabelElement>('.sidebar-filter-field'))
    .find(field => field.textContent?.startsWith(label))!.querySelector<HTMLInputElement>('input[type="date"]')!;
  const lastListOptions = () => listAgentTasks.mock.calls[listAgentTasks.mock.calls.length - 1][3] as { archived: boolean; filters?: Record<string, unknown> };

  async function openPanel() {
    await act(async () => { filterButton()!.click(); });
  }

  beforeEach(() => {
    allAgentsRef.current = [];
    listAgentTasks.mockReset();
    searchAgentTasks.mockReset();
    listScheduledAgentTasks.mockReset();
    listScheduledAgentTasks.mockResolvedValue({ agent_tasks: [] });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('starts with no badge and an unchanged request, then sends each filter and counts it', async () => {
    listAgentTasks.mockResolvedValue(listResponse(historyRow('t1', 'Summarize the report')));
    await renderSidebar();
    await vi.waitFor(() => expect(container.querySelector('.sidebar-row')).not.toBeNull());

    expect(badge()).toBeNull();
    expect(lastListOptions()).toEqual({ archived: false });

    await openPanel();
    setInputValue(input('Application'), 'Safari');
    setInputValue(dateInput('From'), '2026-03-01');

    await vi.waitFor(() => {
      expect(lastListOptions().filters).toEqual(expect.objectContaining({ app: 'Safari', start_date: expect.any(String) }));
    });
    expect(badge()).toBe('2');
    expect(filterButton()!.getAttribute('aria-label')).toBe('Task filters, 2 active');
  });

  it('clears every filter from the panel and fetches the unfiltered list again', async () => {
    listAgentTasks.mockResolvedValue(listResponse(historyRow('t1', 'Summarize the report')));
    await renderSidebar();
    await vi.waitFor(() => expect(container.querySelector('.sidebar-row')).not.toBeNull());
    await openPanel();
    setInputValue(input('Application'), 'Safari');
    await vi.waitFor(() => expect(lastListOptions().filters).toEqual({ app: 'Safari' }));

    await act(async () => { container.querySelector<HTMLButtonElement>('.sidebar-filters-clear')!.click(); });

    await vi.waitFor(() => expect(lastListOptions()).toEqual({ archived: false }));
    expect(badge()).toBeNull();
    expect(input('Application').value).toBe('');
  });

  it('sends the filters with the deep search while a query is typed and refreshes the search when a filter changes', async () => {
    listAgentTasks.mockResolvedValue(listResponse(historyRow('t1', 'Summarize the report')));
    searchAgentTasks.mockResolvedValue(listResponse(historyRow('t1', 'Summarize the report')));
    await renderSidebar();
    await vi.waitFor(() => expect(container.querySelector('.sidebar-row')).not.toBeNull());
    const listCallsBeforeFiltering = listAgentTasks.mock.calls.length;

    setInputValue(container.querySelector<HTMLInputElement>('.sidebar-search-input')!, 'report');
    await vi.waitFor(() => expect(searchAgentTasks).toHaveBeenCalledWith('report', expect.any(Number), 0, { archived: false }));

    await openPanel();
    setInputValue(input('Application'), 'Safari');
    await vi.waitFor(() => {
      expect(searchAgentTasks).toHaveBeenLastCalledWith('report', expect.any(Number), 0, { archived: false, filters: { app: 'Safari' } });
    });
    expect(listAgentTasks.mock.calls.length).toBe(listCallsBeforeFiltering);
  });

  it('explains an empty filtered result and restores the list from its Clear action', async () => {
    listAgentTasks.mockImplementation(async (_limit: number, _offset: number, _status: unknown, options: { filters?: unknown }) => (
      options.filters ? listResponse() : listResponse(historyRow('t1', 'Summarize the report'))
    ));
    await renderSidebar();
    await vi.waitFor(() => expect(container.querySelector('.sidebar-row')).not.toBeNull());
    await openPanel();
    setInputValue(input('Application'), 'Nonexistent');

    await vi.waitFor(() => expect(container.textContent).toContain('No tasks match these filters'));
    expect(container.textContent).not.toContain('No tasks yet');

    await act(async () => { container.querySelector<HTMLButtonElement>('.sidebar-filtered-empty .action-btn')!.click(); });
    await vi.waitFor(() => expect(container.querySelector('.sidebar-row')).not.toBeNull());
    expect(container.textContent).not.toContain('No tasks match these filters');
  });

  it('shows the plain empty message when nothing is filtered', async () => {
    listAgentTasks.mockResolvedValue(listResponse());
    await renderSidebar();
    await vi.waitFor(() => expect(container.textContent).toContain('No tasks yet'));
  });

  it('resets the filters when switching views and offers none in the Scheduled view', async () => {
    listAgentTasks.mockResolvedValue(listResponse(historyRow('t1', 'Summarize the report')));
    await renderSidebar();
    await vi.waitFor(() => expect(container.querySelector('.sidebar-row')).not.toBeNull());
    await openPanel();
    setInputValue(input('Application'), 'Safari');
    await vi.waitFor(() => expect(badge()).toBe('1'));

    await act(async () => { container.querySelector<HTMLButtonElement>('button[aria-label="Archived"]')!.click(); });
    await vi.waitFor(() => expect(lastListOptions()).toEqual({ archived: true }));
    expect(badge()).toBeNull();

    await act(async () => { container.querySelector<HTMLButtonElement>('button[title="View scheduled tasks"]')!.click(); });
    expect(filterButton()).toBeNull();
    expect(container.querySelector('.sidebar-filters')).toBeNull();
  });

  it('hides a running task that does not match the filters and keeps one that does', async () => {
    listAgentTasks.mockResolvedValue(listResponse());
    allAgentsRef.current = [{ ...createAgentState('agent-live', 'Draft the follow-up email'), status: 'processing' }];
    await renderSidebar();
    await vi.waitFor(() => expect(container.querySelectorAll('.sidebar-row').length).toBe(1));
    await openPanel();

    const statusSelect = container.querySelector<HTMLButtonElement>('button.tokenized-select__trigger[aria-label="Status"]')
      ?? Array.from(container.querySelectorAll<HTMLButtonElement>('button.tokenized-select__trigger'))[1];
    await act(async () => { statusSelect.click(); });
    const completedOption = Array.from(document.querySelectorAll<HTMLButtonElement>('.tokenized-select__option'))
      .find(option => option.textContent === 'Completed')!;
    await act(async () => { completedOption.click(); });
    await vi.waitFor(() => expect(container.querySelectorAll('.sidebar-row').length).toBe(0));

    await act(async () => { container.querySelector<HTMLButtonElement>('.sidebar-filters-clear')!.click(); });
    await vi.waitFor(() => expect(container.querySelectorAll('.sidebar-row').length).toBe(1));
  });
});
