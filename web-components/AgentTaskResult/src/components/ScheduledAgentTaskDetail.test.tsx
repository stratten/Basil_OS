// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScheduledAgentTask, ScheduledAgentTaskRun } from '../types';

const mocks = vi.hoisted(() => ({
  getScheduledAgentTask: vi.fn(),
  listScheduledAgentTaskRuns: vi.fn(),
  createScheduledAgentTask: vi.fn(),
  updateScheduledAgentTask: vi.fn(),
  getReasoningModels: vi.fn(),
  listScheduleConnections: vi.fn(),
}));

vi.mock('../services/api', () => ({
  getScheduledAgentTask: mocks.getScheduledAgentTask,
  listScheduledAgentTaskRuns: mocks.listScheduledAgentTaskRuns,
  createScheduledAgentTask: mocks.createScheduledAgentTask,
  updateScheduledAgentTask: mocks.updateScheduledAgentTask,
  getReasoningModels: mocks.getReasoningModels,
  listScheduleConnections: mocks.listScheduleConnections,
}));

vi.mock('../services/bridge', () => ({
  pickFiles: vi.fn(),
  registerFilesPickedHandler: () => () => {},
}));

let ScheduledAgentTaskDetail: typeof import('./ScheduledAgentTaskDetail').default;
let container: HTMLDivElement;
let root: Root;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeAll(async () => {
  ScheduledAgentTaskDetail = (await import('./ScheduledAgentTaskDetail')).default;
});

function scheduledTask(overrides: Partial<ScheduledAgentTask> = {}): ScheduledAgentTask {
  return {
    id: 'sched-1',
    title: 'Check email',
    agent_task_text: 'Summarize new email',
    schedule_type: 'recurring',
    schedule_config: { mode: 'interval', minutes: 15 },
    timezone: 'UTC',
    is_active: true,
    source_type: 'manual',
    reference_paths: [],
    model_id: null,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    run_count: 0,
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(mocks).forEach(mock => mock.mockReset());
  mocks.listScheduledAgentTaskRuns.mockResolvedValue([]);
  mocks.getReasoningModels.mockResolvedValue({
    current_model: 'claude-opus',
    api_models_enabled: true,
    models: [
      { id: 'claude-opus', name: 'claude-opus', display_name: 'Claude Opus', provider: 'anthropic', category: 'api', is_api_model: true },
      { id: 'qwen-4b', name: 'qwen-4b', display_name: 'Qwen 4B', provider: 'local', category: 'local', is_api_model: false },
    ],
  });
  mocks.listScheduleConnections.mockResolvedValue({ connections: [] });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = '';
});

async function render(props: { createMode: boolean; id?: string; onUpdated?: (id: string) => void }) {
  await act(async () => {
    root.render(
      <ScheduledAgentTaskDetail
        scheduledAgentTaskId={props.id ?? null}
        createMode={props.createMode}
        onCreated={vi.fn()}
        onUpdated={props.onUpdated}
        onExitCreateMode={vi.fn()}
      />,
    );
  });
}

function buttonByText(text: string): HTMLButtonElement {
  const match = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find(
    candidate => candidate.textContent?.trim() === text,
  );
  if (!match) throw new Error(`Expected a "${text}" button.`);
  return match;
}

function modelTrigger(): HTMLButtonElement {
  const match = document.body.querySelector<HTMLButtonElement>('button[aria-label="Scheduled task model"]');
  if (!match) throw new Error('Expected the model picker.');
  return match;
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

async function choose(optionLabel: string) {
  await click(modelTrigger());
  await click(
    Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]')).find(
      option => option.textContent === optionLabel,
    )!,
  );
}

async function typeTaskText(value: string) {
  const textarea = document.body.querySelector<HTMLTextAreaElement>('textarea[placeholder="Task text"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
  await act(async () => {
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('ScheduledAgentTaskDetail model selection', () => {
  it('creates a schedule with the chosen model', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'qwen-4b' }));
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    expect(modelTrigger().textContent).toContain('Default model');

    await choose('Qwen 4B');
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask).toHaveBeenCalledTimes(1);
    expect(mocks.createScheduledAgentTask.mock.calls[0][0]).toMatchObject({ model_id: 'qwen-4b' });
  });

  it('omits model_id when the default model is kept', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask.mock.calls[0][0]).not.toHaveProperty('model_id');
  });

  it('shows the pinned model in the read view', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'qwen-4b' }));
    await render({ createMode: false, id: 'sched-1' });
    expect(container.textContent).toContain('Model');
    expect(container.textContent).toContain('Qwen 4B');
  });

  it('shows Default model in the read view when nothing is pinned', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: false, id: 'sched-1' });
    expect(container.textContent).toContain('Default model');
  });

  it('changes the pinned model on edit', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'qwen-4b' }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'claude-opus' }));
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    expect(modelTrigger().textContent).toContain('Qwen 4B');

    await choose('Claude Opus');
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask).toHaveBeenCalledWith('sched-1', expect.objectContaining({ model_id: 'claude-opus' }));
  });

  it('sends an empty model_id to go back to the default model', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'qwen-4b' }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));

    await choose('Default model');
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask).toHaveBeenCalledWith('sched-1', expect.objectContaining({ model_id: '' }));
  });

  it('leaves the model out of an edit that did not change it', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'gone-model' }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'gone-model' }));
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    // A pin that is no longer installed stays visible but marked unavailable.
    expect(modelTrigger().textContent).toContain('gone-model (unavailable)');

    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1]).not.toHaveProperty('model_id');
  });

  it('still works when the model list cannot be loaded', async () => {
    mocks.getReasoningModels.mockRejectedValue(new Error('offline'));
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: false, id: 'sched-1' });
    expect(container.textContent).toContain('Default model');
  });

  it('shows a run notice in the run history', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ model_id: 'qwen-4b' }));
    const run: ScheduledAgentTaskRun = {
      id: 'run-1',
      scheduled_agent_task_id: 'sched-1',
      scheduled_for: '2026-01-01T09:00:00',
      started_at: '2026-01-01T09:00:01',
      status: 'completed',
      notice: 'The chosen model (qwen-4b) is not available, so this run used the default model.',
      created_at: '2026-01-01T09:00:00',
    };
    mocks.listScheduledAgentTaskRuns.mockResolvedValue([run]);
    await render({ createMode: false, id: 'sched-1' });
    expect(container.textContent).toContain('so this run used the default model.');
  });
});

describe('ScheduledAgentTaskDetail connections', () => {
  const gmail = { id: 'conn-gmail', friendly_name: 'Gmail', description: null, enabled: true, last_connection_status: 'healthy' };
  const slack = { id: 'conn-slack', friendly_name: 'Slack', description: null, enabled: false, last_connection_status: 'healthy' };
  const linear = { id: 'conn-linear', friendly_name: 'Linear', description: null, enabled: true, last_connection_status: 'needs_reconnect' };

  // The names of every row in the attachments list that is a connection (they share the list with the reference files).
  function connectionRowNames(): string[] {
    return Array.from(document.body.querySelectorAll<HTMLElement>('.attachment-list__row[data-attachment-kind="connection"]'))
      .map(row => row.querySelector('.attachment-list__row-name')?.textContent ?? '');
  }

  function stopUsingButton(name: string): HTMLButtonElement {
    const match = document.body.querySelector<HTMLButtonElement>(`button[aria-label="Stop using ${name}"]`);
    if (!match) throw new Error(`Expected a "Stop using ${name}" button.`);
    return match;
  }

  function connectionPicker(): HTMLButtonElement | null {
    return document.body.querySelector<HTMLButtonElement>('button[aria-label="Add a connection"]');
  }

  // The picker is the shared Dropdown: a trigger button that opens a listbox of options.
  function pickerOptions(): HTMLElement[] {
    return Array.from(document.body.querySelectorAll<HTMLElement>('.model-selector-dropdown [role="option"]'));
  }

  async function openPicker() {
    const picker = connectionPicker();
    if (!picker) throw new Error('Expected the connection picker.');
    await click(picker);
  }

  async function pickConnection(name: string) {
    await openPicker();
    const option = pickerOptions().find(candidate => candidate.querySelector('.model-option-name')?.textContent === name);
    if (!option) throw new Error(`Expected a "${name}" option in the connection picker.`);
    await click(option);
  }

  it('creates a schedule tied to the chosen connections', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail, slack] });
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail'] }));
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    expect(connectionRowNames()).toEqual([]);

    await pickConnection('Gmail');
    expect(connectionRowNames()).toEqual(['Gmail']);
    // A tagged connection leaves the picker, so it cannot be added twice.
    expect(connectionPicker()!.textContent).toContain('Add a connection…');
    await openPicker();
    expect(pickerOptions().map(option => option.textContent)).toEqual(['Slackswitched off']);
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask.mock.calls[0][0]).toMatchObject({ connection_ids: ['conn-gmail'] });
  });

  it('omits connection_ids when nothing is tagged', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail] });
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask.mock.calls[0][0]).not.toHaveProperty('connection_ids');
  });

  it('shows the tagged connections in the read view and flags the ones that cannot be used', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail, slack, linear] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail', 'conn-slack', 'conn-linear', 'conn-gone'] }));
    await render({ createMode: false, id: 'sched-1' });

    expect(connectionRowNames()).toEqual(['Gmail', 'Slack (switched off)', 'Linear (needs signing in again)', 'Removed connection (removed)']);
  });

  it('shows connections as chips in their own Connections row, apart from the reference files', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ reference_paths: ['/Users/me/notes.md'], connection_ids: ['conn-gmail'] }));
    await render({ createMode: false, id: 'sched-1' });

    const lists = Array.from(container.querySelectorAll('.attachment-list'));
    expect(lists.map(list => list.getAttribute('aria-label'))).toEqual(['Connections', 'Attachments / References']);
    expect(lists.map(list => Array.from(list.querySelectorAll('.attachment-list__row-name')).map(name => name.textContent))).toEqual([['Gmail'], ['notes.md']]);
    // A connection is not a file: no Reveal in Finder, and its name is not an open link.
    expect(container.querySelectorAll('.attachment-list__row-reveal')).toHaveLength(1);
    expect(container.querySelectorAll('.attachment-list__row-name.is-link')).toHaveLength(1);
  });

  it('keeps the connection picker out of the attachments section', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail] });
    await render({ createMode: true });

    const attachments = container.querySelector('.attachment-area')!;
    expect(attachments.contains(connectionPicker())).toBe(false);
    expect(connectionPicker()!.tagName).toBe('BUTTON');
    expect(container.querySelector('select')).toBeNull();
  });

  it('shows neutral rows when the connection list cannot be loaded', async () => {
    mocks.listScheduleConnections.mockRejectedValue(new Error('offline'));
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail', 'conn-slack'] }));
    await render({ createMode: false, id: 'sched-1' });

    expect(connectionRowNames()).toEqual(['Connection', 'Connection']);
    expect(container.textContent).not.toContain('Removed connection');
  });

  it('removes every tag on edit by sending an empty list', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail'] }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: [] }));
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    expect(connectionRowNames()).toEqual(['Gmail']);

    await click(stopUsingButton('Gmail'));
    expect(connectionRowNames()).toEqual([]);
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask).toHaveBeenCalledWith('sched-1', expect.objectContaining({ connection_ids: [] }));
  });

  it('leaves the tags out of an edit that did not change them', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail', 'conn-gone'] }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail', 'conn-gone'] }));
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    // A tag whose connection was removed stays visible so it can be untagged.
    expect(connectionRowNames()).toEqual(['Gmail', 'Removed connection (removed)']);

    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1]).not.toHaveProperty('connection_ids');
  });

  it('hides the picker and keeps the saved tags when the list cannot be loaded', async () => {
    mocks.listScheduleConnections.mockRejectedValue(new Error('offline'));
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail'] }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail'] }));
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));

    expect(connectionPicker()).toBeNull();
    expect(connectionRowNames()).toEqual(['Connection']);
    await click(buttonByText('Save changes'));
    expect(mocks.updateScheduledAgentTask.mock.calls[0][1]).not.toHaveProperty('connection_ids');
  });
});

describe('ScheduledAgentTaskDetail active indicator', () => {
  function indicator(): HTMLElement {
    const match = container.querySelector<HTMLElement>('.scheduled-detail__active-dot');
    if (!match) throw new Error('Expected the active indicator.');
    return match;
  }

  it('shows a solid dot for an active schedule', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: true }));
    await render({ createMode: false, id: 'sched-1' });
    expect(indicator().classList.contains('is-active')).toBe(true);
    expect(indicator().getAttribute('aria-label')).toBe('Active');
  });

  it('shows a hollow ring for an inactive schedule', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: false }));
    await render({ createMode: false, id: 'sched-1' });
    expect(indicator().classList.contains('is-inactive')).toBe(true);
    expect(indicator().classList.contains('is-active')).toBe(false);
    expect(indicator().getAttribute('aria-label')).toBe('Inactive');
  });

  it('tells the parent to reload the sidebar list when the schedule is deactivated', async () => {
    const onUpdated = vi.fn();
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: true }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: false }));
    await render({ createMode: false, id: 'sched-1', onUpdated });

    await click(buttonByText('Deactivate'));

    expect(mocks.updateScheduledAgentTask).toHaveBeenCalledWith('sched-1', { is_active: false });
    expect(onUpdated).toHaveBeenCalledTimes(1);
    expect(onUpdated).toHaveBeenCalledWith('sched-1');
    expect(indicator().classList.contains('is-inactive')).toBe(true);
    expect(buttonByText('Activate')).toBeTruthy();
  });

  it('tells the parent to reload the sidebar list when the schedule is activated', async () => {
    const onUpdated = vi.fn();
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: false }));
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: true }));
    await render({ createMode: false, id: 'sched-1', onUpdated });

    await click(buttonByText('Activate'));

    expect(onUpdated).toHaveBeenCalledTimes(1);
    expect(indicator().classList.contains('is-active')).toBe(true);
  });
});
