import { describe, expect, it } from 'vitest';
import type { TimelineEntry } from '../../types';
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

  it('keeps an exchange with the user as its own chronological stage instead of merging it into a phase', () => {
    const timeline: TimelineEntry[] = [
      { id: 'exec-1', type: 'step', timestamp: '2026-10-04T23:39:00Z', content: 'Searching', metadata: { progress_phase: 'execution' } },
      {
        id: 'user_interaction_cp',
        type: 'step',
        timestamp: '2026-10-04T23:40:02Z',
        content: 'Which hotel?',
        detail_kind: 'user_interaction',
        metadata: {
          progress_step: 'You answered',
          user_interaction: { interaction_id: 'cp', kind: 'clarification', status: 'answered', prompt: 'Which hotel?', asked_at: '2026-10-04T23:40:02Z', response: 'La Fantaisie' },
        },
      },
      { id: 'exec-2', type: 'step', timestamp: '2026-10-04T23:45:00Z', content: 'Searching shops', metadata: { progress_phase: 'execution' } },
    ];

    const presentation = deriveAgentRunPresentation(timeline, 'processing', true);
    const overview = deriveAgentRunOverviewPresentation(presentation);

    expect(presentation.stages.map(item => item.kind)).toEqual(['phase', 'interaction', 'phase']);
    expect(overview.stages.map(item => [item.kind, item.label])).toEqual([
      ['phase', 'Completing task'],
      ['interaction', 'Basil asked'],
    ]);
    expect(overview.stages[1]).toMatchObject({ state: 'completed', interaction: { response: 'La Fantaisie' } });
  });

  it('marks a pending exchange as waiting even after the run completes', () => {
    const presentation = deriveAgentRunPresentation([
      {
        id: 'user_interaction_ap',
        type: 'step',
        timestamp: '2026-10-04T23:40:02Z',
        content: 'rm -rf build',
        detail_kind: 'user_interaction',
        metadata: { user_interaction: { interaction_id: 'ap', kind: 'approval', status: 'waiting', prompt: 'rm -rf build' } },
      },
    ], 'completed', false);

    expect(deriveAgentRunOverviewPresentation(presentation).stages).toEqual([
      expect.objectContaining({ kind: 'interaction', label: 'Basil asked to run', state: 'waiting' }),
      expect.objectContaining({ kind: 'outcome', state: 'completed' }),
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
