import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import { AgentRunRail } from './AgentRunRail';

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
});
