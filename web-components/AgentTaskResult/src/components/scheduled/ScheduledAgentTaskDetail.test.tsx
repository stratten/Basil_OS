// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScheduledAgentTask, ScheduledAgentTaskRun } from '../../types';

const mocks = vi.hoisted(() => ({
  getScheduledAgentTask: vi.fn(),
  listScheduledAgentTaskRuns: vi.fn(),
  createScheduledAgentTask: vi.fn(),
  updateScheduledAgentTask: vi.fn(),
  getReasoningModels: vi.fn(),
  listScheduleConnections: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  getScheduledAgentTask: mocks.getScheduledAgentTask,
  listScheduledAgentTaskRuns: mocks.listScheduledAgentTaskRuns,
  createScheduledAgentTask: mocks.createScheduledAgentTask,
  updateScheduledAgentTask: mocks.updateScheduledAgentTask,
  getReasoningModels: mocks.getReasoningModels,
  listScheduleConnections: mocks.listScheduleConnections,
}));

vi.mock('../../services/bridge', () => ({
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

async function render(props: { createMode: boolean; id?: string; onUpdated?: (id: string) => void; scheduledListVersion?: number }) {
  await act(async () => {
    root.render(
      <ScheduledAgentTaskDetail
        scheduledAgentTaskId={props.id ?? null}
        createMode={props.createMode}
        onCreated={vi.fn()}
        onUpdated={props.onUpdated}
        scheduledListVersion={props.scheduledListVersion}
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

  // The names of every connection chip, apart from the warning note a chip may carry after its name.
  function connectionRowNames(): string[] {
    return Array.from(document.body.querySelectorAll<HTMLElement>('.icon-chip[data-chip-kind="connection"]'))
      .map(chip => chip.querySelector('.icon-chip__name')?.textContent ?? '');
  }

  // The warning note on each connection chip, in order; an empty string for a chip that has none.
  function connectionNotes(): string[] {
    return Array.from(document.body.querySelectorAll<HTMLElement>('.icon-chip[data-chip-kind="connection"]'))
      .map(chip => chip.querySelector('.icon-chip__note')?.textContent ?? '');
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

    expect(connectionRowNames()).toEqual(['Gmail', 'Slack', 'Linear', 'Removed connection']);
    expect(connectionNotes()).toEqual(['', 'switched off', 'needs signing in again', 'removed']);
  });

  it('shows connections as chips in their own Connections row, apart from the reference files', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [gmail] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ reference_paths: ['/Users/me/notes.md'], connection_ids: ['conn-gmail'] }));
    await render({ createMode: false, id: 'sched-1' });

    const chips = container.querySelector('.icon-chip-list')!;
    expect(chips.getAttribute('aria-label')).toBe('Connections');
    expect(Array.from(chips.querySelectorAll('.icon-chip__name')).map(name => name.textContent)).toEqual(['Gmail']);
    const files = container.querySelector('.attachment-list')!;
    expect(files.getAttribute('aria-label')).toBe('Attachments / References');
    expect(Array.from(files.querySelectorAll('.attachment-list__row-name')).map(name => name.textContent)).toEqual(['notes.md']);
    // A connection is not a file: it is not in the attachments list, so it has no Reveal in Finder and no open link.
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

  it('draws the bundled icon for a known connection by its server URL, even after it was renamed', async () => {
    const renamed = { ...gmail, friendly_name: 'Gmail - Work', server_url: 'https://gmailmcp.googleapis.com/mcp/v1' };
    const custom = { ...slack, id: 'conn-custom', friendly_name: 'Internal wiki', enabled: true, server_url: 'https://mcp.example.com/mcp' };
    mocks.listScheduleConnections.mockResolvedValue({ connections: [renamed, custom] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-gmail', 'conn-custom'] }));
    await render({ createMode: false, id: 'sched-1' });

    const chips = Array.from(container.querySelectorAll<HTMLElement>('.icon-chip[data-chip-kind="connection"]'));
    expect(chips.map(chip => chip.querySelector('.icon-chip__name')?.textContent)).toEqual(['Gmail - Work', 'Internal wiki']);
    expect(chips[0].querySelector('img.icon-chip__image')?.getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
    // A connection Basil does not know and whose server advertises nothing keeps the plug glyph.
    expect(chips[1].querySelector('img.icon-chip__image')).toBeNull();
    expect(chips[1].querySelector('.icon-chip__icon--glyph svg')).not.toBeNull();
  });

  it('prefers the icon the server advertises and falls back to the bundled one if it will not load', async () => {
    const advertised = 'data:image/png;base64,iVBORw0KGgo=';
    const linearWithIcon = { ...linear, last_connection_status: 'healthy', server_url: 'https://mcp.linear.app/mcp', server_icon_data_url: advertised };
    mocks.listScheduleConnections.mockResolvedValue({ connections: [linearWithIcon] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-linear'] }));
    await render({ createMode: false, id: 'sched-1' });

    const image = () => container.querySelector<HTMLImageElement>('.icon-chip img.icon-chip__image');
    expect(image()!.getAttribute('src')).toBe(advertised);
    await act(async () => { image()!.dispatchEvent(new Event('error')); });
    expect(image()!.getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
  });

  it('seats every connection icon on a light tile and keeps the warning note beside the name', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [{ ...linear, server_url: 'https://mcp.linear.app/mcp' }] });
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: ['conn-linear'] }));
    await render({ createMode: false, id: 'sched-1' });

    expect(container.querySelector('.icon-chip__icon--tile')).not.toBeNull();
    expect(container.querySelector('.icon-chip__note')?.textContent).toBe('needs signing in again');
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
    expect(connectionRowNames()).toEqual(['Gmail', 'Removed connection']);
    expect(connectionNotes()).toEqual(['', 'removed']);

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

describe('ScheduledAgentTaskDetail when the schedule changes elsewhere', () => {
  const indicator = () => document.body.querySelector('[aria-label="Active"], [aria-label="Inactive"]')!;

  it('fetches again when the list version changes, so a pause from the sidebar row shows here', async () => {
    mocks.getScheduledAgentTask.mockResolvedValueOnce(scheduledTask({ is_active: true }));
    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 0 });
    expect(buttonByText('Deactivate')).toBeTruthy();
    expect(mocks.getScheduledAgentTask).toHaveBeenCalledTimes(1);

    mocks.getScheduledAgentTask.mockResolvedValueOnce(scheduledTask({ is_active: false }));
    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 1 });

    expect(mocks.getScheduledAgentTask).toHaveBeenCalledTimes(2);
    expect(mocks.listScheduledAgentTaskRuns).toHaveBeenCalledTimes(2);
    expect(buttonByText('Activate')).toBeTruthy();
    expect(indicator().getAttribute('aria-label')).toBe('Inactive');
  });

  it('does not fetch again when it re-renders with the same version', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: true }));
    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 3 });
    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 3 });
    expect(mocks.getScheduledAgentTask).toHaveBeenCalledTimes(1);
  });

  it('keeps what the user is typing in the edit form when the version changes', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ is_active: true }));
    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 0 });
    await click(buttonByText('Edit'));
    await typeTaskText('A half-typed change');

    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 1 });

    expect(mocks.getScheduledAgentTask).toHaveBeenCalledTimes(1);
    expect(document.body.querySelector<HTMLTextAreaElement>('textarea[placeholder="Task text"]')?.value).toBe('A half-typed change');
  });

  it('keeps the current view and reports the error when the refresh fails', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    mocks.getScheduledAgentTask.mockResolvedValueOnce(scheduledTask({ is_active: true }));
    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 0 });

    mocks.getScheduledAgentTask.mockRejectedValueOnce(new Error('offline'));
    await render({ createMode: false, id: 'sched-1', scheduledListVersion: 1 });

    expect(buttonByText('Deactivate')).toBeTruthy();
    expect(error).toHaveBeenCalled();
    error.mockRestore();
  });
});

describe('ScheduledAgentTaskDetail form layout', () => {
  it('labels every row of the create form in one label column', async () => {
    mocks.listScheduleConnections.mockResolvedValue({ connections: [{ id: 'c', friendly_name: 'Gmail', description: null, enabled: true, last_connection_status: 'healthy' }] });
    await render({ createMode: true });

    const labels = Array.from(container.querySelectorAll('.scheduled-field__label')).map(label => label.textContent);
    expect(labels).toEqual(['Title', 'Task', 'Connections', 'Model', 'Schedule', 'Quiet hours', 'Runs']);
    // The Task box and the Title box are the form's own field style, not the sidebar search box.
    expect(container.querySelector('textarea[placeholder="Task text"]')!.className).toContain('scheduled-input');
    expect(container.querySelector('.sidebar-search-input')).toBeNull();
    // Labels name their controls.
    const title = container.querySelector<HTMLInputElement>('input[placeholder^="Title"]')!;
    expect(container.querySelector(`label[for="${title.id}"]`)?.textContent).toBe('Title');
  });

  it('keeps inline styles off everything the scheduled view draws itself', async () => {
    // The shared Dropdown and model picker set their own inline sizes; the scheduled view's own markup sets none.
    const ownStyled = () => container.querySelectorAll('[class*="scheduled-"][style], .icon-chip[style], .icon-chip-list[style], .attachment-area [style], .basil-switch[style]');
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ connection_ids: [], reference_paths: [] }));
    await render({ createMode: false, id: 'sched-1' });
    expect(container.querySelector('.scheduled-meta')).not.toBeNull();
    expect(ownStyled()).toHaveLength(0);
    await act(async () => {
      Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Edit')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.querySelector('.scheduled-form')).not.toBeNull();
    expect(ownStyled()).toHaveLength(0);
  });

  it('gives the read view one primary action and quiet secondary buttons, and shows the state once', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: false, id: 'sched-1' });

    const classOf = (text: string) => Array.from(container.querySelectorAll('button')).find(button => button.textContent === text)!.className;
    expect(classOf('Run Now')).toContain('primary');
    expect(classOf('Edit')).toContain('action-btn--neutral');
    expect(classOf('Deactivate')).toContain('action-btn--neutral');
    expect(container.querySelectorAll('.scheduled-detail__state')).toHaveLength(1);
    expect(container.querySelector('.scheduled-detail__state')!.textContent).toBe('Active');
    expect(container.querySelector('.scheduled-meta__label')?.textContent).toBe('Schedule');
    expect(Array.from(container.querySelectorAll('.scheduled-meta__label')).map(label => label.textContent)).not.toContain('Status');
  });

  it('shows the chain limits as switches, not native checkboxes', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ chain_config: { mode: 'chained', max_runs: 5 } }));
    await render({ createMode: false, id: 'sched-1' });
    await act(async () => {
      Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Edit')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    const switches = container.querySelectorAll('.basil-switch-input');
    expect(switches.length).toBeGreaterThanOrEqual(4);
    expect(container.querySelectorAll('input[type="checkbox"]:not(.basil-switch-input)')).toHaveLength(0);
  });
});
