// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../../types';
import { RunStatusCard } from './RunStatusCard';
import { deriveRunPhase } from './runPhase';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../../services/api', () => ({
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: 'local-qwen-3.5', api_models_enabled: true }),
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

function render(task: DisplayableAgentTask, handlers: { onRetry?: (modelId?: string) => void } = {}) {
  act(() => {
    root.render(
      <RunStatusCard
        agentTask={task}
        phase={deriveRunPhase(task)}
        showTrail={false}
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
    expect(container.textContent).toContain('Details are in the result above');
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
