import { describe, expect, it } from 'vitest';
import type { CheckpointData, TimelineEntry } from '../../types';
import { questionNeedsRecovery, waitingQuestionInteraction } from './pendingQuestion';

function interactionEntry(id: string, kind: string, status: string, timestamp = '2026-11-02T16:58:42+00:00'): TimelineEntry {
  return {
    id: `user_interaction_${id}`,
    type: 'step',
    timestamp,
    content: 'Basil asked you a question',
    detail_kind: 'user_interaction',
    metadata: { user_interaction: { interaction_id: id, kind, status, prompt: `Question ${id}` } },
  };
}

const checkpoint: CheckpointData = { checkpoint_id: 'cp-1', prompt: 'Where?', input_type: 'data' };

function agent(overrides: Record<string, unknown> = {}) {
  return {
    status: 'processing' as const,
    executionTimeline: [interactionEntry('cp-1', 'clarification', 'waiting')],
    ...overrides,
  };
}

describe('waitingQuestionInteraction', () => {
  it('finds a waiting question and ignores answered ones, approvals, and pauses', () => {
    expect(waitingQuestionInteraction([
      interactionEntry('old', 'clarification', 'answered', '2026-11-02T16:50:00+00:00'),
      interactionEntry('ok', 'approval', 'waiting', '2026-11-02T16:51:00+00:00'),
      interactionEntry('stop', 'pause', 'waiting', '2026-11-02T16:52:00+00:00'),
    ])).toBeUndefined();
    expect(waitingQuestionInteraction([
      interactionEntry('old', 'clarification', 'answered', '2026-11-02T16:50:00+00:00'),
      interactionEntry('new', 'clarification', 'waiting', '2026-11-02T16:58:00+00:00'),
    ])?.id).toBe('new');
  });

  it('copes with no timeline', () => {
    expect(waitingQuestionInteraction(undefined)).toBeUndefined();
    expect(waitingQuestionInteraction([])).toBeUndefined();
  });
});

describe('questionNeedsRecovery', () => {
  it('asks for recovery when the timeline says a question is waiting but the window has nothing to show', () => {
    const result = questionNeedsRecovery(agent());
    expect(result).toMatchObject({ id: 'cp-1', prompt: 'Question cp-1' });
  });

  it('asks for recovery from status alone when the run is waiting with no timeline entry', () => {
    expect(questionNeedsRecovery(agent({ status: 'awaitingInput', executionTimeline: [] }))).toBe('status');
  });

  it('stays quiet while a question, skipped question, or other prompt is already in hand', () => {
    expect(questionNeedsRecovery(agent({ currentCheckpoint: checkpoint }))).toBeUndefined();
    expect(questionNeedsRecovery(agent({ inlineCheckpoint: checkpoint }))).toBeUndefined();
    expect(questionNeedsRecovery(agent({ showCheckpointPrompt: true }))).toBeUndefined();
    expect(questionNeedsRecovery(agent({ showApprovalPrompt: true }))).toBeUndefined();
    expect(questionNeedsRecovery(agent({ showTokenConnectPrompt: true }))).toBeUndefined();
  });

  it('stays quiet for a finished run, a run that is not waiting, and a missing agent', () => {
    expect(questionNeedsRecovery(agent({ status: 'completed' }))).toBeUndefined();
    expect(questionNeedsRecovery(agent({ status: 'failed' }))).toBeUndefined();
    expect(questionNeedsRecovery(agent({ executionTimeline: [] }))).toBeUndefined();
    expect(questionNeedsRecovery(undefined)).toBeUndefined();
  });

  it('does not flash back while an answer is being delivered or after it was remembered', () => {
    expect(questionNeedsRecovery(agent({ isCheckpointResumePending: true }))).toBeUndefined();
    expect(questionNeedsRecovery(agent({ answeredPrompts: [{ id: 'cp-1' }] }))).toBeUndefined();
  });

  it('still asks for recovery for a different, newer question after an earlier one was answered', () => {
    const result = questionNeedsRecovery(agent({
      answeredPrompts: [{ id: 'cp-0' }],
      executionTimeline: [interactionEntry('cp-1', 'clarification', 'waiting')],
    }));
    expect(result).toMatchObject({ id: 'cp-1' });
  });
});
