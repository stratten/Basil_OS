// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../../types';
import { RunStatusCard } from './RunStatusCard';
import { activitySignature, formatQuietNotice } from './quietActivity';
import { deriveRunPhase } from './runPhase';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../../services/api', () => ({
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: 'local-qwen-3.5', api_models_enabled: true }),
}));

const workingTask: DisplayableAgentTask = {
  agentTaskId: 'task-quiet',
  originalPrompt: 'Check disk usage',
  status: 'processing',
  result: '',
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

function render(task: DisplayableAgentTask) {
  act(() => {
    root.render(
      <RunStatusCard
        agentTask={task}
        phase={deriveRunPhase(task)}
        showTrail={false}
        hasUnreadLiveContent={false}
        onJumpToLatestContent={() => {}}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );
  });
}

function statusText(): string {
  return container.querySelector('.run-status-label')?.textContent ?? '';
}

describe('formatQuietNotice', () => {
  it('reads in seconds below a minute', () => {
    expect(formatQuietNotice(45)).toBe('No new activity for 45s');
  });

  it('reads in minutes and zero-padded seconds from a minute up', () => {
    expect(formatQuietNotice(60)).toBe('No new activity for 1m 00s');
    expect(formatQuietNotice(125)).toBe('No new activity for 2m 05s');
  });

  it('never reports a negative duration', () => {
    expect(formatQuietNotice(-3)).toBe('No new activity for 0s');
  });
});

describe('activitySignature', () => {
  it('changes with new steps, more result text, and more reasoning, and not otherwise', () => {
    const base = activitySignature(workingTask);

    expect(activitySignature({ ...workingTask })).toBe(base);
    expect(activitySignature({ ...workingTask, currentStep: 'Reading the file' })).not.toBe(base);
    expect(activitySignature({ ...workingTask, result: 'Partial answer' })).not.toBe(base);
    expect(activitySignature({
      ...workingTask,
      thinkingSegments: [{ iteration: 1, text: 'Considering options', isComplete: false }],
    })).not.toBe(base);
    expect(activitySignature({
      ...workingTask,
      executionTimeline: [{ id: 'e1', type: 'step', content: 'Planning', timestamp: '2026-10-27T15:00:00Z' }],
    })).not.toBe(base);
  });
});

describe('RunStatusCard quiet notice', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  it('says nothing while a working run is within normal latency', () => {
    render(workingTask);
    act(() => { vi.advanceTimersByTime(29_000); });

    expect(statusText()).toBe('Working');
  });

  it('reports the silence once a working run has produced nothing for 30 seconds', () => {
    render(workingTask);
    act(() => { vi.advanceTimersByTime(45_000); });

    expect(statusText()).toContain('Working · No new activity for 45s');
  });

  it('clears the notice the moment new activity arrives', () => {
    render(workingTask);
    act(() => { vi.advanceTimersByTime(45_000); });
    expect(statusText()).toContain('No new activity');

    render({ ...workingTask, currentStep: 'Reading the output' });

    expect(statusText()).toBe('Working');
  });

  it('keeps counting from the last change rather than from the notice', () => {
    render(workingTask);
    act(() => { vi.advanceTimersByTime(20_000); });
    render({ ...workingTask, result: 'Streaming text' });
    act(() => { vi.advanceTimersByTime(35_000); });

    expect(statusText()).toContain('No new activity for 35s');
  });

  it('adds the silence after the elapsed time while verifying', () => {
    render({ ...workingTask, status: 'completed', verificationStatus: 'pending', result: 'Done.' });
    act(() => { vi.advanceTimersByTime(40_000); });

    expect(statusText()).toContain('Verifying the outcome · 40s · No new activity for 40s');
  });

  it('never reports silence for a settled run', () => {
    render({ ...workingTask, status: 'completed', result: 'Done.' });
    act(() => { vi.advanceTimersByTime(120_000); });

    expect(statusText()).not.toContain('No new activity');
  });
});
