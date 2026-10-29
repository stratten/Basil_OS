// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../types';
import ResultContent from './ResultContent';
import { resetPendingFollowUpsForTests } from '../store/pendingFollowUps';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/bridge', () => ({
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
}));

vi.mock('../services/api', () => ({
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: 'local-qwen-3.5', api_models_enabled: true }),
  saveAgentTaskAsSkill: vi.fn(),
  submitAgentTaskFeedback: vi.fn(),
  isApiReady: vi.fn().mockReturnValue(false),
  getPendingFollowUps: vi.fn().mockResolvedValue({ follow_ups: [] }),
}));

const LONG_RESULT = Array.from({ length: 150 }, (_, index) => `finding${index}`).join(' ');

const liveTask: DisplayableAgentTask = {
  agentTaskId: 'paced-task',
  originalPrompt: 'Summarize everything',
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
let frameQueue: Map<number, FrameRequestCallback>;
let nextFrameId: number;
let clockMs: number;

function render(task: DisplayableAgentTask) {
  act(() => {
    root.render(<ResultContent agentTask={task} onRetry={() => {}} onContinue={() => {}} />);
  });
}

function advance(ms: number) {
  clockMs += ms;
  const due = [...frameQueue.values()];
  frameQueue.clear();
  act(() => {
    for (const callback of due) callback(clockMs);
  });
}

function drain() {
  for (let i = 0; i < 400 && frameQueue.size > 0; i += 1) advance(16);
}

function resultText(): string {
  return container.querySelector('.result-container')?.textContent ?? '';
}

describe('ResultContent paced reveal', () => {
  beforeEach(() => {
    resetPendingFollowUpsForTests();
    frameQueue = new Map();
    nextFrameId = 1;
    clockMs = 0;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = nextFrameId;
      nextFrameId += 1;
      frameQueue.set(id, callback);
      return id;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      frameQueue.delete(id);
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  it('reveals a large result that lands at once on a live run instead of showing it whole', () => {
    render(liveTask);
    render({ ...liveTask, status: 'completed', result: LONG_RESULT });

    const firstPaint = resultText();
    expect(firstPaint.length).toBeLessThan(LONG_RESULT.length);

    drain();
    expect(resultText()).toContain('finding149');
  });

  it('holds the footer back until the last word is revealed', () => {
    render({ ...liveTask, verificationStatus: 'resolved', modelUsed: 'gpt-5-mini' });
    render({
      ...liveTask,
      status: 'completed',
      result: LONG_RESULT,
      verificationStatus: 'resolved',
      outcome: 'success',
      modelUsed: 'gpt-5-mini',
    });

    expect(container.querySelector('.result-footer')).toBeNull();

    drain();
    expect(resultText()).toContain('finding149');
    expect(container.querySelector('.result-footer')).not.toBeNull();
  });

  it('shows a result opened from history in full with no reveal', () => {
    render({ ...liveTask, status: 'completed', result: LONG_RESULT });

    expect(resultText()).toContain('finding149');
  });
});
