// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScheduledAgentTaskRun } from '../../types';
import { formatRunDuration, scheduleFormBlocker } from './scheduledAgentTaskHelpers';
import ScheduledRunHistoryList from './ScheduledRunHistoryList';

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

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('formatRunDuration', () => {
  it('reads seconds, minutes and hours the way a person would', () => {
    expect(formatRunDuration('2026-11-16T10:00:00Z', '2026-11-16T10:00:45Z')).toBe('45s');
    expect(formatRunDuration('2026-11-16T10:00:00Z', '2026-11-16T10:03:12Z')).toBe('3m 12s');
    expect(formatRunDuration('2026-11-16T10:00:00Z', '2026-11-16T10:03:00Z')).toBe('3m');
    expect(formatRunDuration('2026-11-16T10:00:00Z', '2026-11-16T11:05:30Z')).toBe('1h 5m');
    expect(formatRunDuration('2026-11-16T10:00:00Z', '2026-11-16T11:00:00Z')).toBe('1h');
  });

  it('says nothing for a run that has not finished, or whose times cannot be trusted', () => {
    expect(formatRunDuration('2026-11-16T10:00:00Z', null)).toBeNull();
    expect(formatRunDuration(undefined, '2026-11-16T10:00:00Z')).toBeNull();
    expect(formatRunDuration('not a time', '2026-11-16T10:00:00Z')).toBeNull();
    expect(formatRunDuration('2026-11-16T10:05:00Z', '2026-11-16T10:00:00Z')).toBeNull();
  });
});

describe('scheduleFormBlocker', () => {
  it('names the first thing to fix, and nothing when the form is ready', () => {
    expect(scheduleFormBlocker({ taskText: '   ', firstRunIncomplete: true, formError: 'Too long' })).toBe('Describe what the task should do to continue.');
    expect(scheduleFormBlocker({ taskText: 'Check mail', firstRunIncomplete: true, formError: 'Too long' })).toBe('Add a time for the first run, or clear its date.');
    expect(scheduleFormBlocker({ taskText: 'Check mail', firstRunIncomplete: false, formError: 'Too long' })).toBe('Too long');
    expect(scheduleFormBlocker({ taskText: 'Check mail', firstRunIncomplete: false, formError: null })).toBeNull();
  });
});

describe('run history duration', () => {
  const run = (overrides: Partial<ScheduledAgentTaskRun>): ScheduledAgentTaskRun => ({
    id: 'run-1',
    scheduled_agent_task_id: 'sched-1',
    agent_task_id: null,
    scheduled_for: '2026-11-16T10:00:00Z',
    started_at: '2026-11-16T10:00:00Z',
    completed_at: '2026-11-16T10:03:12Z',
    status: 'completed',
    created_at: '2026-11-16T10:00:00Z',
    ...overrides,
  });

  it('is shown beside the start time for a finished run only', () => {
    expect(renderToStaticMarkup(<ScheduledRunHistoryList runs={[run({})]} />)).toContain(', took 3m 12s');
    expect(renderToStaticMarkup(<ScheduledRunHistoryList runs={[run({ completed_at: null })]} />)).not.toContain('took');
  });
});

describe('the scheduled form guidance', () => {
  let ScheduledAgentTaskDetail: typeof import('./ScheduledAgentTaskDetail').default;
  let container: HTMLDivElement;
  let root: Root;

  beforeAll(async () => {
    ScheduledAgentTaskDetail = (await import('./ScheduledAgentTaskDetail')).default;
  });

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

  const renderCreate = async () => {
    await act(async () => {
      root.render(<ScheduledAgentTaskDetail scheduledAgentTaskId={null} createMode onCreated={vi.fn()} onExitCreateMode={vi.fn()} />);
    });
  };

  it('groups the create form into Task, Tools and Schedule', async () => {
    await renderCreate();

    const headings = Array.from(container.querySelectorAll('.scheduled-section__heading')).map(node => node.textContent);
    expect(headings).toEqual(['Task', 'Tools', 'Schedule']);
    const sections = Array.from(container.querySelectorAll('section.scheduled-section'));
    expect(sections).toHaveLength(3);
    sections.forEach(section => expect(section.getAttribute('aria-labelledby')).toBe(section.querySelector('h4')!.id));
  });

  it('says why Create Schedule is dimmed and stops saying so once the task is described', async () => {
    await renderCreate();
    const create = Array.from(container.querySelectorAll('button')).find(node => node.textContent === 'Create Schedule') as HTMLButtonElement;

    expect(create.disabled).toBe(true);
    expect(container.querySelector('#schedule-form-blocker')?.textContent).toBe('Describe what the task should do to continue.');
    expect(create.getAttribute('aria-describedby')).toBe('schedule-form-blocker');

    const textarea = container.querySelector('textarea.scheduled-input--text') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    await act(async () => {
      setter.call(textarea, 'Summarize new email');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });

    expect(create.disabled).toBe(false);
    expect(container.querySelector('#schedule-form-blocker')).toBeNull();
    expect(create.hasAttribute('aria-describedby')).toBe(false);
  });
});
