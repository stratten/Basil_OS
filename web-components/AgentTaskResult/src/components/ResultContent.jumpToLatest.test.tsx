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

const CLIENT_HEIGHT = 500;

const liveTask: DisplayableAgentTask = {
  agentTaskId: 'jump-task',
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

function withSegments(count: number): DisplayableAgentTask {
  return {
    ...liveTask,
    thinkingSegments: Array.from({ length: count }, (_, index) => ({
      iteration: index,
      text: `Reasoning step ${index}`,
      isComplete: true,
    })),
  };
}

let container: HTMLDivElement;
let root: Root;
let contentHeight = 0;
let storedScrollTop = 0;

function maxScrollTop(): number {
  return Math.max(0, contentHeight - CLIENT_HEIGHT);
}

function render(task: DisplayableAgentTask) {
  act(() => {
    root.render(<ResultContent agentTask={task} onRetry={() => {}} onContinue={() => {}} />);
  });
}

function scrollContainer(): HTMLElement {
  return container.querySelector<HTMLElement>('.main-content') as HTMLElement;
}

function fireScroll() {
  act(() => {
    scrollContainer().dispatchEvent(new Event('scroll', { bubbles: true }));
  });
}

function jumpButton(): Element | null {
  return container.querySelector('.execution-activity-dock-jump');
}

describe('ResultContent Jump to latest', () => {
  beforeEach(() => {
    resetPendingFollowUpsForTests();
    contentHeight = 0;
    storedScrollTop = 0;
    // jsdom has no layout, so the scroll geometry comes from these test-controlled accessors, with the browser's clamp on scrollTop.
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => contentHeight });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => CLIENT_HEIGHT });
    Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
      configurable: true,
      get: () => storedScrollTop,
      set: (value: number) => {
        storedScrollTop = Math.min(Math.max(0, value), maxScrollTop());
      },
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollHeight;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollTop;
  });

  it('stays hidden while the view follows reasoning steps that keep growing the content', () => {
    contentHeight = 600;
    render(withSegments(1));
    expect(storedScrollTop).toBe(100);

    // More content lands before the scroll event for the earlier jump is handled, so the view is briefly short of the new end.
    contentHeight = 900;
    fireScroll();
    render(withSegments(2));
    expect(storedScrollTop).toBe(400);
    expect(jumpButton()).toBeNull();

    contentHeight = 1200;
    fireScroll();
    render(withSegments(3));
    expect(jumpButton()).toBeNull();
  });

  it('stays hidden while everything fits in the view', () => {
    contentHeight = 300;
    render(withSegments(1));
    fireScroll();
    render(withSegments(2));
    render(withSegments(3));
    expect(jumpButton()).toBeNull();
  });

  it('appears when the reader scrolled up and new content is hidden below the fold, then clears at the end', () => {
    contentHeight = 900;
    render(withSegments(1));
    expect(storedScrollTop).toBe(400);

    act(() => {
      storedScrollTop = 100;
    });
    fireScroll();

    contentHeight = 1200;
    render(withSegments(2));
    expect(jumpButton()).not.toBeNull();
    expect(storedScrollTop).toBe(100);

    act(() => {
      storedScrollTop = maxScrollTop();
    });
    fireScroll();
    expect(jumpButton()).toBeNull();
  });

  it('withdraws the offer when the hidden content no longer extends below the fold', () => {
    contentHeight = 900;
    render(withSegments(1));
    act(() => {
      storedScrollTop = 100;
    });
    fireScroll();
    contentHeight = 1200;
    render(withSegments(2));
    expect(jumpButton()).not.toBeNull();

    contentHeight = 400;
    act(() => {
      storedScrollTop = 0;
    });
    render(withSegments(3));
    expect(jumpButton()).toBeNull();
  });
});
