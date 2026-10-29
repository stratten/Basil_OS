import { describe, expect, it } from 'vitest';
import {
  activeItemToRow,
  completionEventFromRun,
  ENDED_RUN_GRACE_MS,
  mergeActiveItems,
  rowsMissingFromActive,
  runHasEnded,
  withStepText,
} from './activeRuns';
import { finishedRowPatch, phaseOfRow } from './runPresentation';
import type { ActiveRunItem, MiniPanelRow, ScheduledRunRecord } from './types';

function item(overrides: Partial<ActiveRunItem> = {}): ActiveRunItem {
  return {
    run_id: 'run-1',
    scheduled_agent_task_id: 'sched-1',
    agent_task_id: 'task-1',
    scheduled_for: '2026-10-22T16:54:00Z',
    started_at: '2026-10-22T16:54:45Z',
    title: 'Check changes',
    agent_task_text: 'x',
    agent_task_status: 'processing',
    ...overrides,
  };
}

function row(overrides: Partial<MiniPanelRow> = {}): MiniPanelRow {
  return { ...activeItemToRow(item()), currentStep: 'Reading the feed', ...overrides };
}

describe('activeItemToRow', () => {
  it('flags a run whose agent task waits for the user', () => {
    expect(activeItemToRow(item({ agent_task_status: 'awaiting_user_input' })).awaitingInput).toBe(true);
    expect(activeItemToRow(item()).awaitingInput).toBe(false);
    expect(activeItemToRow(item({ agent_task_status: null })).awaitingInput).toBe(false);
  });
});

describe('mergeActiveItems', () => {
  it('adds a run the panel has not seen', () => {
    const merged = mergeActiveItems([], [item()]);
    expect(merged).toHaveLength(1);
    expect(merged[0].runId).toBe('run-1');
  });

  it('sets the approval flag on an existing row without touching its live step text', () => {
    const merged = mergeActiveItems([row()], [item({ agent_task_status: 'awaiting_user_input' })]);
    expect(merged[0].awaitingInput).toBe(true);
    expect(merged[0].currentStep).toBe('Reading the feed');
  });

  it('clears the flag once the backend no longer reports the task as waiting', () => {
    const merged = mergeActiveItems([row({ awaitingInput: true })], [item()]);
    expect(merged[0].awaitingInput).toBe(false);
  });

  it('keeps a flag raised by an approval request while its hold is active', () => {
    const holds = new Map([['run-1', 2000]]);
    expect(mergeActiveItems([row({ awaitingInput: true })], [item()], holds, 1000)[0].awaitingInput).toBe(true);
    expect(mergeActiveItems([row({ awaitingInput: true })], [item()], holds, 3000)[0].awaitingInput).toBe(false);
  });

  it('never reopens a finished row and keeps rows the backend no longer lists', () => {
    const finished = row({ status: 'finished', taskStatus: 'completed', outcome: 'success', awaitingInput: false });
    const gone = row({ runId: 'run-2' });
    const merged = mergeActiveItems([finished, gone], [item({ agent_task_status: 'awaiting_user_input' })]);
    expect(merged.find(r => r.runId === 'run-1')?.status).toBe('finished');
    expect(merged.find(r => r.runId === 'run-1')?.awaitingInput).toBe(false);
    expect(merged.find(r => r.runId === 'run-2')).toBeDefined();
  });

  it('fills in a missing agent task id from the backend', () => {
    const merged = mergeActiveItems([row({ agentTaskId: undefined })], [item()]);
    expect(merged[0].agentTaskId).toBe('task-1');
  });
});

describe('withStepText', () => {
  it('updates the running row of that agent task only', () => {
    const rows = [row(), row({ runId: 'run-2', agentTaskId: 'task-2' })];
    const next = withStepText(rows, 'task-1', 'Searching');
    expect(next[0].currentStep).toBe('Searching');
    expect(next[1].currentStep).toBe('Reading the feed');
  });

  it('never rewrites a finished row, so late step text cannot sit beside its final dot', () => {
    const finished = row({ status: 'finished', taskStatus: 'failed', outcome: 'partial' });
    expect(withStepText([finished], 'task-1', 'Verifying the outcome')[0]).toBe(finished);
  });
});

describe('rowsMissingFromActive', () => {
  const now = 1_000_000;
  const older = now - ENDED_RUN_GRACE_MS - 1;

  it('returns a running row the backend no longer lists', () => {
    const missing = rowsMissingFromActive([row({ startedAt: older })], [], now);
    expect(missing.map(r => r.runId)).toEqual(['run-1']);
  });

  it('leaves a row the backend still lists', () => {
    expect(rowsMissingFromActive([row({ startedAt: older })], [item()], now)).toEqual([]);
  });

  it('leaves a row that has only just appeared, which may not be listed yet', () => {
    expect(rowsMissingFromActive([row({ startedAt: now - 1000 })], [], now)).toEqual([]);
  });

  it('never returns a finished row', () => {
    const finished = row({ startedAt: older, status: 'finished', taskStatus: 'completed' });
    expect(rowsMissingFromActive([finished], [], now)).toEqual([]);
  });
});

describe('settling a row from its run record', () => {
  function record(overrides: Partial<ScheduledRunRecord> = {}): ScheduledRunRecord {
    return {
      id: 'run-1',
      scheduled_agent_task_id: 'sched-1',
      agent_task_id: 'task-1',
      status: 'completed',
      agent_task_status: 'completed',
      outcome: 'success',
      verification_status: 'resolved',
      ...overrides,
    };
  }

  it('treats running and scheduled records as not ended and every other status as ended', () => {
    expect(runHasEnded(record({ status: 'running' }))).toBe(false);
    expect(runHasEnded(record({ status: 'scheduled' }))).toBe(false);
    for (const status of ['completed', 'failed', 'canceled', 'missed']) {
      expect(runHasEnded(record({ status }))).toBe(true);
    }
  });

  it('settles a stuck row on the completed result, so it stops reading as working or verifying', () => {
    const stuck = row({ taskStatus: 'completed', verificationStatus: 'pending', outcome: 'success' });
    expect(phaseOfRow(stuck).kind).toBe('verifying');

    const settled = { ...stuck, ...finishedRowPatch(completionEventFromRun(record())) };
    expect(settled.status).toBe('finished');
    expect(phaseOfRow(settled)).toMatchObject({ kind: 'settled', outcome: 'success' });
  });

  it('settles a row stuck on working when the record is a partial result', () => {
    const stuck = row({ taskStatus: 'processing' });
    expect(phaseOfRow(stuck).kind).toBe('working');

    const settled = { ...stuck, ...finishedRowPatch(completionEventFromRun(record({ status: 'completed', agent_task_status: 'failed', outcome: 'partial' }))) };
    expect(phaseOfRow(settled)).toMatchObject({ kind: 'settled', outcome: 'partial' });
  });

  it('settles a failed run on the failure', () => {
    const settled = { ...row(), ...finishedRowPatch(completionEventFromRun(record({ status: 'failed', agent_task_status: null, outcome: null, verification_status: null }))) };
    expect(phaseOfRow(settled)).toMatchObject({ kind: 'settled', outcome: 'failed' });
  });

  it('settles a canceled run that never had an agent task as canceled', () => {
    const settled = { ...row(), ...finishedRowPatch(completionEventFromRun(record({ status: 'canceled', agent_task_id: null, agent_task_status: null, outcome: null, verification_status: null }))) };
    expect(phaseOfRow(settled).kind).toBe('canceled');
  });

  it('keeps the agent task id the row already has when the record has none', () => {
    const settled = { ...row(), ...finishedRowPatch(completionEventFromRun(record({ agent_task_id: null }))) };
    expect(settled.agentTaskId).toBe('task-1');
  });
});
