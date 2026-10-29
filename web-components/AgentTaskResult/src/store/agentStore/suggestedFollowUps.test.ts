import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';
import { readSuggestedFollowUps } from './suggestedFollowUps';

describe('readSuggestedFollowUps', () => {
  it('keeps up to three short distinct suggestions and drops malformed ones', () => {
    expect(readSuggestedFollowUps({
      suggested_follow_ups: ['  Draft a reply ', 'draft a reply', 7, '', 'x'.repeat(81), 'Archive the newsletters', 'Summarize the thread', 'Delete the spam'],
    })).toEqual(['Draft a reply', 'Archive the newsletters', 'Summarize the thread']);
  });

  it('returns undefined when the field is missing, malformed, or empty so no chips render', () => {
    expect(readSuggestedFollowUps(undefined)).toBeUndefined();
    expect(readSuggestedFollowUps({})).toBeUndefined();
    expect(readSuggestedFollowUps({ suggested_follow_ups: 'Draft a reply' })).toBeUndefined();
    expect(readSuggestedFollowUps({ suggested_follow_ups: [] })).toBeUndefined();
  });
});

describe('AgentStore suggested follow-ups', () => {
  const makeStore = () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    return store;
  };
  const send = (store: AgentStore, event: Record<string, unknown>) => store.handleWSEvent(event as unknown as WSEvent);

  it('stores suggestions from the verified outcome update and drops them when the outcome is not a success', () => {
    const store = makeStore();
    send(store, { event_type: 'agent_task_result', agent_task_id: 'task-1', success: true, result: 'Three unread emails.', result_payload: { outcome: 'success', verification_status: 'pending' } });
    expect(store.getAgent('task-1')?.suggestedFollowUps).toBeUndefined();

    send(store, { event_type: 'agent_task_outcome_update', agent_task_id: 'task-1', success: true, result: 'Three unread emails.', outcome: 'success', result_payload: { outcome: 'success', suggested_follow_ups: ['Draft a reply to the first email'] } });
    expect(store.getAgent('task-1')?.suggestedFollowUps).toEqual(['Draft a reply to the first email']);

    send(store, { event_type: 'agent_task_outcome_update', agent_task_id: 'task-1', success: false, result: 'Part done.', outcome: 'partial', result_payload: { outcome: 'partial', suggested_follow_ups: ['Do more'] } });
    expect(store.getAgent('task-1')?.suggestedFollowUps).toBeUndefined();
  });

  it('clears suggestions when a follow-up turn begins', () => {
    const store = makeStore();
    send(store, { event_type: 'agent_task_outcome_update', agent_task_id: 'task-1', success: true, result: 'Done.', outcome: 'success', result_payload: { suggested_follow_ups: ['Draft a reply'] } });
    expect(store.getAgent('task-1')?.suggestedFollowUps).toEqual(['Draft a reply']);

    store.beginFollowUpTurn('follow-up-1', 'task-1', undefined, 'task-1', undefined);
    expect(store.getAgent('task-1')?.suggestedFollowUps).toBeUndefined();
  });
});
