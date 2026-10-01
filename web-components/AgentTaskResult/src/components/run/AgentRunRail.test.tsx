// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
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
    expect(markup).toContain('class="agent-run-rail-stage-tooltip">Analyzing request: completed, 1 document</span>');
    expect(markup).toContain('class="agent-run-rail-stage-tooltip">Completing task: completed</span>');
    expect(markup).toContain('class="agent-run-rail-stage-tooltip">Delivered report: completed</span>');
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
    expect(processing).toContain('class="agent-run-rail-stage-tooltip">Starting: in progress</span>');
    expect(processing).toContain('aria-label="Expand active run overview, 0 phases, 0 documents"');
    expect((idle.match(/class="agent-run-rail-flow-stage /g) || [])).toHaveLength(0);
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
});
