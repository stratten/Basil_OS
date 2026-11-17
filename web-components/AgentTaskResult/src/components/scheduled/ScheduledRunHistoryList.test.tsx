import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ScheduledRunHistoryList, { humanizeRunStatus } from './ScheduledRunHistoryList';
import type { ScheduledAgentTaskRun } from '../../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function run(overrides: Partial<ScheduledAgentTaskRun>): ScheduledAgentTaskRun {
  return {
    id: 'run-1',
    scheduled_agent_task_id: 'sched-1',
    agent_task_id: 'task-1',
    scheduled_for: '2026-10-22T10:00:00Z',
    started_at: '2026-10-22T10:00:01Z',
    status: 'completed',
    created_at: '2026-10-22T10:00:00Z',
    ...overrides,
  };
}

function render(overrides: Partial<ScheduledAgentTaskRun>) {
  return renderToStaticMarkup(<ScheduledRunHistoryList runs={[run(overrides)]} />);
}

describe('ScheduledRunHistoryList status language', () => {
  it('draws a partial result with the shared half-filled mark and the shared label', () => {
    const markup = render({ agent_task_status: 'failed', outcome: 'partial', verification_status: 'resolved', notice: 'Partial result: two of three feeds loaded' });

    expect(markup).toContain('run-status-dot--partial outcome-partial-mark');
    expect(markup).toContain('Partial result');
    expect(markup).toContain('Partial result: two of three feeds loaded');
    expect(markup).not.toContain('run-status-dot--danger');
  });

  it('draws a real failure with the failure dot and the shared label', () => {
    const markup = render({ status: 'failed', agent_task_status: 'failed', outcome: 'failed', verification_status: 'resolved', error_message: 'The feed was unreachable' });

    expect(markup).toContain('run-status-dot--danger');
    expect(markup).toContain('Couldn&#x27;t complete');
    expect(markup).toContain('The feed was unreachable');
  });

  it('draws a verified success and a result still being verified differently', () => {
    expect(render({ agent_task_status: 'completed', outcome: 'success', verification_status: 'resolved' })).toContain('run-status-dot--success');
    const verifying = render({ status: 'running', agent_task_status: 'failed', outcome: 'partial', verification_status: 'pending' });
    expect(verifying).toContain('execution-live-beacon');
    expect(verifying).toContain('Verifying the outcome');
  });

  it('keeps the run status word for a run that never reached an agent task', () => {
    const markup = render({ status: 'missed', agent_task_id: null, started_at: null });

    expect(markup).toContain('>Missed<');
    expect(markup).not.toContain('run-status-dot');
  });
});

describe('ScheduledRunHistoryList run messages', () => {
  it('draws markdown in an error and a notice instead of printing it raw', () => {
    const markup = render({ error_message: '**Origami:**\n\n- **#altbanq** failed', notice: 'See `run.log` for details' });

    expect(markup).toContain('<strong>Origami:</strong>');
    expect(markup).toContain('<li><strong>#altbanq</strong> failed</li>');
    expect(markup).toContain('<code>run.log</code>');
    expect(markup).not.toContain('**Origami:**');
    expect(markup).toContain('scheduled-run__message--error');
    expect(markup).toContain('scheduled-run__message--notice');
  });

  it('gives a failed run and a notice their own readable tones through classes, not inline styles', () => {
    const markup = render({ error_message: 'Broke', notice: 'Heads up' });

    expect(markup).not.toMatch(/ style=/);
    expect(markup).not.toContain('current-agent-task-label');
    expect(markup).not.toContain('--accent-base');
  });

  it('shows a plain run status in sentence case', () => {
    expect(render({ status: 'canceled', agent_task_id: null, started_at: null })).toContain('>Canceled<');
    expect(humanizeRunStatus('waiting_for_user')).toBe('Waiting for user');
    expect(humanizeRunStatus('')).toBe('');
  });
});

describe('ScheduledRunHistoryList long messages and navigation', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function draw(overrides: Partial<ScheduledAgentTaskRun>, onViewAgentTask = vi.fn()) {
    act(() => root.render(<ScheduledRunHistoryList runs={[run(overrides)]} onViewAgentTask={onViewAgentTask} />));
    return onViewAgentTask;
  }

  const toggle = () => container.querySelector<HTMLButtonElement>('.scheduled-run__toggle');
  const click = (element: Element) => act(() => { element.dispatchEvent(new MouseEvent('click', { bubbles: true })); });

  it('folds a long message behind Show more and unfolds it', () => {
    draw({ error_message: `${'A long failure report. '.repeat(30)}` });

    expect(toggle()!.textContent).toBe('Show more');
    expect(toggle()!.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('.basil-expandable-clamp__content.is-clamped')).not.toBeNull();
    click(toggle()!);
    expect(toggle()!.textContent).toBe('Show less');
    expect(toggle()!.getAttribute('aria-expanded')).toBe('true');
  });

  it('folds a message of many short lines, and leaves a short message with no toggle', () => {
    draw({ error_message: 'one\n\ntwo\n\nthree\n\nfour\n\nfive' });
    expect(toggle()).not.toBeNull();
    draw({ error_message: 'Short failure.' });
    expect(toggle()).toBeNull();
  });

  it('opens the run from the row, but not from the message or its toggle', () => {
    const onView = draw({ error_message: `${'A long failure report. '.repeat(30)}` });

    click(container.querySelector('.scheduled-run__message')!);
    click(toggle()!);
    expect(onView).not.toHaveBeenCalled();

    click(container.querySelector('.scheduled-run__head')!);
    expect(onView).toHaveBeenCalledWith('task-1');
  });

  it('opens the run on Enter from the row, but not on Enter from a control inside it', () => {
    const onView = draw({ error_message: `${'A long failure report. '.repeat(30)}` });
    const row = container.querySelector<HTMLElement>('.scheduled-run')!;

    act(() => { toggle()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
    expect(onView).not.toHaveBeenCalled();
    act(() => { row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
    expect(onView).toHaveBeenCalledWith('task-1');
  });
});
