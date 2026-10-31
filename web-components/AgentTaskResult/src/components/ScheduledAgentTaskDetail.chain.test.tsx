// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScheduledAgentTask } from '../types';

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

const CHAINED = { mode: 'chained', carry_over: true, max_runs: 8, max_age_minutes: 360 } as const;
const NIGHT = { start: '22:00', end: '07:00' };

function scheduledTask(overrides: Partial<ScheduledAgentTask> = {}): ScheduledAgentTask {
  return {
    id: 'sched-1',
    title: 'Check email',
    agent_task_text: 'Summarize new email',
    schedule_type: 'recurring',
    schedule_config: { mode: 'interval', minutes: 30 },
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
  mocks.getReasoningModels.mockResolvedValue({ current_model: 'claude-opus', api_models_enabled: true, models: [] });
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
        onUpdated={vi.fn()}
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

function byLabel<T extends HTMLElement>(label: string): T {
  const match = document.body.querySelector<T>(`[aria-label="${label}"]`);
  if (!match) throw new Error(`Expected an element labeled "${label}".`);
  return match;
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

async function chooseRunMode(optionLabel: string) {
  await click(byLabel('How runs relate to each other'));
  await click(
    Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]')).find(option => option.textContent === optionLabel)!,
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

describe('creating a schedule with chain and quiet-hours settings', () => {
  it('sends neither setting when both are left alone', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await click(buttonByText('Create Schedule'));

    const payload = mocks.createScheduledAgentTask.mock.calls[0][0];
    expect(payload).not.toHaveProperty('chain_config');
    expect(payload.schedule_config).not.toHaveProperty('exclusion_windows');
  });

  it('sends a chained config with the default limits and carry-over on', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await chooseRunMode('Runs continue one conversation');
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask.mock.calls[0][0].chain_config).toEqual({
      mode: 'chained',
      carry_over: true,
      max_runs: 24,
      max_age_minutes: 1440,
    });
  });

  it('sends the quiet-hours window that was added', async () => {
    mocks.createScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await click(buttonByText('Add quiet hours'));
    await click(buttonByText('Create Schedule'));

    expect(mocks.createScheduledAgentTask.mock.calls[0][0].schedule_config.exclusion_windows).toEqual([NIGHT]);
  });

  it('keeps Create disabled and explains why when a chained schedule has no limit', async () => {
    await render({ createMode: true });
    await typeTaskText('Summarize new email');
    await chooseRunMode('Runs continue one conversation');
    await click(byLabel('Limit the number of runs'));
    await click(byLabel('Limit how long one conversation lasts'));

    expect(buttonByText('Create Schedule').disabled).toBe(true);
    expect(document.body.textContent).toContain('Choose a run limit, a time limit, or both');
    expect(mocks.createScheduledAgentTask).not.toHaveBeenCalled();
  });

  it('hides both settings for a one-time schedule', async () => {
    await render({ createMode: true });
    expect(document.body.textContent).toContain('Quiet hours');
    await click(byLabel('Schedule type'));
    await click(Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]')).find(option => option.textContent === 'One-time')!);

    expect(document.body.textContent).not.toContain('Quiet hours');
    expect(document.body.querySelector('[aria-label="How runs relate to each other"]')).toBeNull();
  });
});

describe('reading and editing a schedule that has chain and quiet-hours settings', () => {
  const configured = () =>
    scheduledTask({ schedule_config: { mode: 'interval', minutes: 30, exclusion_windows: [NIGHT] }, chain_config: { ...CHAINED } });

  it('shows both settings in plain words in the read view', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(configured());
    await render({ createMode: false, id: 'sched-1' });

    expect(document.body.textContent).toContain('10:00 PM to 7:00 AM');
    expect(document.body.textContent).toContain('Continues one conversation, starting a new one after 8 runs or 6 hours, carrying the last result over');
  });

  it('shows neither row for a schedule that has neither setting', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: false, id: 'sched-1' });

    expect(document.body.textContent).not.toContain('Continues one conversation');
    expect(document.body.textContent).not.toContain('Quiet hours');
  });

  it('keeps the windows and does not resend an unchanged chain on an unrelated edit', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(configured());
    mocks.updateScheduledAgentTask.mockResolvedValue(configured());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    await click(buttonByText('Save changes'));

    const payload = mocks.updateScheduledAgentTask.mock.calls[0][1];
    expect(payload).not.toHaveProperty('chain_config');
    expect(payload.schedule_config.exclusion_windows).toEqual([NIGHT]);
  });

  it('sends the whole chain config when carry-over is switched off', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(configured());
    mocks.updateScheduledAgentTask.mockResolvedValue(configured());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    await click(byLabel('Carry the last result over to the new conversation'));
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1].chain_config).toEqual({
      mode: 'chained',
      carry_over: false,
      max_runs: 8,
      max_age_minutes: 360,
    });
  });

  it('removes the quiet-hours key from the saved config when the last window is removed', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(configured());
    mocks.updateScheduledAgentTask.mockResolvedValue(configured());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    await click(byLabel('Remove quiet hours window 1'));
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1].schedule_config).toEqual({ mode: 'interval', minutes: 30 });
  });

  it('sends independent runs when a chained schedule is switched to independent', async () => {
    mocks.getScheduledAgentTask.mockResolvedValue(configured());
    mocks.updateScheduledAgentTask.mockResolvedValue(scheduledTask());
    await render({ createMode: false, id: 'sched-1' });
    await click(buttonByText('Edit'));
    await chooseRunMode('Each run is its own task');
    await click(buttonByText('Save changes'));

    expect(mocks.updateScheduledAgentTask.mock.calls[0][1].chain_config).toEqual({ mode: 'independent' });
  });
});
