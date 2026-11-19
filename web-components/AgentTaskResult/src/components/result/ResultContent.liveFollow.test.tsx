// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask, TimelineEntry } from '../../types';
import ResultContent from './ResultContent';
import { resetPendingFollowUpsForTests } from '../../store/pendingFollowUps';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../../services/bridge', () => ({
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: 'local-qwen-3.5', api_models_enabled: true }),
  saveAgentTaskAsSkill: vi.fn(),
  submitAgentTaskFeedback: vi.fn(),
  isApiReady: vi.fn().mockReturnValue(false),
  getPendingFollowUps: vi.fn().mockResolvedValue({ follow_ups: [] }),
}));

const CLIENT_HEIGHT = 500;

const baseTask: DisplayableAgentTask = {
  agentTaskId: 'task-a',
  originalPrompt: 'Polish the UI',
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

const asked = (id: string): TimelineEntry => ({ id, type: 'step', content: 'Basil asked to run', timestamp: '2026-11-19T07:00:00.000Z' });

class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  readonly observed = new Set<Element>();
  constructor(readonly callback: ResizeObserverCallback) {
    FakeResizeObserver.instances.push(this);
  }
  observe(target: Element) {
    this.observed.add(target);
  }
  unobserve(target: Element) {
    this.observed.delete(target);
  }
  disconnect() {
    this.observed.clear();
  }
}

let container: HTMLDivElement;
let root: Root;
let contentHeight = 0;
let storedScrollTop = 0;

const maxScrollTop = () => Math.max(0, contentHeight - CLIENT_HEIGHT);

function render(task: DisplayableAgentTask) {
  act(() => {
    root.render(<ResultContent agentTask={task} onRetry={() => {}} onContinue={() => {}} />);
  });
}

function fireScroll() {
  act(() => {
    container.querySelector('.main-content')?.dispatchEvent(new Event('scroll', { bubbles: true }));
  });
}

/** The content grows without any render, the way an animating card does. */
function growTo(height: number) {
  contentHeight = height;
  act(() => {
    FakeResizeObserver.instances.forEach(observer => observer.callback([], observer as unknown as ResizeObserver));
  });
}

describe('ResultContent follows a live thread to its end', () => {
  beforeEach(() => {
    resetPendingFollowUpsForTests();
    contentHeight = 0;
    storedScrollTop = 0;
    FakeResizeObserver.instances = [];
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
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
    vi.unstubAllGlobals();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollHeight;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollTop;
  });

  it('goes to the end when a run starts waiting on an approval, and not only while it is working', () => {
    contentHeight = 900;
    render(baseTask);
    expect(storedScrollTop).toBe(400);

    // The approval arrives: the status leaves "processing" and a timeline entry lands, and so does more content.
    contentHeight = 1300;
    render({ ...baseTask, status: 'awaitingInput', executionTimeline: [asked('user_interaction_1')] });

    expect(storedScrollTop).toBe(800);
  });

  it('opens a run that is waiting on the reader at its end, not at the top of its turn', () => {
    contentHeight = 1500;
    render({ ...baseTask, status: 'awaitingInput', executionTimeline: [asked('user_interaction_1')] });

    expect(storedScrollTop).toBe(1000);
  });

  it('follows content that keeps growing after the render that added it', () => {
    contentHeight = 900;
    render({ ...baseTask, status: 'awaitingInput', executionTimeline: [asked('user_interaction_1')] });
    expect(storedScrollTop).toBe(400);

    growTo(1100);
    expect(storedScrollTop).toBe(600);
    growTo(1250);
    expect(storedScrollTop).toBe(750);
  });

  it('watches a child that is added after the first render', () => {
    contentHeight = 700;
    render(baseTask);
    const observer = FakeResizeObserver.instances[FakeResizeObserver.instances.length - 1];
    const before = observer.observed.size;

    const added = document.createElement('div');
    act(() => {
      container.querySelector('.main-content')?.appendChild(added);
    });
    // The observers batch their work, so the child is picked up through the mutation observer on the next microtask.
    return Promise.resolve().then(() => {
      expect(observer.observed.has(added)).toBe(true);
      expect(observer.observed.size).toBe(before + 1);
    });
  });

  it('does not pull a reader back who scrolled away from the end', () => {
    contentHeight = 900;
    render(baseTask);
    act(() => {
      storedScrollTop = 100;
    });
    fireScroll();

    growTo(1300);
    expect(storedScrollTop).toBe(100);
    render({ ...baseTask, status: 'awaitingInput', executionTimeline: [asked('user_interaction_1')] });
    expect(storedScrollTop).toBe(100);
  });

  it('takes a live run opened from another run to its end even when the first run was being read earlier', () => {
    contentHeight = 900;
    render(baseTask);
    act(() => {
      storedScrollTop = 50;
    });
    fireScroll();
    expect(storedScrollTop).toBe(50);

    contentHeight = 1600;
    render({ ...baseTask, agentTaskId: 'task-b', executionTimeline: [asked('user_interaction_2')] });

    expect(storedScrollTop).toBe(1100);
  });

  it('leaves a settled run alone when its content changes size', () => {
    contentHeight = 900;
    render({ ...baseTask, status: 'completed', result: 'Done.' });
    act(() => {
      storedScrollTop = 0;
    });
    fireScroll();

    growTo(1400);
    expect(storedScrollTop).toBe(0);
  });
});
