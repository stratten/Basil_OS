import { describe, expect, it } from 'vitest';
import type { AgentRunPresentation, AgentRunStage } from './agentRunPresentation';
import { deriveAgentRunOverviewPresentation, deriveAgentRunPresentation } from './agentRunPresentation';

function stage(id: string, overrides: Partial<AgentRunStage>): AgentRunStage {
  return Object.assign({
    id,
    kind: 'phase' as const,
    label: id,
    state: 'completed' as const,
    startedAt: '2026-08-10T12:00:00Z',
  }, overrides);
}

describe('deriveAgentRunOverviewPresentation', () => {
  it('deduplicates detailed phase activity, attaches documents, and appends the outcome', () => {
    const presentation: AgentRunPresentation = {
      terminalState: 'completed',
      stages: [
        stage('analysis-start', { phase: 'analysis', label: 'Analyzing request', state: 'active' }),
        stage('analysis-complete', { phase: 'analysis', label: 'Analyzing request', state: 'completed', completedAt: '2026-08-10T12:00:01Z' }),
        stage('tool-search', { kind: 'tool', label: 'Search sources' }),
        stage('report', { kind: 'artifact', label: 'report.md', artifactId: 'artifact-report' }),
        stage('execution-start', { phase: 'execution', label: 'Executing agent task', state: 'active' }),
        stage('execution-complete', { phase: 'execution', label: 'Executing agent task', state: 'completed' }),
        stage('outcome', { kind: 'outcome', label: 'Delivered report', state: 'completed' }),
      ],
    };

    expect(deriveAgentRunOverviewPresentation(presentation)).toEqual({
      terminalState: 'completed',
      activityCount: 7,
      artifactCount: 1,
      stages: [
        {
          id: 'overview:preparation',
          kind: 'phase',
          label: 'Preparing approach',
          state: 'completed',
          startedAt: '2026-08-10T12:00:00Z',
          completedAt: '2026-08-10T12:00:01Z',
          artifactCount: 1,
        },
        {
          id: 'overview:execution',
          kind: 'phase',
          label: 'Completing task',
          state: 'completed',
          startedAt: '2026-08-10T12:00:00Z',
          completedAt: '2026-08-10T12:00:00Z',
          artifactCount: 0,
        },
        {
          id: 'overview:outcome',
          kind: 'outcome',
          label: 'Delivered report',
          state: 'completed',
          startedAt: '2026-08-10T12:00:00Z',
          completedAt: undefined,
          artifactCount: 0,
        },
      ],
    });
  });

  it('creates a terminal overview for a completed task with no timeline entries', () => {
    expect(deriveAgentRunOverviewPresentation({ stages: [], terminalState: 'completed' })).toMatchObject({
      terminalState: 'completed',
      activityCount: 0,
      artifactCount: 0,
      stages: [
        expect.objectContaining({ kind: 'outcome', label: 'Run completed', state: 'completed' }),
      ],
    });
  });

  it('treats a partial terminal outcome as completed run progress rather than a failure', () => {
    const presentation = deriveAgentRunPresentation([
      {
        type: 'step',
        timestamp: '2026-08-10T12:00:00Z',
        content: 'Working',
        metadata: { progress_phase: 'Execution', progress_status: 'running' },
      },
    ], 'failed', false, 'partial');

    expect(presentation.terminalState).toBe('completed');
    expect(presentation.stages).toEqual([
      expect.objectContaining({ kind: 'phase', state: 'completed' }),
      expect.objectContaining({ kind: 'outcome', label: 'Partial result', state: 'completed' }),
    ]);
  });

  it('normalizes recovered failed phases when the run completed successfully', () => {
    const overview = deriveAgentRunOverviewPresentation({
      terminalState: 'completed',
      stages: [
        stage('setup', { phase: 'routing', state: 'failed' }),
        stage('execution', { phase: 'execution', state: 'completed' }),
        stage('outcome', { kind: 'outcome', label: 'Run completed', state: 'completed' }),
      ],
    });

    expect(overview.stages.filter(item => item.kind === 'phase')).toEqual([
      expect.objectContaining({ label: 'Preparing request', state: 'completed' }),
      expect.objectContaining({ label: 'Completing task', state: 'completed' }),
    ]);
  });

  it('presents a legacy completed-with-warnings outcome as completed', () => {
    const presentation = deriveAgentRunPresentation([], 'completed', false, 'completed_with_warnings');

    expect(presentation.terminalState).toBe('completed');
    expect(presentation.stages).toEqual([
      expect.objectContaining({ kind: 'outcome', label: 'Run completed', state: 'completed' }),
    ]);
  });
});
