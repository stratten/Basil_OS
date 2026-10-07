// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask, StructuredFile } from '../types';
import type {
  AgentTaskArtifactHttpResponse,
  AgentTaskPresentationSummary,
} from '../artifacts/artifactContract';
import ResultContent from './ResultContent';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/bridge', () => ({
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({
  getReasoningModels: vi.fn().mockResolvedValue({
    models: [
      { id: 'local-qwen-3.5', name: 'Qwen 3.5', display_name: 'Qwen 3.5', provider: 'local', category: 'local', is_api_model: false },
      { id: 'gpt-5-mini', name: 'GPT-5 mini', display_name: 'GPT-5 mini', provider: 'openai', category: 'api', is_api_model: true },
    ],
    current_model: 'local-qwen-3.5',
    api_models_enabled: true,
  }),
  saveAgentTaskAsSkill: vi.fn(),
  submitAgentTaskFeedback: vi.fn(),
}));

vi.mock('../services/api', () => apiMocks);

const completedTask: DisplayableAgentTask = {
  agentTaskId: 'task-1',
  originalPrompt: 'Summarize the report',
  status: 'completed',
  result: 'The report has been summarized.',
  structuredFiles: [],
  referencePaths: [],
  agentTaskHistory: [],
  progressSteps: [],
  executionTimeline: [{
    id: 'step-1',
    type: 'step',
    timestamp: '2026-07-30T12:00:00Z',
    content: 'Read the report',
    metadata: { progress_step: 'Read the report' },
  }],
  stepDetails: [],
  showWorkflowPlan: false,
  isStreaming: false,
  checkpointAvailable: false,
  thinkingSegments: [{ iteration: 1, text: 'I will review the report.', isComplete: true }],
  delegatedProviderReportCards: [],
};

const presentationSummary: AgentTaskPresentationSummary = {
  agentTaskId: 'task-1',
  lifecycle: 'completed',
  workflow: {},
  artifacts: [],
  artifactCount: 0,
  verificationStatus: 'resolved',
  requiresUserAttention: false,
  delegatedProviderReportCards: [],
};

const reportArtifact: AgentTaskArtifactHttpResponse = {
  artifact_id: 'report-artifact',
  display_name: 'report.md',
  local_path: '/tmp/report.md',
  artifact_kind: 'file',
  operation: 'create',
  lifecycle: 'ready',
  preview: { capability: 'unknown' },
  verification: { status: 'unknown' },
};

const reportFile: StructuredFile = {
  name: 'report.md',
  path: '/tmp/report.md',
  operation: 'create',
  artifact: reportArtifact,
};

describe('ResultContent completed activity history', () => {
  it('moves completed activity below reasoning instead of retaining the live dock', () => {
    const markup = renderToStaticMarkup(
      <ResultContent agentTask={completedTask} onRetry={() => {}} onContinue={() => {}} />,
    );

    const thinkingIndex = markup.indexOf('thinking-segments');
    const activityIndex = markup.indexOf('activity-summary');
    const resultIndex = markup.indexOf('Result:');

    expect(thinkingIndex).toBeGreaterThanOrEqual(0);
    expect(activityIndex).toBeGreaterThan(thinkingIndex);
    expect(activityIndex).toBeLessThan(resultIndex);
    expect(markup).not.toContain('execution-activity-dock');
  });

  it('keeps activity in the dock while processing', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{ ...completedTask, status: 'processing', result: '' }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).toContain('execution-activity-dock');
    expect(markup).not.toContain('activity-summary');
  });

  it('does not mount an empty inline activity container when a completed task has no activity', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{ ...completedTask, executionTimeline: [] }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('margin-bottom:var(--padding-m)');
  });

  it('collapses inline completed activity when focus moves to another task', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ResultContent agentTask={completedTask} onRetry={() => {}} onContinue={() => {}} />);
      });
      const firstHeader = container.querySelector<HTMLButtonElement>('.activity-summary-header');
      expect(firstHeader?.getAttribute('aria-expanded')).toBe('false');

      act(() => {
        firstHeader?.click();
      });
      expect(firstHeader?.getAttribute('aria-expanded')).toBe('true');

      act(() => {
        root.render(
          <ResultContent
            agentTask={{ ...completedTask, agentTaskId: 'task-2' }}
            onRetry={() => {}}
            onContinue={() => {}}
          />,
        );
      });
      expect(container.querySelector('.activity-summary-header')?.getAttribute('aria-expanded')).toBe('false');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('keeps completed reasoning present and expandable', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ResultContent agentTask={completedTask} onRetry={() => {}} onContinue={() => {}} />);
      });
      const reasoningHeader = container.querySelector<HTMLElement>('.thinking-pill .execution-steps-header');
      const reasoningBody = container.querySelector<HTMLElement>('.thinking-pill .thinking-collapse');
      expect(reasoningHeader?.textContent).toContain('Reasoning');
      expect(reasoningBody?.classList.contains('expanded')).toBe(false);

      act(() => {
        reasoningHeader?.click();
      });
      expect(reasoningBody?.classList.contains('expanded')).toBe(true);
      expect(reasoningBody?.textContent).toContain('I will review the report.');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });
});

describe('ResultContent artifact integration', () => {
  it('keeps the lightweight file link after the user-facing result', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{
          ...completedTask,
          presentationSummary: { ...presentationSummary, artifactCount: 1 },
          structuredFiles: [reportFile],
        }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    const activityIndex = markup.indexOf('activity-summary');
    const legacyFileIndex = markup.indexOf('Created: report.md');
    const resultIndex = markup.indexOf('Result:');

    expect(activityIndex).toBeGreaterThanOrEqual(0);
    expect(markup).not.toContain('Work summary');
    expect(legacyFileIndex).toBeGreaterThan(resultIndex);
    expect(markup).not.toContain('agent-task-artifact-dock');
  });

  it('hides supplemental presentation for a task without actual artifacts or delegated work', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{ ...completedTask, status: 'processing', result: '', presentationSummary: undefined, executionTimeline: [] }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('Work summary');
    expect(markup).not.toContain('Artifacts');
  });

  it('does not render an empty terminal artifact dock', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{ ...completedTask, presentationSummary }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('Work summary');
    expect(markup).not.toContain('No artifacts were reported for this task.');
  });

  it('shows a failed outcome, its reason and Retry in the run status card', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{
          ...completedTask,
          status: 'failed',
          errorMessage: 'SECRET failure detail',
          presentationSummary: { ...presentationSummary, lifecycle: 'failed' },
        }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).toContain('run-status-card');
    expect(markup).toContain("Couldn&#x27;t complete");
    expect(markup).toContain('SECRET failure detail');
    expect(markup).toContain('Retry');
    expect(markup).toContain('Partial Result:');
    expect(markup).not.toContain('Partial result alert');
    expect(markup).toContain('activity-summary');
  });

  it('shows one verifying state with a provisional result and no recovery actions', () => {
    for (const status of ['completed', 'failed'] as const) {
      const markup = renderToStaticMarkup(
        <ResultContent
          agentTask={{
            ...completedTask,
            status,
            verificationStatus: 'pending',
            errorMessage: status === 'failed' ? 'provisional failure text' : undefined,
          }}
          onRetry={() => {}}
          onContinue={() => {}}
        />,
      );

      expect(markup).toContain('Verifying the outcome');
      expect(markup).toContain('run-status-card--live');
      expect(markup).toContain('Provisional');
      expect(markup).not.toContain('Retry');
      expect(markup).not.toContain('Partial Result:');
      expect(markup).not.toContain('Partial result alert');
      expect(markup).not.toContain('final result will appear in a moment');
      expect(markup).not.toContain('result-verifying');
      expect(markup).toContain('execution-activity-dock');
      expect(markup).not.toContain('activity-summary');
    }
  });

  it('shows a canceled run as neutral with Run again, never as a failure or a pending question', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{
          ...completedTask,
          status: 'failed',
          isCanceled: true,
          errorMessage: 'Task failed',
          executionTimeline: [
            ...completedTask.executionTimeline,
            {
              id: 'user_interaction_ask-1',
              type: 'step',
              timestamp: '2026-10-04T23:40:02+00:00',
              content: 'sed -n 2p notes.txt',
              detail_kind: 'user_interaction',
              metadata: {
                progress_step: 'Basil asked to run',
                user_interaction: {
                  interaction_id: 'ask-1',
                  kind: 'approval',
                  status: 'waiting',
                  prompt: 'sed -n 2p notes.txt',
                  asked_at: '2026-10-04T23:40:02+00:00',
                },
              },
            },
          ],
        }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).toContain('run-status-card--neutral');
    expect(markup).toContain('Canceled');
    expect(markup).toContain('Run again');
    expect(markup).toContain('Canceled - the run ended before this was answered');
    expect(markup).not.toContain('Waiting for your answer');
    expect(markup).not.toContain('Task failed');
    expect(markup).not.toContain("Couldn&#x27;t complete");
    expect(markup).not.toContain('run-status-card--danger');
  });

  it('does not show a status card for a clean completed run', () => {
    const markup = renderToStaticMarkup(
      <ResultContent agentTask={completedTask} onRetry={() => {}} onContinue={() => {}} />,
    );

    expect(markup).not.toContain('run-status-card');
    expect(markup).not.toContain('Retry');
  });

  it('suppresses stale failure residue for a legacy successful warning outcome', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{
          ...completedTask,
          outcome: 'completed_with_warnings',
          result: 'Completed with warnings: Created report.',
          errorMessage: 'Recovered retry detail',
        }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('Completed with warnings');
    expect(markup).not.toContain('run-status-card');
    expect(markup).not.toContain('Recovered retry detail');
    expect(markup).toContain('Created report.');
  });

  it('keeps structured artifacts out of the main result column', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{ ...completedTask, structuredFiles: [reportFile] }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('agent-task-artifact-dock');
  });

  it('renders a compact delegated-work chip after the user-facing result', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{
          ...completedTask,
          presentationSummary,
          delegatedProviderReportCards: [{
            delegatedAgentRunId: 'run-private-1',
            runStatus: 'supervision_due',
            runRevision: 4,
            captureState: 'available',
            evidenceCount: 25,
            latestSummary: 'Provider completed this turn.',
            verificationState: 'not_applicable',
          }],
        }}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    const resultIndex = markup.indexOf('Result:');
    const chipIndex = markup.indexOf('Delegated work');
    expect(chipIndex).toBeGreaterThan(resultIndex);
    expect(markup).toContain('delegated-provider-work-chip--working');
    expect(markup).not.toContain('supervision due');
    expect(markup).not.toContain('run-private-1');
  });
});

describe('ResultContent retry model selector', () => {
  const failedTask: DisplayableAgentTask = {
    ...completedTask,
    status: 'failed',
    errorMessage: 'Something went wrong',
    result: '',
  };

  it('defaults the retry model selector to the model originally used for the failed attempt', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ResultContent
          agentTask={{ ...failedTask, originalModelId: 'gpt-5-mini' }}
          onRetry={() => {}}
          onContinue={() => {}}
        />,
      );
    });
    await act(async () => { await Promise.resolve(); });

    expect(container.querySelector('.rich-text-model-picker-trigger')?.textContent).toContain('GPT-5 mini');

    act(() => { root.unmount(); });
    container.remove();
  });

  it('passes the currently selected retry model into onRetry', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onRetry = vi.fn();

    await act(async () => {
      root.render(
        <ResultContent
          agentTask={{ ...failedTask, originalModelId: 'gpt-5-mini' }}
          onRetry={onRetry}
          onContinue={() => {}}
        />,
      );
    });
    await act(async () => { await Promise.resolve(); });

    const retryButton = Array.from(container.querySelectorAll('button')).find(b => b.textContent?.includes('Retry'));
    act(() => { retryButton?.click(); });

    expect(onRetry).toHaveBeenCalledWith('gpt-5-mini');

    act(() => { root.unmount(); });
    container.remove();
  });
});

describe('ResultContent turn chain and run details', () => {
  const chainTask: DisplayableAgentTask = {
    ...completedTask,
    currentTurnTaskId: 'follow-up-1',
    result: 'Here is the comparison.\n\n• Active app at request: Mail\n\n• Tool calls: 3',
    agentTaskHistory: [{
      id: 'root-task',
      agentTaskText: 'Investigate the workflow',
      result: 'Investigation stopped.',
      errorMessage: 'The tool crashed.',
      status: 'failed',
      files: [],
      reference_paths: [],
      timestamp: '2026-09-24T12:00:00.000Z',
    }],
  };

  it('labels every turn and shows a failed glyph for a failed earlier turn', () => {
    const markup = renderToStaticMarkup(
      <ResultContent agentTask={chainTask} onRetry={() => {}} onContinue={() => {}} />,
    );

    expect(markup).toContain('Initial request');
    expect(markup).toContain('Follow-up 1');
    expect(markup.indexOf('Initial request')).toBeLessThan(markup.indexOf('Follow-up 1'));
    expect(markup).toContain('turn-status-glyph--failed');
    expect(markup).toContain('turn-status-glyph--success');
  });

  it('omits turn labels for a single-turn task', () => {
    const markup = renderToStaticMarkup(
      <ResultContent agentTask={completedTask} onRetry={() => {}} onContinue={() => {}} />,
    );

    expect(markup).not.toContain('turn-label');
  });

  it('focuses the clicked run and marks the focused label', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onFocusRun = vi.fn();

    try {
      act(() => {
        root.render(
          <ResultContent
            agentTask={chainTask}
            onRetry={() => {}}
            onContinue={() => {}}
            focusedRunId="root-task"
            onFocusRun={onFocusRun}
          />,
        );
      });
      const labels = Array.from(container.querySelectorAll<HTMLButtonElement>('button.turn-label--interactive'));

      expect(labels).toHaveLength(2);
      expect(labels[0].getAttribute('aria-pressed')).toBe('true');
      expect(labels[1].getAttribute('aria-pressed')).toBe('false');

      act(() => {
        labels[1].click();
      });

      expect(onFocusRun).toHaveBeenCalledWith('follow-up-1');
    } finally {
      act(() => { root.unmount(); });
      container.remove();
    }
  });

  describe('run map navigation', () => {
    function mockTop(element: Element | null, top: number) {
      if (!element) throw new Error('Expected a navigation element.');
      (element as HTMLElement).getBoundingClientRect = () => ({ top, bottom: top, left: 0, right: 0, width: 0, height: 0, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
    }

    function prepareScrollContainer(container: HTMLElement, scrollTop: number): HTMLElement {
      const main = container.querySelector<HTMLElement>('.main-content');
      if (!main) throw new Error('Expected the main content scroller.');
      Object.defineProperty(main, 'clientHeight', { configurable: true, value: 400 });
      Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 2000 });
      Object.defineProperty(main, 'scrollTop', { configurable: true, writable: true, value: scrollTop });
      mockTop(main, 0);
      return main;
    }

    function scrollTo(container: HTMLElement, tops: { root: number; followUp: number }, scrollTop = 500) {
      const main = prepareScrollContainer(container, scrollTop);
      mockTop(container.querySelector('[data-run-anchor="root-task"]'), tops.root);
      mockTop(container.querySelector('[data-run-anchor="follow-up-1"]'), tops.followUp);
      act(() => {
        main.dispatchEvent(new Event('scroll'));
      });
    }

    function renderChain(props: Partial<React.ComponentProps<typeof ResultContent>>) {
      const container = document.createElement('div');
      document.body.appendChild(container);
      const root = createRoot(container);
      const render = (next: Partial<React.ComponentProps<typeof ResultContent>>) => {
        act(() => {
          root.render(<ResultContent agentTask={chainTask} onRetry={() => {}} onContinue={() => {}} {...props} {...next} />);
        });
      };
      render({});
      return {
        container,
        render,
        cleanup: () => {
          act(() => { root.unmount(); });
          container.remove();
        },
      };
    }

    const scrollToSpy = vi.fn();

    beforeEach(() => {
      scrollToSpy.mockClear();
      Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, writable: true, value: scrollToSpy });
    });

    afterEach(() => {
      Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo');
    });

    it('expands a prior turn and scrolls to its result once per navigation request', () => {
      const onLocationChange = vi.fn();
      const view = renderChain({ onLocationChange, navigationRequest: null });

      try {
        expect(view.container.querySelector('[data-run-content="root-task"] [data-run-section="result"]')).toBeNull();
        const request = { nonce: 1, runId: 'root-task', target: { kind: 'section' as const, section: 'result' as const } };
        view.render({ navigationRequest: request });

        const resultSection = view.container.querySelector('[data-run-content="root-task"] [data-run-section="result"]');
        expect(resultSection).not.toBeNull();
        expect(scrollToSpy).toHaveBeenCalledTimes(1);
        expect(scrollToSpy).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'smooth' }));
        expect(resultSection?.hasAttribute('data-navigation-flash')).toBe(true);
        expect(onLocationChange).not.toHaveBeenCalled();

        view.render({ navigationRequest: { ...request } });
        expect(scrollToSpy).toHaveBeenCalledTimes(1);

        view.render({ navigationRequest: { nonce: 2, runId: 'follow-up-1', target: { kind: 'run' } } });
        expect(view.container.querySelector('[data-run-content="root-task"] [data-run-section="result"]')).toBeNull();
        expect(scrollToSpy).toHaveBeenCalledTimes(2);
      } finally {
        view.cleanup();
      }
    });

    it('reports the turn whose label crosses the location threshold', () => {
      const onLocationChange = vi.fn();
      const view = renderChain({ onLocationChange });

      try {
        scrollTo(view.container, { root: -50, followUp: 300 });
        expect(onLocationChange).toHaveBeenLastCalledWith('root-task');
        scrollTo(view.container, { root: -400, followUp: 100 });
        expect(onLocationChange).toHaveBeenLastCalledWith('follow-up-1');
        scrollTo(view.container, { root: -400, followUp: 100 });
        expect(onLocationChange).toHaveBeenCalledTimes(2);
        scrollTo(view.container, { root: -50, followUp: 300 });
        expect(onLocationChange).toHaveBeenLastCalledWith('root-task');
        scrollTo(view.container, { root: -50, followUp: 300 }, 1600);
        expect(onLocationChange).toHaveBeenLastCalledWith('follow-up-1');
        expect(onLocationChange).toHaveBeenCalledTimes(4);
        scrollTo(view.container, { root: 0, followUp: 100 }, 0);
        expect(onLocationChange).toHaveBeenLastCalledWith('root-task');
        expect(onLocationChange).toHaveBeenCalledTimes(5);
      } finally {
        view.cleanup();
      }
    });

    it('ignores turns passed over by a map scroll until arrival or user input', () => {
      const onLocationChange = vi.fn();
      const view = renderChain({ onLocationChange });

      try {
        view.render({ navigationRequest: { nonce: 1, runId: 'root-task', target: { kind: 'run' } } });
        expect(scrollToSpy).toHaveBeenCalledTimes(1);

        scrollTo(view.container, { root: -500, followUp: 100 });
        expect(onLocationChange).not.toHaveBeenCalled();
        scrollTo(view.container, { root: 0, followUp: 600 });
        expect(onLocationChange).not.toHaveBeenCalled();
        scrollTo(view.container, { root: -500, followUp: 100 });
        expect(onLocationChange).toHaveBeenLastCalledWith('follow-up-1');

        view.render({ navigationRequest: { nonce: 2, runId: 'root-task', target: { kind: 'run' } } });
        expect(scrollToSpy).toHaveBeenCalledTimes(2);
        scrollTo(view.container, { root: -500, followUp: 100 });
        expect(onLocationChange).toHaveBeenCalledTimes(1);

        const main = view.container.querySelector<HTMLElement>('.main-content');
        act(() => {
          main?.dispatchEvent(new Event('wheel', { bubbles: true }));
        });
        scrollTo(view.container, { root: -500, followUp: 100 });
        expect(onLocationChange).toHaveBeenCalledTimes(2);
        expect(onLocationChange).toHaveBeenLastCalledWith('follow-up-1');
      } finally {
        view.cleanup();
      }
    });
  });

  it('moves the finalizer metadata into a collapsed run details section', () => {
    const markup = renderToStaticMarkup(
      <ResultContent agentTask={chainTask} onRetry={() => {}} onContinue={() => {}} />,
    );

    expect(markup).toContain('Here is the comparison.');
    expect(markup).toContain('run-details-toggle');
    expect(markup).toContain('3 tool calls · Mail');
    expect(markup).not.toContain('run-details-list');
    expect(markup).not.toContain('Active app at request');
  });
});
