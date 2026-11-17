// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../../types';
import { RunStatusCard, problemDetailFor } from './RunStatusCard';
import { reportProblem, showDiagnosticLogs } from '../../services/bridge';
import { deriveRunPhase } from './runPhase';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../../services/api', () => ({
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: 'local-qwen-3.5', api_models_enabled: true }),
}));

vi.mock('../../services/bridge', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/bridge')>()),
  reportProblem: vi.fn(),
  showDiagnosticLogs: vi.fn(),
}));

const baseTask: DisplayableAgentTask = {
  agentTaskId: 'task-1',
  originalPrompt: 'Summarize the report',
  status: 'completed',
  result: 'Done.',
  structuredFiles: [],
  referencePaths: [],
  agentTaskHistory: [],
  progressSteps: [],
  executionTimeline: [],
  stepDetails: [],
  showWorkflowPlan: false,
  isStreaming: false,
  checkpointAvailable: false,
  thinkingSegments: [],
  delegatedProviderReportCards: [],
};

let container: HTMLDivElement;
let root: Root;

function render(task: DisplayableAgentTask, handlers: { onRetry?: (modelId?: string) => void; showTrail?: boolean } = {}) {
  act(() => {
    root.render(
      <RunStatusCard
        agentTask={task}
        phase={deriveRunPhase(task)}
        showTrail={handlers.showTrail ?? false}
        hasUnreadLiveContent={false}
        onJumpToLatestContent={() => {}}
        onRetry={handlers.onRetry ?? (() => {})}
        onContinue={() => {}}
      />,
    );
  });
}

describe('RunStatusCard', () => {
  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  it('counts elapsed seconds while verifying and stops when the run settles', () => {
    vi.useFakeTimers();
    render({ ...baseTask, verificationStatus: 'pending' });
    expect(container.querySelector('.run-status-label')?.textContent).toContain('Verifying the outcome · 0s');

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(container.querySelector('.run-status-label')?.textContent).toContain('Verifying the outcome · 3s');
    expect(container.querySelector('.execution-live-beacon')).not.toBeNull();

    render({ ...baseTask, status: 'failed', errorMessage: 'Could not finish', verificationStatus: 'resolved' });
    expect(container.querySelector('.run-status-label')?.textContent).toBe("Couldn't complete");
    expect(container.querySelector('.execution-live-beacon')).toBeNull();
  });

  it('offers Retry on a failed run and passes the chosen model', () => {
    const onRetry = vi.fn();
    render({ ...baseTask, status: 'failed', errorMessage: 'Could not finish', selectedModelId: 'gpt-5-mini' }, { onRetry });

    const retry = Array.from(container.querySelectorAll('button')).find(button => button.textContent?.includes('Retry'));
    expect(retry).toBeDefined();
    act(() => retry?.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(onRetry).toHaveBeenCalledWith('gpt-5-mini');
  });

  it('keeps the activity trail folded on failed and canceled runs while the recovery actions and the reason stay visible', () => {
    render({ ...baseTask, status: 'failed', errorMessage: 'Could not finish' });
    expect(container.querySelector('.execution-activity-dock-body.is-open')).toBeNull();
    expect(container.querySelector('.run-status-footer')?.textContent).toContain('Could not finish');
    expect(container.querySelector('.execution-activity-dock-header-row .run-status-recovery')?.textContent).toContain('Retry');

    render({ ...baseTask, status: 'failed', isCanceled: true });
    expect(container.querySelector('.execution-activity-dock-body.is-open')).toBeNull();
    expect(container.querySelector('.execution-activity-dock-header-row .run-status-recovery')?.textContent).toContain('Run again');
  });

  it('draws the recovery actions as icon-only bordered buttons whose tooltips name and explain them', () => {
    render({ ...baseTask, status: 'failed', errorMessage: 'Could not finish', checkpointAvailable: true });

    const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>('.run-status-recovery .decision-btn'));
    expect(buttons.map(button => button.title)).toEqual([
      'Continue: pick up from where it stopped',
      'Retry: run this turn again',
      'Show logs: open the diagnostic logs for this run',
      'Report a problem: send details about this run',
    ]);
    expect(buttons.every(button => button.querySelector('.decision-btn__icon svg') !== null)).toBe(true);
    expect(container.querySelector('.run-status-recovery')!.parentElement!.classList.contains('execution-activity-dock-header-row--actions')).toBe(true);
    expect(container.querySelector('.execution-activity-dock-header button, button .decision-btn')).toBeNull();
  });

  it('puts the retry model picker in the bar row, just left of Retry and right of Continue', () => {
    render({ ...baseTask, status: 'failed', errorMessage: 'Could not finish', checkpointAvailable: true });

    const group = container.querySelector('.execution-activity-dock-header-row .run-status-recovery')!;
    const order = Array.from(group.children).map(child => (
      child.classList.contains('run-status-picker') ? 'picker' : (child as HTMLElement).title.split(':')[0]
    ));
    expect(order).toEqual(['Continue', 'picker', 'Retry', 'Show logs', 'Report a problem']);
    expect(group.querySelector('.run-status-picker button')?.getAttribute('aria-label')).toBe('Retry model');
    expect(container.querySelector('.execution-activity-dock-body.is-open')).toBeNull();
  });

  it('keeps the bar inert, with no chevron, when recovery is offered but there is no trail to open', () => {
    render({ ...baseTask, status: 'failed', errorMessage: 'Could not finish' });
    const header = container.querySelector<HTMLButtonElement>('.execution-activity-dock-header')!;

    expect(header.disabled).toBe(true);
    expect(header.hasAttribute('aria-expanded')).toBe(false);
    expect(header.querySelector('svg')).toBeNull();
    expect(container.querySelector('.execution-activity-dock-header-row--chevron')).toBeNull();
  });

  it('separates the status label from the summary with a small rule', () => {
    render({ ...baseTask, status: 'failed', errorMessage: 'Could not finish' });

    const label = container.querySelector('.run-status-label')!;
    const separator = container.querySelector('.run-status-separator')!;
    expect(separator.getAttribute('aria-hidden')).toBe('true');
    expect(label.nextElementSibling).toBe(separator);
    expect(separator.nextElementSibling?.classList.contains('execution-activity-dock-latest')).toBe(true);
  });

  it('shows the Activity count only where the bar can open the trail', () => {
    const task = { ...baseTask, status: 'failed' as const, errorMessage: 'Could not finish', progressSteps: [{ step: 'Read the file', isActive: false, isComplete: true }] };

    render(task, { showTrail: false });
    expect(container.querySelector('.execution-activity-dock-count')).toBeNull();

    render(task, { showTrail: true });
    expect(container.querySelector('.execution-activity-dock-count')?.textContent).toContain('Activity · 1 update');
    expect(container.querySelector<HTMLButtonElement>('.execution-activity-dock-header')!.disabled).toBe(false);
    expect(container.querySelector('.execution-activity-dock-header-row--chevron')).not.toBeNull();
  });

  it('offers no chevron and an inert header when a bar has nothing to open', () => {
    render({ ...baseTask, status: 'completed' });
    const header = container.querySelector<HTMLButtonElement>('.execution-activity-dock-header')!;

    expect(container.querySelector('.run-status-recovery')).toBeNull();
    expect(header.disabled).toBe(true);
    expect(header.hasAttribute('aria-expanded')).toBe(false);
    expect(header.querySelector('svg')).toBeNull();
  });

  it('offers Show logs and Report a problem on a failed run and sends the failure text', () => {
    vi.mocked(reportProblem).mockClear();
    vi.mocked(showDiagnosticLogs).mockClear();
    render({ ...baseTask, status: 'failed', errorMessage: 'The model ran out of memory.' });

    const button = (label: string) => Array.from(container.querySelectorAll('button')).find(candidate => candidate.textContent?.trim() === label);
    expect(button('Retry')).toBeDefined();
    act(() => button('Show logs')!.click());
    expect(showDiagnosticLogs).toHaveBeenCalledWith('The model ran out of memory.');
    expect(reportProblem).not.toHaveBeenCalled();

    act(() => button('Report a problem')!.click());
    expect(reportProblem).toHaveBeenCalledWith('The model ran out of memory.');
  });

  it('sends no detail when the failed run reported no reason', () => {
    vi.mocked(reportProblem).mockClear();
    render({ ...baseTask, status: 'failed' });

    const report = Array.from(container.querySelectorAll('button')).find(candidate => candidate.textContent?.trim() === 'Report a problem');
    act(() => report!.click());
    expect(reportProblem).toHaveBeenCalledWith(undefined);
  });

  it('does not offer Show logs or Report a problem on a canceled run or a run that succeeded', () => {
    render({ ...baseTask, status: 'failed', isCanceled: true });
    expect(container.textContent).not.toContain('Show logs');
    expect(container.textContent).not.toContain('Report a problem');

    render({ ...baseTask, status: 'completed' });
    expect(container.textContent).not.toContain('Show logs');
    expect(container.textContent).not.toContain('Report a problem');
  });

  it('keeps the problem detail short, plain, and on one line', () => {
    expect(problemDetailFor({ ...baseTask, errorMessage: '**Bad**\n\n  thing   happened' })).toBe('Bad thing happened');
    expect(problemDetailFor({ ...baseTask, errorMessage: 'x'.repeat(900) })).toHaveLength(500);
    expect(problemDetailFor({ ...baseTask, errorMessage: '   ' })).toBeUndefined();
    expect(problemDetailFor(baseTask)).toBeUndefined();
  });

  it('offers Run again on a canceled run with neutral styling', () => {
    render({ ...baseTask, status: 'failed', isCanceled: true });

    expect(container.querySelector('.run-status-card--neutral')).not.toBeNull();
    expect(container.textContent).toContain('Canceled');
    expect(container.textContent).toContain('Run again');
    expect(container.textContent).not.toContain('Retry');
    expect(container.querySelector('.run-status-dot--danger')).toBeNull();
  });

  it('does not repeat a partial result that the Result section already shows, but keeps the recovery actions', () => {
    const finalMessage = 'Here is what I found.\n\nThe second report could not be opened.';
    render({ ...baseTask, status: 'failed', outcome: 'partial', result: finalMessage, errorMessage: finalMessage });

    expect(container.querySelector('.run-status-reason')).toBeNull();
    expect(container.textContent).not.toContain('The second report could not be opened.');
    expect(container.textContent).toContain('Details above');
    expect(container.textContent).toContain('Retry');
  });

  it('shows a distinct failure reason when the result says something else', () => {
    render({ ...baseTask, status: 'failed', result: 'Partial notes', errorMessage: 'The model stopped responding' });

    expect(container.querySelector('.run-status-reason')?.textContent).toContain('The model stopped responding');
  });

  it('offers no recovery action while verifying, even when a provisional error is present', () => {
    render({ ...baseTask, status: 'failed', errorMessage: 'provisional', verificationStatus: 'pending' });

    expect(container.textContent).not.toContain('Retry');
    expect(container.textContent).not.toContain('Run again');
  });
});
