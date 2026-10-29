import { describe, expect, it } from 'vitest';
import {
  parseAgentTaskArtifact,
  parseAgentTaskPresentationSummary,
  parseAgentTaskPresentationSummaryForTask,
  parseDelegatedProviderReportCard,
  parseDelegatedProviderReportCards,
  parseDelegatedProviderReportCardsForParent,
} from './artifactContract';

const readyArtifact = {
  artifact_id: 'artifact-report',
  display_name: 'report.md',
  local_path: '/tmp/report.md',
  artifact_kind: 'file',
  operation: 'create',
  lifecycle: 'ready',
  source_timeline_entry_id: 'timeline-report',
  source_step_id: 'step-write',
  preview: { capability: 'unknown', kind: null },
  verification: { status: 'unknown', summary: null },
  content: 'must not cross the contract boundary',
};

const readySummary = {
  agent_task_id: 'task-report',
  lifecycle: 'awaiting_user_input',
  latest_activity: 'Created report.md',
  workflow: { total_steps: 3, completed_steps: 2 },
  artifacts: [readyArtifact],
  artifact_count: 1,
  verification_status: 'unknown',
  requires_user_attention: true,
  raw_detail: { command: 'must not cross the contract boundary' },
};

describe('parseAgentTaskArtifact', () => {
  it('converts selected snake_case artifact fields without retaining unknown fields', () => {
    expect(parseAgentTaskArtifact(readyArtifact)).toEqual({
      artifactId: 'artifact-report',
      displayName: 'report.md',
      localPath: '/tmp/report.md',
      artifactKind: 'file',
      operation: 'create',
      lifecycle: 'ready',
      sourceTimelineEntryId: 'timeline-report',
      sourceStepId: 'step-write',
      preview: { capability: 'unknown' },
      verification: { status: 'unknown' },
    });
  });

  it('accepts an unavailable pathless artifact', () => {
    expect(parseAgentTaskArtifact({
      artifact_id: 'artifact-unavailable',
      display_name: 'deleted-report.md',
      artifact_kind: 'file',
      lifecycle: 'unavailable',
      preview: { capability: 'unsupported' },
      verification: { status: 'unknown' },
    })).toEqual({
      artifactId: 'artifact-unavailable',
      displayName: 'deleted-report.md',
      artifactKind: 'file',
      lifecycle: 'unavailable',
      preview: { capability: 'unsupported' },
      verification: { status: 'unknown' },
    });
  });

  it.each([
    ['blank artifact ID', { ...readyArtifact, artifact_id: ' ' }],
    ['blank display name', { ...readyArtifact, display_name: ' ' }],
    ['relative local path', { ...readyArtifact, local_path: 'report.md' }],
    ['blank local path', { ...readyArtifact, local_path: ' ' }],
    ['unknown artifact kind', { ...readyArtifact, artifact_kind: 'virtual' }],
    ['unknown lifecycle', { ...readyArtifact, lifecycle: 'invented' }],
    ['unknown preview capability', { ...readyArtifact, preview: { capability: 'rendered' } }],
    ['unknown verification status', { ...readyArtifact, verification: { status: 'asserted' } }],
    ['an overlong verification summary', { ...readyArtifact, verification: { status: 'verified', summary: 'x'.repeat(2_001) } }],
  ])('rejects an artifact with %s', (_label, value) => {
    expect(parseAgentTaskArtifact(value)).toBeUndefined();
  });
});

describe('parseAgentTaskPresentationSummary', () => {
  it('converts a valid bounded summary into camelCase presentation data', () => {
    expect(parseAgentTaskPresentationSummary(readySummary)).toEqual({
      agentTaskId: 'task-report',
      lifecycle: 'awaiting_user_input',
      latestActivity: 'Created report.md',
      workflow: { totalSteps: 3, completedSteps: 2 },
      artifacts: [
        {
          artifactId: 'artifact-report',
          displayName: 'report.md',
          localPath: '/tmp/report.md',
          artifactKind: 'file',
          operation: 'create',
          lifecycle: 'ready',
          sourceTimelineEntryId: 'timeline-report',
          sourceStepId: 'step-write',
          preview: { capability: 'unknown' },
          verification: { status: 'unknown' },
        },
      ],
      artifactCount: 1,
      verificationStatus: 'unknown',
      requiresUserAttention: true,
      delegatedProviderReportCards: [],
    });
  });

  it('preserves legacy detail compatibility by returning undefined for an absent summary', () => {
    expect(parseAgentTaskPresentationSummary(undefined)).toBeUndefined();
    expect(parseAgentTaskPresentationSummary(null)).toBeUndefined();
  });

  it('accepts the six-artifact presentation boundary', () => {
    const summary = parseAgentTaskPresentationSummary({
      ...readySummary,
      artifacts: Array.from({ length: 6 }, () => readyArtifact),
      artifact_count: 6,
    });

    expect(summary?.artifacts).toHaveLength(6);
    expect(summary?.artifactCount).toBe(6);
  });

  it.each([
    ['an unrecognized task lifecycle', { ...readySummary, lifecycle: 'queued' }],
    ['an over-limit artifact list', { ...readySummary, artifacts: Array.from({ length: 7 }, () => readyArtifact), artifact_count: 7 }],
    ['a non-safe workflow count', { ...readySummary, workflow: { total_steps: 1.5, completed_steps: 0 } }],
    ['an overlong latest activity', { ...readySummary, latest_activity: 'x'.repeat(161) }],
    ['a negative artifact count', { ...readySummary, artifacts: [], artifact_count: -1 }],
    ['an artifact count below the selected artifact list length', { ...readySummary, artifact_count: 0 }],
    ['a malformed nested artifact', { ...readySummary, artifacts: [{ ...readyArtifact, local_path: 'relative.md' }] }],
  ])('rejects a summary with %s', (_label, value) => {
    expect(parseAgentTaskPresentationSummary(value)).toBeUndefined();
  });
});

describe('parseAgentTaskPresentationSummaryForTask', () => {
  it('accepts only a summary whose durable task identity matches the displayed turn', () => {
    expect(parseAgentTaskPresentationSummaryForTask('task-report', readySummary)?.agentTaskId).toBe('task-report');
    expect(parseAgentTaskPresentationSummaryForTask('other-task', readySummary)).toBeUndefined();
    expect(parseAgentTaskPresentationSummaryForTask('task-report', { agent_task_id: 'task-report' })).toBeUndefined();
  });
});

const validCard = {
  delegated_agent_run_id: 'run-1',
  run_status: 'supervision_due',
  run_revision: 4,
  capture_state: 'available',
  evidence_count: 3,
  latest_summary: 'Provider completed this turn.',
  verification_state: 'not_applicable',
};

describe('parseDelegatedProviderReportCards', () => {
  it('parses valid cards and summary delegation', () => {
    const parsedCard = {
      delegatedAgentRunId: 'run-1',
      runStatus: 'supervision_due',
      runRevision: 4,
      captureState: 'available',
      evidenceCount: 3,
      latestSummary: 'Provider completed this turn.',
      verificationState: 'not_applicable',
    };
    expect(parseDelegatedProviderReportCard(validCard)).toEqual(parsedCard);
    expect(parseDelegatedProviderReportCards({ items: [validCard] })).toEqual([parsedCard]);
    expect(parseAgentTaskPresentationSummary({
      ...readySummary,
      delegated_provider_report_cards: { items: [validCard] },
    })?.delegatedProviderReportCards).toHaveLength(1);
    expect(parseAgentTaskPresentationSummary(readySummary)?.delegatedProviderReportCards).toEqual([]);
  });

  it.each([
    ['duplicate run ids', { items: [validCard, validCard] }],
    ['malformed run status', { items: [{ ...validCard, run_status: 'invented' }] }],
    ['overlong summary', { items: [{ ...validCard, latest_summary: 'x'.repeat(161) }] }],
    ['negative evidence count', { items: [{ ...validCard, evidence_count: -1 }] }],
    ['missing items array', {}],
  ])('rejects %s', (_label, value) => {
    expect(parseDelegatedProviderReportCards(value)).toBeUndefined();
  });

  it('accepts unavailable, verified, and mismatch states', () => {
    expect(parseDelegatedProviderReportCards({ items: [
      { ...validCard, capture_state: 'unavailable', evidence_count: 0, latest_summary: null, verification_state: 'unavailable' },
      { ...validCard, delegated_agent_run_id: 'run-2', verification_state: 'verified' },
      { ...validCard, delegated_agent_run_id: 'run-3', verification_state: 'verification_mismatch' },
    ] })).toHaveLength(3);
  });
});

describe('parseDelegatedProviderReportCardsForParent', () => {
  it('requires parent identity to match', () => {
    expect(parseDelegatedProviderReportCardsForParent('parent-task', {
      parent_agent_task_id: 'parent-task',
      items: [validCard],
    })).toHaveLength(1);
    expect(parseDelegatedProviderReportCardsForParent('parent-task', {
      parent_agent_task_id: 'other-task',
      items: [validCard],
    })).toBeUndefined();
  });
});
