// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
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
      <ResultContent agentTask={completedTask} embedded={false} onRetry={() => {}} onContinue={() => {}} />,
    );

    const thinkingIndex = markup.indexOf('thinking-segments');
    const activityIndex = markup.indexOf('activity-summary');
    const resultIndex = markup.indexOf('Result:');

    expect(thinkingIndex).toBeGreaterThanOrEqual(0);
    expect(activityIndex).toBeGreaterThan(thinkingIndex);
    expect(activityIndex).toBeLessThan(resultIndex);
    expect(markup).not.toContain('execution-activity-dock');
  });

  it('uses the completed inline activity summary when embedded', () => {
    const markup = renderToStaticMarkup(
      <ResultContent agentTask={completedTask} embedded onRetry={() => {}} onContinue={() => {}} />,
    );

    expect(markup).toContain('thinking-segments');
    expect(markup).toContain('activity-summary');
    expect(markup).not.toContain('execution-activity-dock');
  });

  it('keeps embedded activity in the dock while processing', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{ ...completedTask, status: 'processing', result: '' }}
        embedded
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
        embedded={false}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('margin-bottom:var(--padding-m)');
  });

  it('collapses the embedded activity summary when focus moves to another task', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ResultContent agentTask={completedTask} embedded onRetry={() => {}} onContinue={() => {}} />);
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
            embedded
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

  it('collapses inline completed activity when focus moves to another task', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ResultContent agentTask={completedTask} embedded={false} onRetry={() => {}} onContinue={() => {}} />);
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
            embedded={false}
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

  it('keeps completed embedded reasoning present and expandable', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ResultContent agentTask={completedTask} embedded onRetry={() => {}} onContinue={() => {}} />);
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
        embedded={false}
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
        embedded={false}
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
        embedded={false}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('Work summary');
    expect(markup).not.toContain('No artifacts were reported for this task.');
  });

  it('keeps the detailed failure text in the existing partial-result alert', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{
          ...completedTask,
          status: 'failed',
          errorMessage: 'SECRET failure detail',
          presentationSummary: { ...presentationSummary, lifecycle: 'failed' },
        }}
        embedded={false}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).toContain('Partial result alert');
    expect(markup).toContain('SECRET failure detail');
    expect(markup.indexOf('Partial result alert')).toBeLessThan(markup.indexOf('SECRET failure detail'));
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
        embedded={false}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    );

    expect(markup).not.toContain('Completed with warnings');
    expect(markup).not.toContain('Partial result alert');
    expect(markup).not.toContain('Recovered retry detail');
    expect(markup).toContain('Created report.');
  });

  it('keeps structured artifacts out of the main result column', () => {
    const markup = renderToStaticMarkup(
      <ResultContent
        agentTask={{ ...completedTask, structuredFiles: [reportFile] }}
        embedded={false}
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
        embedded={false}
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
          embedded={false}
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
          embedded={false}
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
