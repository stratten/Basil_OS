// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { AgentRunHistoryTray } from './AgentRunHistoryTray';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const runs: AgentTaskRunFocusSummary[] = [
  {
    id: 'root',
    kind: 'root',
    ordinal: 1,
    label: 'Initial request',
    requestText: 'Investigate the integration workflow',
    resultText: 'The integration workflow is ready.',
    timestamp: '2026-08-10T12:00:00Z',
    taskStatus: 'completed',
    isProcessing: false,
    documentCount: 1,
    structuredFiles: [],
    executionTimeline: [],
  },
  {
    id: 'follow-up',
    kind: 'follow_up',
    ordinal: 2,
    label: 'Follow-up 1',
    requestText: 'Compare the alternatives and summarize them',
    resultText: 'The alternatives are summarized.',
    timestamp: '2026-08-10T12:01:00Z',
    taskStatus: 'completed',
    isProcessing: false,
    documentCount: 0,
    structuredFiles: [],
    executionTimeline: [],
  },
];

function renderTray(onSelect = vi.fn()) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<AgentRunHistoryTray runs={runs} focusedRunId="follow-up" onSelect={onSelect} />);
  });
  return { container, root, onSelect };
}

describe('AgentRunHistoryTray', () => {
  it('does not render for a single-run task', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunHistoryTray runs={[runs[0]]} focusedRunId="root" onSelect={() => {}} />);
      });
      expect(container.innerHTML).toBe('');
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('is collapsed by default and exposes every run when expanded', () => {
    const { container, root } = renderTray();

    try {
      const toggle = container.querySelector<HTMLButtonElement>('.agent-run-history-toggle');
      expect(toggle?.getAttribute('aria-expanded')).toBe('false');
      expect(container.querySelector('.agent-run-history-list')).toBeNull();

      act(() => {
        toggle?.click();
      });

      expect(toggle?.getAttribute('aria-expanded')).toBe('true');
      expect(container.querySelectorAll('.agent-run-history-row')).toHaveLength(2);
      expect(container.textContent).toContain('Investigate the integration workflow');
      expect(container.textContent).toContain('1 doc');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('keeps the tray open and selects the requested run', () => {
    const onSelect = vi.fn();
    const { container, root } = renderTray(onSelect);

    try {
      const toggle = container.querySelector<HTMLButtonElement>('.agent-run-history-toggle');
      act(() => {
        toggle?.click();
      });
      const rootRun = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'))
        .find(button => button.textContent?.includes('Initial request'));
      act(() => {
        rootRun?.click();
      });

      expect(onSelect).toHaveBeenCalledWith('root');
      expect(container.querySelector('.agent-run-history-toggle')?.getAttribute('aria-expanded')).toBe('true');
      expect(container.querySelector('.agent-run-history-item.is-focused')?.textContent).toContain('Follow-up 1');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('presents a verified path-continuity follow-up as completed with a note, not a red failure', () => {
    const verifiedContinuityRuns: AgentTaskRunFocusSummary[] = [
      runs[0],
      {
        ...runs[1],
        taskStatus: 'completed',
        outcome: 'partial',
        resultSeverity: 'warning',
        documentCount: 1,
        hasVerifiedArtifactOutput: true,
      },
    ];
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunHistoryTray runs={verifiedContinuityRuns} focusedRunId="follow-up" onSelect={() => {}} />);
      });
      act(() => {
        container.querySelector<HTMLButtonElement>('.agent-run-history-toggle')?.click();
      });

      const followUpRow = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'))
        .find(button => button.textContent?.includes('Follow-up 1'));
      const statusDot = followUpRow?.querySelector('.agent-run-history-status');

      expect(statusDot?.className).not.toContain('is-failed');
      expect(statusDot?.getAttribute('aria-label')).toBe('Completed with note');
      expect(followUpRow?.getAttribute('aria-label')).toContain('Completed with note');
      expect(followUpRow?.textContent).not.toContain('Needs attention');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('presents an actual execution failure as needing attention with a red marker', () => {
    const failedRuns: AgentTaskRunFocusSummary[] = [
      runs[0],
      {
        ...runs[1],
        taskStatus: 'failed',
        outcome: 'failed',
        resultSeverity: 'error',
      },
    ];
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunHistoryTray runs={failedRuns} focusedRunId="follow-up" onSelect={() => {}} />);
      });
      act(() => {
        container.querySelector<HTMLButtonElement>('.agent-run-history-toggle')?.click();
      });

      const followUpRow = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'))
        .find(button => button.textContent?.includes('Follow-up 1'));
      const statusDot = followUpRow?.querySelector('.agent-run-history-status');

      expect(statusDot?.className).toContain('is-failed');
      expect(statusDot?.getAttribute('aria-label')).toBe('Needs attention');
      expect(followUpRow?.getAttribute('aria-label')).toContain('Needs attention');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('does not treat an unverified output as a verified continuity note', () => {
    const unverifiedRuns: AgentTaskRunFocusSummary[] = [
      runs[0],
      {
        ...runs[1],
        taskStatus: 'failed',
        outcome: 'partial',
        resultSeverity: 'warning',
        documentCount: 1,
        hasVerifiedArtifactOutput: false,
      },
    ];
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunHistoryTray runs={unverifiedRuns} focusedRunId="follow-up" onSelect={() => {}} />);
      });
      act(() => {
        container.querySelector<HTMLButtonElement>('.agent-run-history-toggle')?.click();
      });

      const followUpRow = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'))
        .find(button => button.textContent?.includes('Follow-up 1'));
      expect(followUpRow?.querySelector('.agent-run-history-status')?.className).toContain('is-failed');
      expect(followUpRow?.getAttribute('aria-label')).toContain('Needs attention');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('presents a processing run as in progress regardless of status', () => {
    const processingRuns: AgentTaskRunFocusSummary[] = [
      runs[0],
      { ...runs[1], taskStatus: 'routing', isProcessing: true },
    ];
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunHistoryTray runs={processingRuns} focusedRunId="follow-up" onSelect={() => {}} />);
      });
      act(() => {
        container.querySelector<HTMLButtonElement>('.agent-run-history-toggle')?.click();
      });

      const followUpRow = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'))
        .find(button => button.textContent?.includes('Follow-up 1'));
      const statusDot = followUpRow?.querySelector('.agent-run-history-status');

      expect(statusDot?.className).toContain('is-processing');
      expect(statusDot?.getAttribute('aria-label')).toBe('In progress');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('presents an awaiting-input run as waiting for input', () => {
    const waitingRuns: AgentTaskRunFocusSummary[] = [
      runs[0],
      { ...runs[1], taskStatus: 'awaitingInput' },
    ];
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunHistoryTray runs={waitingRuns} focusedRunId="follow-up" onSelect={() => {}} />);
      });
      act(() => {
        container.querySelector<HTMLButtonElement>('.agent-run-history-toggle')?.click();
      });

      const followUpRow = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'))
        .find(button => button.textContent?.includes('Follow-up 1'));
      const statusDot = followUpRow?.querySelector('.agent-run-history-status');

      expect(statusDot?.className).toContain('is-awaitingInput');
      expect(statusDot?.getAttribute('aria-label')).toBe('Waiting for input');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });
});
