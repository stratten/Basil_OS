// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import { AgentRunRail } from './AgentRunRail';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const overview: AgentRunOverviewPresentation = {
  terminalState: 'completed',
  activityCount: 58,
  artifactCount: 1,
  stages: [
    {
      id: 'overview:analysis',
      kind: 'phase',
      label: 'Analyzing request',
      state: 'completed',
      startedAt: '2026-08-10T12:00:00Z',
      artifactCount: 1,
    },
    {
      id: 'overview:execution',
      kind: 'phase',
      label: 'Completing task',
      state: 'completed',
      startedAt: '2026-08-10T12:00:01Z',
      artifactCount: 0,
    },
    {
      id: 'overview:outcome',
      kind: 'outcome',
      label: 'Delivered report',
      state: 'completed',
      startedAt: '2026-08-10T12:00:02Z',
      artifactCount: 0,
    },
  ],
};

describe('AgentRunRail', () => {
  it('renders semantic stage and document glyphs without visible counts', () => {
    const onExpand = vi.fn();
    const markup = renderToStaticMarkup(<AgentRunRail overview={overview} onExpand={onExpand} />);

    expect(onExpand).not.toHaveBeenCalled();
    expect(markup).toContain('aria-label="Expand completed run overview, 2 phases, 1 document"');
    expect((markup.match(/class="agent-run-rail-flow-stage /g) || [])).toHaveLength(3);
    expect((markup.match(/<svg/g) || []).length).toBeGreaterThanOrEqual(4);
    expect(markup).toContain('agent-run-rail-artifact-mark');
    expect(markup).not.toContain('58');
    expect(markup).not.toContain('agent-run-rail-count');
    expect(markup).not.toContain('agent-run-rail-label');
    expect(markup).toContain('data-tooltip="Analyzing request: completed, 1 document"');
    expect(markup).toContain('data-tooltip="Completing task: completed"');
    expect(markup).toContain('data-tooltip="Delivered report: completed"');
    expect(markup).toContain('--run-rail-enter-delay:0ms');
    expect(markup).toContain('--run-rail-connector-delay:180ms');
  });

  it('shows an in-progress placeholder only while a run is processing without stages', () => {
    const empty: AgentRunOverviewPresentation = { terminalState: 'active', activityCount: 0, artifactCount: 0, stages: [] };
    const processing = renderToStaticMarkup(
      <AgentRunRail overview={empty} runId="follow-up-1" isProcessing onExpand={() => {}} />,
    );
    const idle = renderToStaticMarkup(<AgentRunRail overview={empty} onExpand={() => {}} />);

    expect((processing.match(/class="agent-run-rail-flow-stage /g) || [])).toHaveLength(1);
    expect(processing).toContain('is-active');
    expect(processing).toContain('data-tooltip="Starting: in progress"');
    expect(processing).toContain('aria-label="Expand active run overview, 0 phases, 0 documents"');
    expect((idle.match(/class="agent-run-rail-flow-stage /g) || [])).toHaveLength(0);
  });

  it('shows exchanges with the user as distinct stages whose tooltip pairs question and answer', () => {
    const onExpand = vi.fn();
    const withExchange: AgentRunOverviewPresentation = {
      ...overview,
      stages: [
        overview.stages[1],
        {
          id: 'overview:interaction:user_interaction_cp',
          kind: 'interaction',
          label: 'Basil asked',
          state: 'completed',
          startedAt: '2026-08-10T12:00:01Z',
          artifactCount: 0,
          interaction: {
            id: 'cp',
            entryId: 'user_interaction_cp',
            kind: 'clarification',
            status: 'answered',
            prompt: 'Which hotel did you mean?',
            askedAt: '2026-08-10T12:00:01Z',
            response: 'La Fantaisie',
            responseHidden: false,
            options: [],
          },
        },
        overview.stages[2],
      ],
    };
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunRail overview={withExchange} onExpand={onExpand} />);
      });
      const exchange = container.querySelector('.agent-run-rail-flow-stage--interaction');

      expect(exchange?.classList.contains('is-completed')).toBe(true);
      expect(exchange?.getAttribute('data-tooltip'))
        .toBe('Basil asked: Which hotel did you mean?\nYou answered: La Fantaisie');
      expect(container.querySelector('button')?.getAttribute('aria-label'))
        .toBe('Expand completed run overview, 1 phases, 1 exchange with you, 1 document');

      act(() => {
        (exchange as HTMLElement).click();
      });
      expect(onExpand).toHaveBeenCalledTimes(1);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('remounts stage nodes when the focused run changes', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AgentRunRail overview={overview} runId="root-task" onExpand={() => {}} />);
      });
      const firstStage = container.querySelector('.agent-run-rail-flow-stage');

      act(() => {
        root.render(<AgentRunRail overview={overview} runId="follow-up-1" onExpand={() => {}} />);
      });

      expect(container.querySelector('.agent-run-rail-flow-stage')).not.toBe(firstStage);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  const railRuns: AgentTaskRunFocusSummary[] = [
    {
      id: 'root',
      kind: 'root',
      ordinal: 1,
      label: 'Initial request',
      requestText: 'Investigate',
      resultText: 'Done.',
      timestamp: '2026-08-10T12:00:00Z',
      taskStatus: 'completed',
      isProcessing: false,
      documentCount: 0,
      structuredFiles: [],
      executionTimeline: [],
    },
    {
      id: 'follow-up',
      kind: 'follow_up',
      ordinal: 2,
      label: 'Follow-up 1',
      requestText: 'Retry',
      resultText: 'Failed.',
      timestamp: '2026-08-10T12:01:00Z',
      taskStatus: 'failed',
      isProcessing: false,
      documentCount: 0,
      structuredFiles: [],
      executionTimeline: [],
    },
  ];

  const thirdRun: AgentTaskRunFocusSummary = {
    ...railRuns[1],
    id: 'follow-up-2',
    ordinal: 3,
    label: 'Follow-up 2',
    requestText: 'Summarize',
    taskStatus: 'completed',
  };

  it('expands the viewed turn in place of its dot, between the turns before and after it', () => {
    const onNavigateRun = vi.fn();
    const onExpand = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <AgentRunRail
            overview={overview}
            onExpand={onExpand}
            runId="follow-up"
            runs={[...railRuns, thirdRun]}
            locationRunId="follow-up"
            onNavigateRun={onNavigateRun}
          />,
        );
      });
      const nav = container.querySelector('nav.agent-run-rail-turns');
      const children = Array.from(nav?.children ?? []);
      expect(children.map(child => child.className.split(' ')[0])).toEqual([
        'agent-run-rail-turn',
        'agent-run-rail-turn-expanded',
        'agent-run-rail-turn',
      ]);
      const dots = Array.from(container.querySelectorAll<HTMLButtonElement>('nav.agent-run-rail-turns .agent-run-rail-turn'));
      expect(dots.map(dot => dot.textContent)).toEqual(['1', '3']);
      expect(dots[0].getAttribute('aria-label')).toBe('Go to Initial request, Completed');
      expect(dots[0].getAttribute('data-tooltip')).toBe('Initial request: Completed');
      expect(dots[0].hasAttribute('aria-current')).toBe(false);
      const toggle = children[1].querySelector('.agent-run-rail-toggle');
      expect(toggle?.getAttribute('aria-current')).toBe('location');
      expect(children[1].querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(3);
      const number = children[1].firstElementChild;
      expect(number?.className).toBe('agent-run-rail-turn-number');
      expect(number?.textContent).toBe('2');
      expect(number?.getAttribute('data-tooltip')).toBe('Follow-up 1: Needs attention');

      act(() => {
        dots[0].click();
      });
      expect(onNavigateRun).toHaveBeenCalledWith('root');
      expect(onExpand).not.toHaveBeenCalled();

      act(() => {
        nav?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      });
      expect(onExpand).toHaveBeenCalledTimes(1);

      act(() => {
        (number as HTMLElement).click();
      });
      expect(onExpand).toHaveBeenCalledTimes(2);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('keeps the location dot when the focused turn differs from the scroll location', () => {
    const markup = renderToStaticMarkup(
      <AgentRunRail overview={overview} onExpand={() => {}} runId="root" runs={railRuns} locationRunId="follow-up" onNavigateRun={() => {}} />,
    );
    expect(markup.indexOf('agent-run-rail-turn-expanded')).toBeLessThan(markup.indexOf('aria-label="Go to Follow-up 1, Needs attention"'));
    expect(markup).toContain('class="agent-run-rail-turn is-failed is-location" aria-current="location"');
    expect(markup).not.toContain('class="agent-run-rail-toggle" aria-label="Expand completed run overview, 2 phases, 1 document" aria-current');
  });

  it('places the stage flow after the dots when the focused turn is not in the list', () => {
    const markup = renderToStaticMarkup(
      <AgentRunRail overview={overview} onExpand={() => {}} runId="missing" runs={railRuns} locationRunId="missing" onNavigateRun={() => {}} />,
    );
    expect((markup.match(/class="agent-run-rail-turn /g) || [])).toHaveLength(2);
    expect(markup.lastIndexOf('agent-run-rail-turn ')).toBeLessThan(markup.indexOf('agent-run-rail-turn-expanded'));
  });

  it('omits turn dots for a single run or without a navigation handler', () => {
    const single = renderToStaticMarkup(
      <AgentRunRail overview={overview} onExpand={() => {}} runs={[railRuns[0]]} locationRunId="root" onNavigateRun={() => {}} />,
    );
    const withoutHandler = renderToStaticMarkup(
      <AgentRunRail overview={overview} onExpand={() => {}} runs={railRuns} locationRunId="root" />,
    );
    expect(single).not.toContain('agent-run-rail-turns');
    expect(withoutHandler).not.toContain('agent-run-rail-turns');
  });
});
