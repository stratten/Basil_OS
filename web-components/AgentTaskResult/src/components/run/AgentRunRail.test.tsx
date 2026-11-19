// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import { AgentRunRail } from './AgentRunRail';
import { makeChecklistItem, makeChecklistSnapshot } from '../checklist/checklistTestData';
import { resetChecklistStoreForTests } from '../../store/checklistStore';

const getChecklist = vi.hoisted(() => vi.fn());
vi.mock('../../services/checklistApi', () => ({ getChecklist: (...args: unknown[]) => getChecklist(...args) }));
vi.mock('../../services/api', () => ({ isApiReady: () => true }));
vi.mock('../../services/websocket', () => ({ wsManager: { subscribe: () => () => {}, onConnect: () => () => {} } }));

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

  it('caps the entrance stagger so the last chip of a long run arrives with the first few', () => {
    const many: AgentRunOverviewPresentation = {
      ...overview,
      // Each step carries a document, which keeps it from folding into a count, so all 53 stay as chips.
      stages: Array.from({ length: 53 }, (_, index) => ({
        id: `overview:phase-${index}`,
        kind: 'phase' as const,
        label: `Step ${index + 1}`,
        state: 'completed' as const,
        startedAt: '2026-08-10T12:00:00Z',
        artifactCount: 1,
      })),
    };
    const markup = renderToStaticMarkup(<AgentRunRail overview={many} onExpand={() => {}} />);
    const enterDelays = Array.from(markup.matchAll(/--run-rail-enter-delay:(\d+)ms/g), match => Number(match[1]));
    const connectorDelays = Array.from(markup.matchAll(/--run-rail-connector-delay:(\d+)ms/g), match => Number(match[1]));

    expect(enterDelays).toHaveLength(53);
    expect(enterDelays[0]).toBe(0);
    expect(enterDelays[11]).toBe(550);
    expect(Math.max(...enterDelays)).toBe(600);
    expect(Math.max(...connectorDelays)).toBe(730);
  });

  it('keeps the active chip in view when a long run grows, and leaves a reader who scrolled up alone', () => {
    const makeOverview = (count: number): AgentRunOverviewPresentation => ({
      ...overview,
      terminalState: 'active',
      stages: Array.from({ length: count }, (_, index) => ({
        id: `overview:phase-${index}`,
        kind: 'phase' as const,
        label: `Step ${index + 1}`,
        state: index === count - 1 ? 'active' as const : 'completed' as const,
        startedAt: '2026-08-10T12:00:00Z',
        artifactCount: 0,
      })),
    });
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    // Every chip is 28px tall in a 300px scroller, and its offset is set per step below.
    const offsetTop = vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockReturnValue(600);
    const offsetHeight = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(28);

    try {
      act(() => { root.render(<AgentRunRail overview={makeOverview(5)} onExpand={() => {}} />); });
      const flow = container.querySelector<HTMLElement>('.agent-run-rail-flow')!;
      Object.defineProperty(flow, 'scrollHeight', { configurable: true, value: 1000 });
      Object.defineProperty(flow, 'clientHeight', { configurable: true, value: 300 });
      Object.defineProperty(flow, 'scrollTop', { configurable: true, writable: true, value: 700 });

      // The reader is at the end (700 of 700), and the new active chip is above the window, so the rail scrolls up to its top edge minus the 6px padding.
      act(() => { root.render(<AgentRunRail overview={makeOverview(6)} onExpand={() => {}} />); });
      expect(flow.scrollTop).toBe(600 - 6);

      // A chip below the window is revealed by its bottom edge plus the padding, minus the 300px window.
      offsetTop.mockReturnValue(1200);
      act(() => { root.render(<AgentRunRail overview={makeOverview(7)} onExpand={() => {}} />); });
      expect(flow.scrollTop).toBe(1200 + 28 + 6 - 300);

      // The reader scrolls to the top: the next new chip does not pull the rail back down.
      (flow as unknown as { scrollTop: number }).scrollTop = 0;
      act(() => { flow.dispatchEvent(new Event('scroll', { bubbles: true })); });
      act(() => { root.render(<AgentRunRail overview={makeOverview(8)} onExpand={() => {}} />); });
      expect(flow.scrollTop).toBe(0);
    } finally {
      offsetTop.mockRestore();
      offsetHeight.mockRestore();
      act(() => { root.unmount(); });
      container.remove();
    }
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

  it("marks a waiting exchange as the user's turn", () => {
    const markup = renderToStaticMarkup(
      <AgentRunRail
        overview={{
          terminalState: 'active',
          activityCount: 1,
          artifactCount: 0,
          stages: [{
            id: 'overview:interaction:user_interaction_cp',
            kind: 'interaction',
            label: 'Basil asked',
            state: 'waiting',
            startedAt: '2026-10-05T10:00:00Z',
            artifactCount: 0,
            interaction: {
              id: 'cp',
              entryId: 'user_interaction_cp',
              kind: 'clarification',
              status: 'waiting',
              prompt: 'Which hotel?',
              askedAt: '2026-10-05T10:00:00Z',
              responseHidden: false,
              options: [],
            },
          }],
        }}
        onExpand={() => undefined}
      />,
    );

    expect(markup).toContain('agent-run-rail-flow-stage--interaction is-waiting');
    expect(markup).toContain('data-tooltip="Your turn: Basil asked: Which hotel?');
    expect(markup).toContain('M9.2 9.2');
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
      displayNumber: '1',
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
      displayNumber: '2',
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
    displayNumber: '3',
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

  it('draws the expanded turn once and logs no key warning when two entries share a run id', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <AgentRunRail
            overview={overview}
            onExpand={vi.fn()}
            runId="follow-up"
            runs={[...railRuns, { ...thirdRun, id: 'follow-up' }]}
            locationRunId="follow-up"
            onNavigateRun={vi.fn()}
          />,
        );
      });

      expect(container.querySelectorAll('.agent-run-rail-turn-expanded')).toHaveLength(1);
      expect(container.querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(3);
      expect(error.mock.calls.filter(call => String(call[0]).includes('same key'))).toEqual([]);
    } finally {
      act(() => {
        root.unmount();
      });
      error.mockRestore();
    }
  });

  it('prints an agent revision as parent.k in a wider badge', () => {
    const revision: AgentTaskRunFocusSummary = {
      ...railRuns[1],
      id: 'revision',
      ordinal: 2,
      displayNumber: '1.1',
      label: 'Agent revision 1.1',
      taskStatus: 'completed',
    };
    const container = document.createElement('div');
    const root = createRoot(container);
    try {
      act(() => {
        root.render(
          <AgentRunRail overview={overview} onExpand={() => {}} runId="root" runs={[railRuns[0], revision]} locationRunId="root" onNavigateRun={() => {}} />,
        );
      });
      const dot = container.querySelector<HTMLButtonElement>('nav.agent-run-rail-turns .agent-run-rail-turn');
      expect(dot?.textContent).toBe('1.1');
      expect(dot?.classList.contains('is-revision')).toBe(true);
      expect(dot?.getAttribute('aria-label')).toContain('Agent revision 1.1');
      expect(container.querySelector('.agent-run-rail-turn-number')?.classList.contains('is-revision')).toBe(false);
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('shows a clock instead of a number for a scheduled check, in its dot and when it is the expanded turn', () => {
    const check: AgentTaskRunFocusSummary = {
      ...railRuns[1],
      id: 'check',
      ordinal: 2,
      displayNumber: '',
      label: 'Scheduled check 1 of the initial request',
      taskStatus: 'completed',
    };
    const container = document.createElement('div');
    const root = createRoot(container);
    try {
      act(() => {
        root.render(
          <AgentRunRail overview={overview} onExpand={() => {}} runId="root" runs={[railRuns[0], check]} locationRunId="root" onNavigateRun={() => {}} />,
        );
      });
      const dot = container.querySelector<HTMLButtonElement>('nav.agent-run-rail-turns .agent-run-rail-turn');
      expect(dot?.textContent).toBe('');
      expect(dot?.querySelector('svg.scheduled-check-glyph')).not.toBeNull();
      expect(dot?.classList.contains('is-revision')).toBe(false);
      expect(dot?.getAttribute('aria-label')).toContain('Scheduled check 1 of the initial request');
      expect(dot?.getAttribute('aria-label')).not.toMatch(/revision/i);

      act(() => {
        root.render(
          <AgentRunRail overview={overview} onExpand={() => {}} runId="check" runs={[railRuns[0], check]} locationRunId="check" onNavigateRun={() => {}} />,
        );
      });
      const expanded = container.querySelector('.agent-run-rail-turn-number');
      expect(expanded?.querySelector('svg.scheduled-check-glyph')).not.toBeNull();
      expect(expanded?.getAttribute('data-tooltip')).toContain('Scheduled check 1 of the initial request');
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

describe('AgentRunRail checklist pill', () => {
  async function mount(props: Partial<React.ComponentProps<typeof AgentRunRail>>) {
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(<AgentRunRail overview={overview} onExpand={() => {}} {...props} />);
    });
    return { container, unmount: () => act(() => root.unmount()) };
  }

  it('sits above the turn dots as a fixed child of the rail, only once the chain has items', async () => {
    resetChecklistStoreForTests();
    getChecklist.mockResolvedValue(makeChecklistSnapshot([makeChecklistItem({ status: 'done' }), makeChecklistItem({ id: 'b' })]));
    const turn = (id: string, ordinal: number): AgentTaskRunFocusSummary => ({
      id, kind: ordinal === 1 ? 'root' : 'follow_up', ordinal, displayNumber: String(ordinal), label: `Turn ${ordinal}`, requestText: 'Ask', resultText: 'Done.',
      timestamp: '2026-08-10T12:00:00Z', taskStatus: 'completed', isProcessing: false, documentCount: 0, structuredFiles: [], executionTimeline: [],
    });
    const { container, unmount } = await mount({
      runId: 'turn-2', runs: [turn('turn-1', 1), turn('turn-2', 2), turn('turn-3', 3)], locationRunId: 'turn-2', onNavigateRun: () => {}, checklistRootId: 'root-1',
    });

    const rail = container.querySelector('aside.agent-run-rail')!;
    expect(Array.from(rail.children).map(child => child.className.split(' ')[0])).toEqual(['agent-run-rail-checklist', 'agent-run-rail-turns']);
    expect(rail.querySelector('.agent-run-rail-checklist-pill')!.textContent).toBe('1/2');
    unmount();
  });

  it('also appears above the stage flow when the rail has no turn dots', async () => {
    resetChecklistStoreForTests();
    getChecklist.mockResolvedValue(makeChecklistSnapshot([makeChecklistItem()]));
    const { container, unmount } = await mount({ checklistRootId: 'root-1' });

    const rail = container.querySelector('aside.agent-run-rail')!;
    expect(rail.firstElementChild!.className).toBe('agent-run-rail-checklist');
    expect(container.querySelector('.agent-run-rail-toggle')).not.toBeNull();
    unmount();
  });

  it('renders no checklist when the chain has no items or no checklist root is given', async () => {
    resetChecklistStoreForTests();
    getChecklist.mockResolvedValue(makeChecklistSnapshot([]));
    const empty = await mount({ checklistRootId: 'root-1' });
    expect(empty.container.querySelector('.agent-run-rail-checklist')).toBeNull();
    empty.unmount();

    getChecklist.mockClear();
    const none = await mount({});
    expect(none.container.querySelector('.agent-run-rail-checklist')).toBeNull();
    expect(getChecklist).not.toHaveBeenCalled();
    none.unmount();
  });
});

describe('AgentRunRail fold', () => {
  type Stage = AgentRunOverviewPresentation['stages'][number];
  const phaseStage = (index: number, state: Stage['state'] = 'completed'): Stage => ({
    id: `overview:phase-${index}`, kind: 'phase', label: `Step ${index + 1}`, state, startedAt: '2026-08-10T12:00:00Z', artifactCount: 0,
  });
  const overviewOf = (stages: Stage[]): AgentRunOverviewPresentation => ({ terminalState: 'active', activityCount: stages.length, artifactCount: 0, stages });
  const chipTooltips = (container: Element) => Array.from(container.querySelectorAll('.agent-run-rail-flow-stage'), chip => chip.getAttribute('data-tooltip'));
  const foldCount = (container: Element) => container.querySelector('.agent-run-rail-fold-count');

  async function mountRail(initial: AgentRunOverviewPresentation, runId?: string) {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => { root.render(<AgentRunRail overview={initial} runId={runId} onExpand={() => {}} />); });
    return {
      container,
      update: (next: AgentRunOverviewPresentation, nextRunId?: string) => act(() => { root.render(<AgentRunRail overview={next} runId={nextRunId ?? runId} onExpand={() => {}} />); }),
      unmount: () => { act(() => { root.unmount(); }); container.remove(); },
    };
  }

  it('folds a run that is already quiet into one chip with its step count and an explanatory tooltip', () => {
    const markup = renderToStaticMarkup(<AgentRunRail overview={overviewOf(Array.from({ length: 12 }, (_, index) => phaseStage(index)))} onExpand={() => {}} />);

    expect((markup.match(/class="agent-run-rail-flow-stage /g) || [])).toHaveLength(1);
    expect(markup).toContain('agent-run-rail-flow-stage--fold');
    expect(markup).toContain('>12</span>');
    expect(markup).toContain('data-tooltip="12 steps, all completed: 12 processing steps and 0 exchanges with you. Select the rail to see every step."');
    expect(markup).toContain('aria-label="Expand active run overview, 12 phases, 0 documents"');
  });

  it('shows a step that has just finished as its own chip, then folds it into the count and ticks the number', () => {
    vi.useFakeTimers();
    return (async () => {
      const rail = await mountRail(overviewOf([...Array.from({ length: 4 }, (_, index) => phaseStage(index)), phaseStage(4, 'active')]));
      try {
        expect(foldCount(rail.container)?.textContent).toBe('4');
        expect(foldCount(rail.container)?.classList.contains('is-ticking')).toBe(false);
        expect(rail.container.querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(2);

        // Step 5 finishes and step 6 starts. Step 5 gets its moment as a chip while the count stays at 4.
        rail.update(overviewOf([...Array.from({ length: 5 }, (_, index) => phaseStage(index)), phaseStage(5, 'active')]));
        expect(rail.container.querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(3);
        expect(foldCount(rail.container)?.textContent).toBe('4');

        act(() => { vi.advanceTimersByTime(1199); });
        expect(rail.container.querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(3);

        act(() => { vi.advanceTimersByTime(1); });
        expect(rail.container.querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(2);
        expect(foldCount(rail.container)?.textContent).toBe('5');
        expect(foldCount(rail.container)?.classList.contains('is-ticking')).toBe(true);
      } finally {
        rail.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.useRealTimers();
      }
    })();
  });

  it('keeps the same fold chip element as the count grows, so it does not replay its arrival', () => {
    vi.useFakeTimers();
    return (async () => {
      const rail = await mountRail(overviewOf([...Array.from({ length: 3 }, (_, index) => phaseStage(index)), phaseStage(3, 'active')]));
      try {
        const fold = rail.container.querySelector('.agent-run-rail-flow-stage--fold');
        rail.update(overviewOf([...Array.from({ length: 4 }, (_, index) => phaseStage(index)), phaseStage(4, 'active')]));
        act(() => { vi.advanceTimersByTime(1200); });
        expect(foldCount(rail.container)?.textContent).toBe('4');
        expect(rail.container.querySelector('.agent-run-rail-flow-stage--fold')).toBe(fold);
      } finally {
        rail.unmount();
        vi.useRealTimers();
      }
    })();
  });

  it('folds a whole run that is loaded at once without first showing each step', () => {
    vi.useFakeTimers();
    return (async () => {
      const rail = await mountRail(overviewOf([phaseStage(0, 'active')]));
      try {
        rail.update(overviewOf([...Array.from({ length: 20 }, (_, index) => phaseStage(index)), phaseStage(20, 'active')]));
        expect(rail.container.querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(2);
        expect(foldCount(rail.container)?.textContent).toBe('20');
        expect(vi.getTimerCount()).toBe(0);
      } finally {
        rail.unmount();
        vi.useRealTimers();
      }
    })();
  });

  it('folds a run it is switched to at once, because that run is not new', () => {
    vi.useFakeTimers();
    return (async () => {
      const rail = await mountRail(overviewOf([phaseStage(0, 'active')]), 'run-a');
      try {
        rail.update(overviewOf(Array.from({ length: 3 }, (_, index) => phaseStage(index))), 'run-b');
        expect(rail.container.querySelectorAll('.agent-run-rail-flow-stage')).toHaveLength(1);
        expect(foldCount(rail.container)?.textContent).toBe('3');
      } finally {
        rail.unmount();
        vi.useRealTimers();
      }
    })();
  });

  it('shows a step again when it starts a second time, instead of leaving it folded', () => {
    vi.useFakeTimers();
    return (async () => {
      const quiet = Array.from({ length: 4 }, (_, index) => phaseStage(index));
      const rail = await mountRail(overviewOf(quiet));
      try {
        expect(foldCount(rail.container)?.textContent).toBe('4');
        rail.update(overviewOf([...quiet.slice(0, 3), phaseStage(3, 'active')]));
        expect(foldCount(rail.container)?.textContent).toBe('3');
        expect(chipTooltips(rail.container)).toEqual([
          '3 steps, all completed: 3 processing steps and 0 exchanges with you. Select the rail to see every step.',
          'Step 4: in progress',
        ]);
        rail.update(overviewOf(quiet));
        expect(chipTooltips(rail.container)).toHaveLength(2);
        act(() => { vi.advanceTimersByTime(1200); });
        expect(foldCount(rail.container)?.textContent).toBe('4');
      } finally {
        rail.unmount();
        vi.useRealTimers();
      }
    })();
  });

  it('never folds a failed step, a denied exchange, or a step with a document', () => {
    const exchange: Stage = {
      id: 'overview:interaction:denied', kind: 'interaction', label: 'Basil asked', state: 'completed', startedAt: '2026-08-10T12:00:00Z', artifactCount: 0,
      interaction: { id: 'denied', entryId: 'denied', kind: 'approval', status: 'denied', prompt: 'Run it', askedAt: '2026-08-10T12:00:00Z', responseHidden: false, options: [] },
    };
    const stages: Stage[] = [
      ...Array.from({ length: 3 }, (_, index) => phaseStage(index)),
      exchange,
      ...Array.from({ length: 3 }, (_, index) => phaseStage(index + 3)),
      { ...phaseStage(6), artifactCount: 1 },
      phaseStage(7, 'failed'),
    ];
    const markup = renderToStaticMarkup(<AgentRunRail overview={overviewOf(stages)} onExpand={() => {}} />);

    expect((markup.match(/agent-run-rail-flow-stage--fold/g) || [])).toHaveLength(2);
    expect(markup).toContain('agent-run-rail-flow-stage--interaction');
    expect(markup).toContain('data-tooltip="Step 7: completed, 1 document"');
    expect(markup).toContain('data-tooltip="Step 8: needs attention"');
  });
});
