// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScheduledAgentTask } from '../types';
import { summarizeSchedule, resolveFirstRunDate } from './scheduled/scheduledAgentTaskHelpers';

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
  mocks.getReasoningModels.mockResolvedValue({ current_model: 'm', api_models_enabled: true, models: [] });
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

async function render(props: { createMode: boolean; id?: string }) {
  await act(async () => {
    root.render(
      <ScheduledAgentTaskDetail
        scheduledAgentTaskId={props.id ?? null}
        createMode={props.createMode}
        onCreated={vi.fn()}
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

async function click(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

async function typeTaskText(value: string) {
  const textarea = document.body.querySelector<HTMLTextAreaElement>('textarea[placeholder="Task text"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
  await act(async () => {
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function chooseRecurringMode(optionLabel: string) {
  await click(document.body.querySelector<HTMLButtonElement>('button[aria-label="Recurring mode"]')!);
  await click(
    Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]')).find(
      option => option.textContent === optionLabel,
    )!,
  );
}

function timeInput(): HTMLInputElement | null {
  // The interval mode shows no other time input, so this is the first-run time.
  return document.body.querySelector<HTMLInputElement>('input[type="time"]');
}

function dateInput(): HTMLInputElement | null {
  return document.body.querySelector<HTMLInputElement>('input[type="date"]');
}

async function setInput(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

const futureInterval = (extra: Record<string, unknown> = {}) =>
  scheduledTask({ timezone: 'UTC', next_run_at: '2999-01-01T14:30:00+00:00', schedule_config: { mode: 'interval', minutes: 15, ...extra } });

describe('every-N-minutes first run', () => {
  it('only offers the first-run fields for the interval mode', async () => {
    await render({ createMode: true });
    expect(dateInput()).toBeNull();

    await chooseRecurringMode('Every N minutes');
    expect(dateInput()).not.toBeNull();
    expect(container.textContent).toContain('First run (optional)');

    await chooseRecurringMode('Weekly');
    expect(dateInput()).toBeNull();
  });

  it('creates an interval schedule with a first run on the chosen date', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await chooseRecurringMode('Every N minutes');
    await setInput(timeInput()!, '09:30');
    await setInput(dateInput()!, '2030-01-01');
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask.mock.calls[0][0].schedule_config).toEqual({
      mode: 'interval',
      minutes: 60,
      start_at: '2030-01-01T09:30',
    });
  });

  it('turns a bare time of day into its next occurrence, without needing a date', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await chooseRecurringMode('Every N minutes');
    await setInput(timeInput()!, '13:27');
    await click(buttonByText('Create Schedule'));

    const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const startAt = mocks.createScheduledAgentTask.mock.calls[0][0].schedule_config.start_at as string;
    expect(startAt).toBe(`${resolveFirstRunDate('13:27', userTz)}T13:27`);
  });

  it('leaves start_at out when no first run is chosen', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await chooseRecurringMode('Every N minutes');
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask.mock.calls[0][0].schedule_config).toEqual({ mode: 'interval', minutes: 60 });
  });

  it('refuses to save a date with no time instead of dropping it silently', async () => {
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await chooseRecurringMode('Every N minutes');
    await setInput(dateInput()!, '2030-01-01');

    expect(container.textContent).toContain('Add a time for the first run');
    expect(buttonByText('Create Schedule').disabled).toBe(true);

    await click(buttonByText('Clear'));
    expect(buttonByText('Create Schedule').disabled).toBe(false);
    expect(container.textContent).not.toContain('Add a time for the first run');
  });

  it('shows the upcoming run as the editable next run when editing', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(futureInterval());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));

    expect(container.textContent).toContain('Next run (optional)');
    expect(timeInput()!.value).toBe('14:30');
    expect(dateInput()!.value).toBe('2999-01-01');
  });

  it('changes the next run when the time is edited', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(futureInterval());
    mocks.updateScheduledAgentTask.mockResolvedValue(futureInterval());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    await setInput(timeInput()!, '13:27');
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1].schedule_config).toEqual({
      mode: 'interval',
      minutes: 15,
      start_at: '2999-01-01T13:27',
    });
  });

  it('keeps the upcoming run when an unrelated edit is saved', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(futureInterval());
    mocks.updateScheduledAgentTask.mockResolvedValue(futureInterval());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1].schedule_config).toEqual({
      mode: 'interval',
      minutes: 15,
      start_at: '2999-01-01T14:30',
    });
  });

  it('can clear the next run so the interval counts from the save', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(futureInterval());
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    await click(buttonByText('Clear'));
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1].schedule_config).toEqual({ mode: 'interval', minutes: 15 });
  });

  it('starts empty when the schedule has no run ahead of it', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask({ next_run_at: '2001-01-01T00:00:00+00:00' }));
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    expect(timeInput()!.value).toBe('');
    expect(dateInput()!.value).toBe('');
  });

  it('starts empty for a paused schedule even if a run time is on file', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue({ ...futureInterval(), is_active: false });
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    expect(timeInput()!.value).toBe('');
  });

  it('does not leak a first run into the next create form', async () => {
    await render({ createMode: true });
    await chooseRecurringMode('Every N minutes');
    await setInput(timeInput()!, '09:30');

    await render({ createMode: false, id: null as unknown as string });
    await render({ createMode: true });
    await chooseRecurringMode('Every N minutes');
    expect(timeInput()!.value).toBe('');
  });
});

describe('summarizeSchedule with a first run', () => {
  it('mentions a first run that is still ahead', () => {
    const summary = summarizeSchedule(
      scheduledTask({ schedule_config: { mode: 'interval', minutes: 30, start_at: '2999-01-01T09:30' } }),
    );
    expect(summary).toContain('Every 30 minutes, starting');
  });

  it('drops a first run that has passed or is malformed', () => {
    for (const startAt of ['2001-01-01T09:30', 'garbage', '']) {
      expect(
        summarizeSchedule(scheduledTask({ schedule_config: { mode: 'interval', minutes: 30, start_at: startAt } })),
      ).toBe('Every 30 minutes');
    }
  });
});
