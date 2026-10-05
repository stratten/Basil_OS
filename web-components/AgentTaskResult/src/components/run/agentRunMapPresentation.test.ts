import { describe, expect, it } from 'vitest';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import {
  deriveAgentRunMapTurns,
  documentCountLabel,
  presentRunStatus,
  RUN_STATUS_TONE_CLASS,
  runAttention,
} from './agentRunMapPresentation';

const baseRun: AgentTaskRunFocusSummary = {
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
};

const emptyOverview: AgentRunOverviewPresentation = { stages: [], activityCount: 0, artifactCount: 0, terminalState: 'completed' };

describe('presentRunStatus', () => {
  it('presents a verified path-continuity follow-up as completed with a note, not a red failure', () => {
    const status = presentRunStatus({ ...baseRun, outcome: 'partial', resultSeverity: 'warning', documentCount: 1, hasVerifiedArtifactOutput: true });
    expect(status).toEqual({ label: 'Completed with note', tone: 'note' });
    expect(RUN_STATUS_TONE_CLASS[status.tone]).not.toBe('is-failed');
  });

  it('presents an actual execution failure as needing attention with a red marker', () => {
    const status = presentRunStatus({ ...baseRun, taskStatus: 'failed', outcome: 'failed', resultSeverity: 'error' });
    expect(status).toEqual({ label: 'Needs attention', tone: 'failed' });
    expect(RUN_STATUS_TONE_CLASS[status.tone]).toBe('is-failed');
  });

  it('does not treat an unverified output as a verified continuity note', () => {
    const status = presentRunStatus({ ...baseRun, taskStatus: 'failed', outcome: 'partial', resultSeverity: 'warning', documentCount: 1, hasVerifiedArtifactOutput: false });
    expect(status.tone).toBe('failed');
  });

  it('presents a document-free partial result as amber partial, not a red failure', () => {
    const status = presentRunStatus({ ...baseRun, taskStatus: 'failed', outcome: 'partial', resultSeverity: 'warning' });
    expect(status).toEqual({ label: 'Partial result', tone: 'partial' });
    expect(RUN_STATUS_TONE_CLASS[status.tone]).toBe('is-partial');
    expect(runAttention({ ...baseRun, taskStatus: 'failed', outcome: 'partial', resultSeverity: 'warning' }, emptyOverview)).toEqual({ kind: 'note', label: 'Partial result' });
  });

  it('presents a processing run as in progress regardless of status', () => {
    const status = presentRunStatus({ ...baseRun, taskStatus: 'routing', isProcessing: true });
    expect(status).toEqual({ label: 'In progress', tone: 'processing' });
    expect(RUN_STATUS_TONE_CLASS[status.tone]).toBe('is-processing');
  });

  it('presents an awaiting-input run as waiting for input', () => {
    const status = presentRunStatus({ ...baseRun, taskStatus: 'awaitingInput' });
    expect(status).toEqual({ label: 'Waiting for input', tone: 'waiting' });
    expect(RUN_STATUS_TONE_CLASS[status.tone]).toBe('is-awaitingInput');
  });

  it('presents a completed run as completed', () => {
    expect(presentRunStatus(baseRun)).toEqual({ label: 'Completed', tone: 'completed' });
  });
});

describe('runAttention', () => {
  it('flags failed, waiting, and note runs and stays quiet for completed runs', () => {
    expect(runAttention({ ...baseRun, taskStatus: 'failed' }, emptyOverview)).toEqual({ kind: 'failed', label: 'Needs attention' });
    expect(runAttention({ ...baseRun, taskStatus: 'awaitingInput' }, emptyOverview)).toEqual({ kind: 'waiting', label: 'Waiting for you' });
    expect(runAttention({ ...baseRun, outcome: 'partial', resultSeverity: 'warning', hasVerifiedArtifactOutput: true }, emptyOverview)).toEqual({ kind: 'note', label: 'Note' });
    expect(runAttention(baseRun, emptyOverview)).toBeNull();
  });

  it('flags an unanswered exchange even when the run status is not waiting', () => {
    const overview: AgentRunOverviewPresentation = {
      ...emptyOverview,
      terminalState: 'active',
      stages: [{ id: 'overview:interaction:cp', kind: 'interaction', label: 'Basil asked you', state: 'waiting', startedAt: '', artifactCount: 0 }],
    };
    expect(runAttention({ ...baseRun, taskStatus: 'processing', isProcessing: true }, overview)).toEqual({ kind: 'waiting', label: 'Waiting for you' });
  });
});

describe('documentCountLabel', () => {
  it('labels zero, one, and many documents', () => {
    expect(documentCountLabel(0)).toBeNull();
    expect(documentCountLabel(1)).toBe('1 doc');
    expect(documentCountLabel(3)).toBe('3 docs');
  });
});

describe('deriveAgentRunMapTurns', () => {
  it('flattens request Markdown and derives each turn overview', () => {
    const [turn] = deriveAgentRunMapTurns([{ ...baseRun, requestText: '**Compare** the alternatives', documentCount: 2 }]);
    expect(turn.requestText).toBe('Compare the alternatives');
    expect(turn.documentLabel).toBe('2 docs');
    expect(turn.status.tone).toBe('completed');
    expect(turn.attention).toBeNull();
    expect(turn.overview.stages[turn.overview.stages.length - 1]).toEqual(expect.objectContaining({ kind: 'outcome', label: 'Run completed' }));
  });

  it('returns an empty list for no runs', () => {
    expect(deriveAgentRunMapTurns([])).toEqual([]);
  });
});
