import { describe, expect, it } from 'vitest';
import type { DisplayableAgentTask } from '../../types';
import {
  agentTaskRunLabels,
  agentTaskRunLabelsForTask,
  agentTaskRunNumbers,
  agentTaskRunNumbersForTask,
  isRevisionNumber,
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

  it('labels turns Basil started itself as agent revisions, numbered apart from user follow-ups', () => {
    expect(agentTaskRunLabels([undefined, 'agent_follow_up', 'agent_follow_up', undefined, 'agent_follow_up', undefined])).toEqual([
      'Initial request',
      'Agent revision 1 of the initial request',
      'Agent revision 2 of the initial request',
      'Follow-up 1',
      'Agent revision 1 of Follow-up 1',
      'Follow-up 2',
    ]);
    expect(agentTaskRunLabels([])).toEqual([]);
  });

  it('names a revision for the follow-up it revises rather than for its position in the chain', () => {
    const labels = agentTaskRunLabels([undefined, undefined, undefined, undefined, undefined, 'agent_follow_up', 'agent_follow_up', undefined]);

    expect(labels).toEqual([
      'Initial request',
      'Follow-up 1',
      'Follow-up 2',
      'Follow-up 3',
      'Follow-up 4',
      'Agent revision 1 of Follow-up 4',
      'Agent revision 2 of Follow-up 4',
      'Follow-up 5',
    ]);
    expect(labels.join(' ')).not.toMatch(/revision 5/i);
  });

  it('calls a check the agent scheduled for itself a scheduled check, never a revision, and counts it per turn', () => {
    const labels = agentTaskRunLabels([
      undefined, undefined, 'scheduled_follow_up', 'scheduled_follow_up', 'agent_follow_up', 'scheduled_follow_up', undefined, 'scheduled_follow_up',
    ]);

    expect(labels).toEqual([
      'Initial request',
      'Follow-up 1',
      'Scheduled check 1 of Follow-up 1',
      'Scheduled check 2 of Follow-up 1',
      'Agent revision 1 of Follow-up 1',
      'Scheduled check 3 of Follow-up 1',
      'Follow-up 2',
      'Scheduled check 1 of Follow-up 2',
    ]);
    expect(labels.filter(label => /^Scheduled check/.test(label)).join(' ')).not.toMatch(/revision/i);
  });

  it('gives scheduled checks no number and keeps them out of everyone else\'s count', () => {
    expect(agentTaskRunNumbers([undefined, undefined, 'scheduled_follow_up', 'scheduled_follow_up', 'agent_follow_up', undefined, 'scheduled_follow_up'])).toEqual([
      '1', '2', '', '', '2.1', '3', '',
    ]);
    expect(isRevisionNumber('')).toBe(false);
    expect(agentTaskRunNumbers(['scheduled_follow_up'])).toEqual(['1']);
    expect(agentTaskRunLabels(['scheduled_follow_up'])).toEqual(['Initial request']);
  });

  it('numbers non-revision turns 1, 2, 3 and agent revisions parent.k', () => {
    expect(agentTaskRunNumbers([])).toEqual([]);
    expect(agentTaskRunNumbers([undefined])).toEqual(['1']);
    expect(agentTaskRunNumbers([undefined, undefined, 'conversation'])).toEqual(['1', '2', '3']);
    expect(agentTaskRunNumbers([undefined, 'agent_follow_up', 'agent_follow_up', undefined, 'agent_follow_up', undefined])).toEqual([
      '1', '1.1', '1.2', '2', '2.1', '3',
    ]);
    expect(agentTaskRunNumbers(['agent_follow_up', 'agent_follow_up'])).toEqual(['1', '1.1']);
    expect(agentTaskRunNumbers([undefined, ...Array(11).fill(undefined), 'agent_follow_up', 'agent_follow_up'])).toEqual([
      ...Array.from({ length: 12 }, (_, index) => String(index + 1)),
      '12.1',
      '12.2',
    ]);
  });

  it('treats only a dotted display number as a revision number', () => {
    expect(isRevisionNumber('1.1')).toBe(true);
    expect(isRevisionNumber('12.3')).toBe(true);
    expect(isRevisionNumber('4')).toBe(false);
  });

  it('puts the same number on the rail summary that the revision label carries', () => {
    const source = displaySource({ currentTurnOriginType: undefined });
    source.agentTaskHistory[1].originType = 'agent_follow_up';

    const runs = deriveAgentTaskRunFocusSummaries(source, false);

    expect(runs.map(run => [run.ordinal, run.displayNumber, run.label])).toEqual([
      [1, '1', 'Initial request'],
      [2, '1.1', 'Agent revision 1 of the initial request'],
      [3, '2', 'Follow-up 1'],
    ]);
  });

  it('lets the rail number of a user follow-up match its position among non-revision turns', () => {
    const origins = [undefined, 'agent_follow_up', 'agent_follow_up', undefined];
    expect(agentTaskRunLabels(origins)[3]).toBe('Follow-up 1');
    expect(agentTaskRunNumbers(origins)[3]).toBe('2');
  });

  it('never labels the root turn an agent revision and treats other origins as user follow-ups', () => {
    expect(agentTaskRunLabels(['agent_follow_up', 'conversation', 'todo'])).toEqual([
      'Initial request',
      'Follow-up 1',
      'Follow-up 2',
    ]);
  });

  it('labels run summaries by turn origin, including the current turn', () => {
    const source = displaySource({ currentTurnOriginType: 'agent_follow_up' });
    source.agentTaskHistory[1].originType = 'agent_follow_up';

    const runs = deriveAgentTaskRunFocusSummaries(source, false);

    expect(runs.map(run => run.label)).toEqual([
      'Initial request',
      'Agent revision 1 of the initial request',
      'Agent revision 2 of the initial request',
    ]);
    expect(runs.map(run => run.displayNumber)).toEqual(['1', '1.1', '1.2']);
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

  it('lists the current turn once when history already holds the same turn, keeping that turn\'s label and the fresher data', () => {
    const runs = deriveAgentTaskRunFocusSummaries(displaySource({
      agentTaskId: 'root-task',
      currentTurnTaskId: 'follow-up-1',
      originalPrompt: 'Compare alternatives (live)',
      result: 'Live comparison.',
    }), true);

    expect(runs.map(run => run.id)).toEqual(['root-task', 'follow-up-1']);
    const turn = runs[1];
    expect(turn.requestText).toBe('Compare alternatives (live)');
    expect(turn.resultText).toBe('Live comparison.');
    expect(turn.isProcessing).toBe(true);
    expect(turn.ordinal).toBe(2);
    expect(turn.label).toBe(agentTaskRunLabelsForTask(displaySource())[1]);
    expect(turn.displayNumber).toBe(agentTaskRunNumbersForTask(displaySource())[1]);
  });

  it('keeps the first of two history items that share an id', () => {
    const source = displaySource();
    const runs = deriveAgentTaskRunFocusSummaries(displaySource({
      agentTaskHistory: [source.agentTaskHistory[0], source.agentTaskHistory[1], { ...source.agentTaskHistory[1], result: 'Stale copy.' }],
      agentTaskId: 'follow-up-2',
    }), false);

    expect(runs.map(run => run.id)).toEqual(['root-task', 'follow-up-1', 'follow-up-2']);
    expect(runs[1].resultText).toBe('Comparison complete.');
  });

  it('defaults to the latest run when the requested focus is absent or stale', () => {
    const runs = deriveAgentTaskRunFocusSummaries(displaySource(), false);

    expect(resolveFocusedRun(runs, undefined).id).toBe('follow-up-2');
    expect(resolveFocusedRun(runs, 'deleted-run').id).toBe('follow-up-2');
    expect(resolveFocusedRun(runs, 'root-task').id).toBe('root-task');
  });
});
