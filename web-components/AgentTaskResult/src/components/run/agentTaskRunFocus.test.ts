import { describe, expect, it } from 'vitest';
import type { DisplayableAgentTask } from '../../types';
import {
  deriveAgentTaskRunFocusSummaries,
  resolveFocusedRun,
} from './agentTaskRunFocus';

function displaySource(overrides: Partial<DisplayableAgentTask> = {}): DisplayableAgentTask {
  return {
    agentTaskId: 'follow-up-2',
    timestamp: '2026-08-10T12:03:00Z',
    originalPrompt: 'Summarize the result',
    status: 'completed',
    result: 'Summary complete.',
    delegatedProviderReportCards: [],
    structuredFiles: [{ name: 'final.md', path: '/tmp/final.md', operation: 'write' }],
    referencePaths: [],
    agentTaskHistory: [
      {
        id: 'root-task',
        agentTaskText: 'Investigate the integration workflow',
        result: 'Initial investigation complete.',
        files: [{ name: 'initial.md', path: '/tmp/initial.md', operation: 'write' }],
        reference_paths: [],
        timestamp: '2026-08-10T12:00:00Z',
      },
      {
        id: 'follow-up-1',
        agentTaskText: 'Compare alternatives',
        result: 'Comparison complete.',
        files: [],
        reference_paths: [],
        timestamp: '2026-08-10T12:01:00Z',
      },
    ],
    progressSteps: [],
    executionTimeline: [],
    stepDetails: [],
    showWorkflowPlan: false,
    isStreaming: false,
    checkpointAvailable: false,
    thinkingSegments: [],
    ...overrides,
  };
}

describe('agent task run focus', () => {
  it('creates one initial-request summary for a direct task', () => {
    const runs = deriveAgentTaskRunFocusSummaries(displaySource({
      agentTaskId: 'root-task',
      agentTaskHistory: [],
      structuredFiles: [],
    }), false);

    expect(runs).toEqual([
      expect.objectContaining({
        id: 'root-task',
        kind: 'root',
        ordinal: 1,
        label: 'Initial request',
        requestText: 'Summarize the result',
        documentCount: 0,
      }),
    ]);
  });

  it('keeps each root/follow-up document count scoped to its own run', () => {
    const runs = deriveAgentTaskRunFocusSummaries(displaySource(), false);

    expect(runs.map(run => ({
      id: run.id,
      label: run.label,
      requestText: run.requestText,
      documentCount: run.documentCount,
    }))).toEqual([
      { id: 'root-task', label: 'Initial request', requestText: 'Investigate the integration workflow', documentCount: 1 },
      { id: 'follow-up-1', label: 'Follow-up 1', requestText: 'Compare alternatives', documentCount: 0 },
      { id: 'follow-up-2', label: 'Follow-up 2', requestText: 'Summarize the result', documentCount: 1 },
    ]);
  });

  it('marks a historical run with an explicit failed backend status as failed without making it active', () => {
    const source = displaySource();
    source.agentTaskHistory[1].errorMessage = 'The comparison failed.';
    source.agentTaskHistory[1].status = 'failed';

    const runs = deriveAgentTaskRunFocusSummaries(source, true);

    expect(runs[1]).toEqual(expect.objectContaining({
      id: 'follow-up-1',
      taskStatus: 'failed',
      isProcessing: false,
    }));
    expect(runs[2]).toEqual(expect.objectContaining({ isProcessing: true }));
  });

  it('does not infer a failed status solely from a populated narrative errorMessage', () => {
    const source = displaySource();
    source.agentTaskHistory[1].errorMessage = 'An agent advisory about a conflicting later literal path.';
    source.agentTaskHistory[1].outcome = 'partial';
    source.agentTaskHistory[1].resultSeverity = 'warning';
    source.agentTaskHistory[1].status = 'completed';

    const runs = deriveAgentTaskRunFocusSummaries(source, true);

    expect(runs[1]).toEqual(expect.objectContaining({
      id: 'follow-up-1',
      taskStatus: 'completed',
      outcome: 'partial',
      resultSeverity: 'warning',
    }));
  });

  it('populates resultSeverity for both historical and current run summaries', () => {
    const source = displaySource({ resultSeverity: 'success' });
    source.agentTaskHistory[0].resultSeverity = 'warning';

    const runs = deriveAgentTaskRunFocusSummaries(source, false);

    expect(runs[0].resultSeverity).toBe('warning');
    expect(runs[2].resultSeverity).toBe('success');
  });

  it('marks a run as having verified artifact output only when its artifact evidence is verified', () => {
    const source = displaySource({
      executionTimeline: [{
        id: 'artifact-final',
        type: 'artifact',
        timestamp: '2026-08-10T12:03:00Z',
        content: 'Verified final document',
        metadata: {
          artifact: {
            artifact_id: 'artifact-final',
            display_name: 'final.md',
            local_path: '/tmp/final.md',
            artifact_kind: 'file',
            operation: 'overwrite',
            lifecycle: 'verified',
            preview: { capability: 'unknown' },
            verification: { status: 'verified' },
          },
        },
      }],
    });

    const runs = deriveAgentTaskRunFocusSummaries(source, false);

    expect(runs[0].hasVerifiedArtifactOutput).toBe(false);
    expect(runs[2].hasVerifiedArtifactOutput).toBe(true);
  });

  it('defaults to the latest run when the requested focus is absent or stale', () => {
    const runs = deriveAgentTaskRunFocusSummaries(displaySource(), false);

    expect(resolveFocusedRun(runs, undefined).id).toBe('follow-up-2');
    expect(resolveFocusedRun(runs, 'deleted-run').id).toBe('follow-up-2');
    expect(resolveFocusedRun(runs, 'root-task').id).toBe('root-task');
  });
});
