import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';
import { isLiveProgressEvent, isTerminalProgressEvent } from './progressEvent';

function makeStoreWithAgent(agentTaskId = 'task-1') {
  const store = new AgentStore();
  store.registerAgent(agentTaskId);
  return store;
}

function dispatch(store: AgentStore, event: WSEvent) {
  store.handleWSEvent(event);
}

describe('AgentStore outcome verification updates', () => {
  it('sets verificationStatus pending from agent_task_result payload', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: true,
      result: 'Answer text',
      result_payload: {
        outcome: 'success',
        verification_status: 'pending',
        files: [],
      },
    });

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('completed');
    expect(agent?.result).toBe('Answer text');
    expect(agent?.verificationStatus).toBe('pending');
  });

  it('confirms a retry when its first live progress event arrives', () => {
    const store = makeStoreWithAgent();
    store.setError('task-1', 'OperationalError: database is locked');
    store.resetForRetry('task-1');

    dispatch(store, {
      event_type: 'agent_task_progress',
      agent_task_id: 'task-1',
      status: 'in_progress',
      details: 'Reading the retry context',
    });

    expect(store.getAgent('task-1')).toMatchObject({
      status: 'processing',
      errorMessage: undefined,
      isRetryPending: false,
    });
  });

  it('clears a retry marker when a terminal status arrives through the shared store transition', () => {
    const store = makeStoreWithAgent();
    store.setError('task-1', 'OperationalError: database is locked');
    store.resetForRetry('task-1');

    store.updateStatus('task-1', 'failed');

    expect(store.getAgent('task-1')).toMatchObject({
      status: 'failed',
      isRetryPending: false,
    });
  });

  it('handleOutcomeUpdate resolves outcome, files, and failed status', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: true,
      result: 'Provisional answer',
      result_payload: {
        outcome: 'success',
        verification_status: 'pending',
        files: [],
      },
    });

    dispatch(store, {
      event_type: 'agent_task_outcome_update',
      agent_task_id: 'task-1',
      success: false,
      result: 'Revised answer with warning',
      outcome: 'partial',
      result_payload: {
        outcome: 'partial',
        verification_status: 'resolved',
        files: [{ name: 'doc.txt', full_path: '/tmp/doc.txt', operation: 'created' }],
      },
    });

    const agent = store.getAgent('task-1');
    expect(agent?.verificationStatus).toBe('resolved');
    expect(agent?.outcome).toBe('partial');
    expect(agent?.status).toBe('failed');
    expect(agent?.result).toBe('Revised answer with warning');
    expect(agent?.errorMessage).toBe('Some requested work remains incomplete.');
    expect(agent?.resultSeverity).toBe('warning');
    expect(agent?.structuredFiles).toHaveLength(1);
    expect(agent?.structuredFiles[0].path).toBe('/tmp/doc.txt');
  });

  it('restores completed status when verification upgrades a provisional failure', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: false,
      error: 'A step failed',
      result: 'Partial answer text',
      result_payload: { outcome: 'partial', verification_status: 'pending', files: [] },
    });

    let agent = store.getAgent('task-1');
    expect(agent?.status).toBe('failed');
    expect(agent?.verificationStatus).toBe('pending');

    dispatch(store, {
      event_type: 'agent_task_outcome_update',
      agent_task_id: 'task-1',
      success: true,
      outcome: 'success',
      result_payload: { outcome: 'success', verification_status: 'resolved', files: [] },
    });

    agent = store.getAgent('task-1');
    expect(agent?.status).toBe('completed');
    expect(agent?.outcome).toBe('success');
    expect(agent?.verificationStatus).toBe('resolved');
  });

  it('ignores a stale outcome update once a newer follow-up turn is active', () => {
    const store = makeStoreWithAgent('root-1');

    // First turn completes with a pending cloud verification.
    dispatch(store, {
      event_type: 'agent_task_result',
      agent_task_id: 'root-1',
      success: true,
      result: 'First turn answer',
      result_payload: { outcome: 'success', verification_status: 'pending', files: [] },
    });

    // User starts a follow-up turn (routes to the same root) before verification lands.
    dispatch(store, {
      event_type: 'agent_progress_update',
      agent_task_id: 'follow-up-2',
      root_task_id: 'root-1',
      message: 'Working on the follow-up',
    });

    // The prior turn's late verification must not clobber the active newer turn.
    dispatch(store, {
      event_type: 'agent_task_outcome_update',
      agent_task_id: 'root-1',
      root_task_id: 'root-1',
      success: false,
      outcome: 'failure',
      result: 'Stale first-turn revision',
      result_payload: { outcome: 'failure', verification_status: 'resolved', files: [] },
    });

    // The follow-up turn owns the row now (beginFollowUpTurn reset it to processing);
    // the stale update must not have applied its failure values.
    const agent = store.getAgent('root-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.result).not.toBe('Stale first-turn revision');
    expect(agent?.outcome).not.toBe('failure');
    expect(agent?.verificationStatus).not.toBe('resolved');
  });

  it('applies agent_task_outcome_update after terminal agent_task_result', () => {
    const terminal: WSEvent = {
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: false,
      error: 'Provisional result may be incomplete',
      result: 'Provisional answer',
      result_payload: { verification_status: 'pending', outcome: 'partial', files: [] },
    };
    const update: WSEvent = {
      event_type: 'agent_task_outcome_update',
      agent_task_id: 'task-1',
      success: true,
      outcome: 'success',
      result_payload: {
        outcome: 'success',
        verification_status: 'resolved',
        files: [],
      },
    };

    expect(isTerminalProgressEvent(terminal)).toBe(true);
    expect(isTerminalProgressEvent(update)).toBe(false);
    expect(isLiveProgressEvent(update)).toBe(false);

    const store = makeStoreWithAgent();
    dispatch(store, terminal);
    dispatch(store, update);

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('completed');
    expect(agent?.errorMessage).toBeUndefined();
    expect(agent?.verificationStatus).toBe('resolved');
    expect(agent?.outcome).toBe('success');
  });

  it('drops progress and results after cancellation starts', () => {
    const store = makeStoreWithAgent();
    store.markCancelling('task-1');

    dispatch(store, {
      event_type: 'agent_task_progress',
      agent_task_id: 'task-1',
      message: 'Late progress',
    });
    dispatch(store, {
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: true,
      result: 'Late result',
    });

    const agent = store.getAgent('task-1');
    expect(agent?.isCancelling).toBe(true);
    expect(agent?.currentStep).toBe('Cancelling...');
    expect(agent?.result).not.toBe('Late result');
  });

  it('keeps cancelled state terminal when late streaming arrives', () => {
    const store = makeStoreWithAgent();
    dispatch(store, {
      event_type: 'agent_task_cancelled',
      agent_task_id: 'task-1',
      message: 'Cancelled',
    });
    dispatch(store, {
      event_type: 'agent_task_streaming',
      agent_task_id: 'task-1',
      partial_result: 'Late stream',
    });

    const agent = store.getAgent('task-1');
    expect(agent?.isCancelled).toBe(true);
    expect(agent?.isCancelling).toBe(false);
    expect(agent?.currentStep).toBe('Cancelled');
    expect(agent?.result).not.toBe('Late stream');
  });

  it('ignores stale sibling cancellation and accepts cancellation for the active follow-up', () => {
    const store = makeStoreWithAgent('root-1');
    dispatch(store, {
      event_type: 'agent_task_progress',
      agent_task_id: 'follow-up-2',
      root_task_id: 'root-1',
      message: 'Running follow-up',
    });

    dispatch(store, {
      event_type: 'agent_task_cancelled',
      agent_task_id: 'root-1',
      root_task_id: 'root-1',
      message: 'Stale cancellation',
    });
    expect(store.getAgent('root-1')?.isCancelled).not.toBe(true);

    dispatch(store, {
      event_type: 'agent_task_cancelled',
      agent_task_id: 'follow-up-2',
      root_task_id: 'root-1',
      message: 'Active follow-up cancelled',
    });
    expect(store.getAgent('root-1')?.isCancelled).toBe(true);
    expect(store.getAgent('root-1')?.currentStep).toBe('Cancelled');
  });
});
