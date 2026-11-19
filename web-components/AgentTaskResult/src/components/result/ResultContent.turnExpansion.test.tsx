// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../../types';
import ResultContent from './ResultContent';
import { applyHostChainExpansion } from '../../app/display/chainExpansionPreference';
import { resetPendingFollowUpsForTests } from '../../store/pendingFollowUps';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../../services/bridge', () => ({
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  saveAgentTaskAsSkill: vi.fn(),
  submitAgentTaskFeedback: vi.fn(),
  isApiReady: vi.fn().mockReturnValue(false),
  getPendingFollowUps: vi.fn().mockResolvedValue({ follow_ups: [] }),
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: '', api_models_enabled: false }),
}));

function priorTurn(id: string, text: string) {
  return {
    id,
    agentTaskText: text,
    result: `Result of ${text}`,
    status: 'completed',
    files: [],
    reference_paths: [],
    timestamp: '2026-09-24T12:00:00.000Z',
  };
}

const chainTask: DisplayableAgentTask = {
  agentTaskId: 'task-1',
  rootTaskId: 'root-task',
  originalPrompt: 'Third question',
  status: 'completed',
  result: 'Third answer.',
  structuredFiles: [],
  referencePaths: [],
  currentTurnTaskId: 'turn-3',
  agentTaskHistory: [priorTurn('root-task', 'First question'), priorTurn('turn-2', 'Second question')],
  progressSteps: [],
  executionTimeline: [],
  stepDetails: [],
  showWorkflowPlan: false,
  isStreaming: false,
  checkpointAvailable: false,
  thinkingSegments: [],
  delegatedProviderReportCards: [],
} as DisplayableAgentTask;

function mountResult(props: Partial<React.ComponentProps<typeof ResultContent>> = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const render = (next: Partial<React.ComponentProps<typeof ResultContent>> = {}) => {
    act(() => {
      root.render(<ResultContent agentTask={chainTask} onRetry={() => {}} onContinue={() => {}} {...props} {...next} />);
    });
  };
  render();
  return {
    container,
    render,
    cleanup: () => {
      act(() => { root.unmount(); });
      container.remove();
    },
  };
}

function expandedRunIds(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll<HTMLElement>('.history-card--expanded'))
    .map(card => card.dataset.runContent ?? '');
}

function clickCard(container: HTMLElement, runId: string) {
  act(() => { container.querySelector<HTMLElement>(`[data-run-content="${runId}"]`)!.click(); });
}

function controlButton(container: HTMLElement, label: string): HTMLButtonElement | null {
  return container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
}

describe('ResultContent earlier turn expansion', () => {
  beforeEach(() => {
    resetPendingFollowUpsForTests();
    applyHostChainExpansion('single');
  });

  afterEach(() => {
    applyHostChainExpansion(undefined);
  });

  it('keeps one earlier turn open at a time in single mode and offers only a collapse button while one is open', () => {
    const view = mountResult();
    try {
      expect(expandedRunIds(view.container)).toEqual([]);
      expect(controlButton(view.container, 'Collapse all earlier turns')).toBeNull();
      expect(controlButton(view.container, 'Expand all earlier turns')).toBeNull();

      clickCard(view.container, 'root-task');
      clickCard(view.container, 'turn-2');
      expect(expandedRunIds(view.container)).toEqual(['turn-2']);
      expect(controlButton(view.container, 'Expand all earlier turns')).toBeNull();

      act(() => { controlButton(view.container, 'Collapse all earlier turns')!.click(); });
      expect(expandedRunIds(view.container)).toEqual([]);
      expect(controlButton(view.container, 'Collapse all earlier turns')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('keeps several earlier turns open in multiple mode and toggles each independently', () => {
    applyHostChainExpansion('multiple');
    const view = mountResult();
    try {
      clickCard(view.container, 'root-task');
      clickCard(view.container, 'turn-2');
      expect(expandedRunIds(view.container).sort()).toEqual(['root-task', 'turn-2']);
      expect(controlButton(view.container, 'Expand all earlier turns')!.disabled).toBe(true);

      clickCard(view.container, 'root-task');
      expect(expandedRunIds(view.container)).toEqual(['turn-2']);
      expect(controlButton(view.container, 'Expand all earlier turns')!.disabled).toBe(false);
    } finally {
      view.cleanup();
    }
  });

  it('expands and collapses every earlier turn from the toolbar in multiple mode', () => {
    applyHostChainExpansion('multiple');
    const view = mountResult();
    try {
      expect(controlButton(view.container, 'Collapse all earlier turns')!.disabled).toBe(true);

      act(() => { controlButton(view.container, 'Expand all earlier turns')!.click(); });
      expect(expandedRunIds(view.container).sort()).toEqual(['root-task', 'turn-2']);

      act(() => { controlButton(view.container, 'Collapse all earlier turns')!.click(); });
      expect(expandedRunIds(view.container)).toEqual([]);
    } finally {
      view.cleanup();
    }
  });

  it('trims to the most recently opened turn when the setting changes from multiple to single', () => {
    applyHostChainExpansion('multiple');
    const view = mountResult();
    try {
      clickCard(view.container, 'root-task');
      clickCard(view.container, 'turn-2');
      act(() => { applyHostChainExpansion('single'); });
      expect(expandedRunIds(view.container)).toEqual(['turn-2']);
    } finally {
      view.cleanup();
    }
  });

  it('opens a navigated earlier turn without closing the others in multiple mode', () => {
    applyHostChainExpansion('multiple');
    const view = mountResult();
    try {
      clickCard(view.container, 'root-task');
      view.render({ navigationRequest: { nonce: 1, runId: 'turn-2', target: { kind: 'run' } } });
      expect(expandedRunIds(view.container).sort()).toEqual(['root-task', 'turn-2']);
    } finally {
      view.cleanup();
    }
  });

  it('replaces the open turn with a navigated earlier turn in single mode', () => {
    const view = mountResult();
    try {
      clickCard(view.container, 'root-task');
      view.render({ navigationRequest: { nonce: 1, runId: 'turn-2', target: { kind: 'run' } } });
      expect(expandedRunIds(view.container)).toEqual(['turn-2']);
    } finally {
      view.cleanup();
    }
  });

  it('renders no toolbar for a single-turn task', () => {
    applyHostChainExpansion('multiple');
    const view = mountResult({ agentTask: { ...chainTask, agentTaskHistory: [] } as DisplayableAgentTask });
    try {
      expect(view.container.querySelector('.turn-expansion-controls')).toBeNull();
    } finally {
      view.cleanup();
    }
  });
});

describe('ResultContent opening a finished task', () => {
  const originalScrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');

  beforeEach(() => {
    resetPendingFollowUpsForTests();
    applyHostChainExpansion('single');
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => 1840 });
  });

  afterEach(() => {
    if (originalScrollHeight) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', originalScrollHeight);
    else delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollHeight;
    applyHostChainExpansion(undefined);
  });

  it('opens a finished multi-turn task at the very bottom, not at the top of its latest request', () => {
    const view = mountResult();
    try {
      expect(view.container.querySelector<HTMLElement>('.main-content')!.scrollTop).toBe(1840);
    } finally {
      view.cleanup();
    }
  });

  it('opens a finished single-turn task at the very bottom too', () => {
    const view = mountResult({ agentTask: { ...chainTask, agentTaskHistory: [] } as DisplayableAgentTask });
    try {
      expect(view.container.querySelector<HTMLElement>('.main-content')!.scrollTop).toBe(1840);
    } finally {
      view.cleanup();
    }
  });

  it('does not jump to the end on open while the task is still running, because live output follows the bottom itself', () => {
    // The live-follow effect also scrolls a running task, so give it nothing to scroll to and check the open effect adds nothing.
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => 0 });
    const view = mountResult({ agentTask: { ...chainTask, status: 'processing' } as DisplayableAgentTask });
    try {
      expect(view.container.querySelector<HTMLElement>('.main-content')!.scrollTop).toBe(0);
    } finally {
      view.cleanup();
    }
  });

  it('does not scroll when the caller is about to jump to a specific turn', () => {
    const view = mountResult({ suppressOpenAtLatest: true });
    try {
      expect(view.container.querySelector<HTMLElement>('.main-content')!.scrollTop).toBe(0);
    } finally {
      view.cleanup();
    }
  });

  it('scrolls only once per task, not again when the task object updates', () => {
    const view = mountResult();
    try {
      const main = view.container.querySelector<HTMLElement>('.main-content')!;
      main.scrollTop = 40;
      view.render({ agentTask: { ...chainTask, result: 'Third answer, revised.' } as DisplayableAgentTask });
      expect(main.scrollTop).toBe(40);
    } finally {
      view.cleanup();
    }
  });
});
