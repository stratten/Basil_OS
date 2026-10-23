import { describe, expect, it } from 'vitest';
import { dotClassOfPhase, finishedRowPatch, phaseOfRow, rowEndedCleanly } from './runPresentation';
import type { MiniPanelRow } from './types';

function row(overrides: Partial<MiniPanelRow> = {}): MiniPanelRow {
  return {
    runId: 'run-1',
    scheduledAgentTaskId: 'sched-1',
    agentTaskId: 'task-1',
    title: 'Check changes',
    currentStep: 'Reading the feed',
    status: 'running',
    startedAt: 0,
    ...overrides,
  };
}

describe('phaseOfRow', () => {
  it('reads a running row without task facts as working', () => {
    expect(phaseOfRow(row()).kind).toBe('working');
  });

  it('lets the approval flag win over a stored status that has not caught up', () => {
    expect(phaseOfRow(row({ awaitingInput: true, taskStatus: 'processing' })).kind).toBe('awaiting');
  });

  it('ignores the approval flag once the run has finished', () => {
    expect(phaseOfRow(row({ status: 'finished', awaitingInput: true, taskStatus: 'completed', outcome: 'success' })).kind).toBe('settled');
  });

  it('settles a task saved as failed with a partial outcome as partial, using the same reading as the result window', () => {
    const phase = phaseOfRow(row({ status: 'finished', taskStatus: 'failed', outcome: 'partial', verificationStatus: 'resolved' }));
    expect(phase).toMatchObject({ kind: 'settled', outcome: 'partial' });
    expect(dotClassOfPhase(phase)).toContain('outcome-partial-mark');
  });

  it('reads a failure outcome on a completed task as a failure', () => {
    expect(phaseOfRow(row({ taskStatus: 'completed', outcome: 'failed' })).outcome).toBe('failed');
  });

  it('waits on verification instead of settling', () => {
    expect(phaseOfRow(row({ taskStatus: 'failed', outcome: 'partial', verificationStatus: 'pending' })).kind).toBe('verifying');
  });
});

describe('finishedRowPatch', () => {
  it('carries the agent task status, outcome and verification state from the event', () => {
    expect(
      finishedRowPatch({
        status: 'completed',
        agent_task_status: 'failed',
        outcome: 'partial',
        verification_status: 'resolved',
        agent_task_id: 'task-9',
      }),
    ).toEqual({
      status: 'finished',
      taskStatus: 'failed',
      outcome: 'partial',
      verificationStatus: 'resolved',
      awaitingInput: false,
      agentTaskId: 'task-9',
    });
  });

  it('falls back to the run status from an older backend and keeps an existing agent task id when the event has none', () => {
    const completed = finishedRowPatch({ status: 'completed' });
    const failed = finishedRowPatch({ status: 'failed' });

    expect(completed.taskStatus).toBe('completed');
    expect(failed.taskStatus).toBe('failed');
    expect('agentTaskId' in completed).toBe(false);
  });
});

describe('rowEndedCleanly', () => {
  it('is true only for a verified success', () => {
    expect(rowEndedCleanly(row({ taskStatus: 'completed', outcome: 'success', verificationStatus: 'resolved' }))).toBe(true);
    expect(rowEndedCleanly(row({ taskStatus: 'failed', outcome: 'partial' }))).toBe(false);
    expect(rowEndedCleanly(row({ taskStatus: 'failed', outcome: 'failed' }))).toBe(false);
    expect(rowEndedCleanly(row({ taskStatus: 'paused' }))).toBe(false);
  });
});
