import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';

function progressEvent(content: string): WSEvent {
  return {
    event_type: 'agent_progress_update',
    agent_task_id: 'follow-1',
    root_task_id: 'root-1',
    timeline_entry: {
      id: `step-${content}`,
      type: 'step',
      timestamp: '2026-10-27T16:00:00Z',
      content,
      metadata: { progress_status: 'in_progress' },
    },
  };
}

function canceledStore() {
  const store = new AgentStore();
  store.registerAgent('root-1');
  store.updateStatus('root-1', 'processing');
  store.handleWSEvent({ event_type: 'agent_task_canceled', agent_task_id: 'root-1' });
  return store;
}

describe('a follow-up to a canceled run', () => {
  it('starts the new turn as live work, not as the earlier cancellation', () => {
    const store = canceledStore();
    expect(store.getAgent('root-1')?.isCanceled).toBe(true);

    store.beginFollowUpTurn('follow-1', 'root-1');

    const agent = store.getAgent('root-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.isCanceling).toBe(false);
  });

  it('shows the follow-up turn live progress instead of dropping it as post-cancellation noise', () => {
    const store = canceledStore();
    store.beginFollowUpTurn('follow-1', 'root-1');

    store.handleWSEvent(progressEvent('Reading the inbox'));

    const agent = store.getAgent('root-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.executionTimeline.map(entry => entry.content)).toContain('Reading the inbox');
  });

  it('can still cancel the follow-up turn itself', () => {
    const store = canceledStore();
    store.beginFollowUpTurn('follow-1', 'root-1');
    store.handleWSEvent(progressEvent('Reading the inbox'));

    store.handleWSEvent({ event_type: 'agent_task_canceled', agent_task_id: 'follow-1', root_task_id: 'root-1' });

    const agent = store.getAgent('root-1');
    expect(agent?.isCanceled).toBe(true);
    expect(agent?.status).toBe('failed');
  });

  it('also clears a cancellation that was still being requested when the follow-up began', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.updateStatus('root-1', 'processing');
    store.markCanceling('root-1');
    expect(store.getAgent('root-1')?.isCanceling).toBe(true);

    store.beginFollowUpTurn('follow-1', 'root-1');

    expect(store.getAgent('root-1')?.isCanceling).toBe(false);
    expect(store.getAgent('root-1')?.cancellationError).toBeUndefined();
  });

  it('routes a registered follow-up turn to its own entry even when the host keyed that entry by a turn id', () => {
    const store = new AgentStore();
    store.registerAgent('turn-key');
    store.updateAgentTaskText('turn-key', 'Finish removing the four items');
    store.updateStatus('turn-key', 'failed');
    store.markCanceled('turn-key');
    store.beginFollowUpTurn('follow-1', 'turn-key', undefined, 'root-1');

    store.handleWSEvent(progressEvent('Reading the document'));

    expect(store.getAgent('root-1')).toBeUndefined();
    const agent = store.getAgent('turn-key');
    expect(agent?.status).toBe('processing');
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.executionTimeline.map(entry => entry.content)).toContain('Reading the document');
    expect(store.getSelectedAgentId()).toBe('turn-key');
  });

  it('completes the chain when the follow-up to a canceled run finishes', () => {
    const store = canceledStore();
    store.beginFollowUpTurn('follow-1', 'root-1');
    store.handleWSEvent(progressEvent('Reading the inbox'));

    store.handleWSEvent({
      event_type: 'agent_task_result',
      agent_task_id: 'follow-1',
      root_task_id: 'root-1',
      result_payload: { message: 'All done' },
    } as WSEvent);

    const agent = store.getAgent('root-1');
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.status).toBe('completed');
  });
});
