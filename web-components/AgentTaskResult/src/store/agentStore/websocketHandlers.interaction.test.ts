import { describe, expect, it } from 'vitest';
import { AgentStore } from './websocketHandlers';

function makeStore() {
  const store = new AgentStore();
  store.registerAgent('task-1');
  return store;
}

function thinking(store: AgentStore, iteration: number, text: string, timestamp: string, complete = true) {
  store.handleWSEvent({
    event_type: 'agent_progress_update',
    agent_task_id: 'task-1',
    timestamp,
    thinking: text,
    thinking_complete: complete,
    thinking_iteration: iteration,
  });
}

describe('AgentStore exchanges with the user', () => {
  it('upserts one live exchange entry from ask to answer', () => {
    const store = makeStore();
    const entry = (status: string, extra: Record<string, unknown> = {}) => ({
      id: 'user_interaction_cp',
      type: 'step',
      timestamp: '2026-10-04T23:40:02+00:00',
      content: 'Which hotel?',
      detail_kind: 'user_interaction',
      metadata: {
        user_interaction: { interaction_id: 'cp', kind: 'clarification', status, prompt: 'Which hotel?', ...extra },
      },
    });

    store.handleWSEvent({ event_type: 'agent_task_step_detail', agent_task_id: 'task-1', timeline_entry: entry('waiting') });
    store.handleWSEvent({
      event_type: 'agent_task_step_detail',
      agent_task_id: 'task-1',
      timeline_entry: entry('answered', { response: 'La Fantaisie' }),
    });

    const exchanges = store.getAgent('task-1')!.executionTimeline.filter(item => item.detail_kind === 'user_interaction');
    expect(exchanges).toHaveLength(1);
    expect(exchanges[0].metadata?.user_interaction).toMatchObject({ status: 'answered', response: 'La Fantaisie' });
  });

  it('hands React a new timeline array when an answer replaces its question in place', () => {
    const store = makeStore();
    const entry = (status: string) => ({
      id: 'user_interaction_cred',
      type: 'step',
      timestamp: '2026-10-07T12:25:43+00:00',
      content: 'Keychain access required',
      detail_kind: 'user_interaction',
      metadata: {
        user_interaction: { interaction_id: 'cred', kind: 'credential', status, prompt: 'Keychain access required' },
      },
    });

    store.handleWSEvent({ event_type: 'agent_task_step_detail', agent_task_id: 'task-1', timeline_entry: entry('waiting') });
    const waitingTimeline = store.getAgent('task-1')!.executionTimeline;
    store.handleWSEvent({ event_type: 'agent_task_step_detail', agent_task_id: 'task-1', timeline_entry: entry('approved') });

    const resolvedTimeline = store.getAgent('task-1')!.executionTimeline;
    expect(resolvedTimeline).not.toBe(waitingTimeline);
    expect(waitingTimeline[0].metadata?.user_interaction).toMatchObject({ status: 'waiting' });
    expect(resolvedTimeline).toHaveLength(1);
    expect(resolvedTimeline[0].metadata?.user_interaction).toMatchObject({ status: 'approved' });
  });

  it('stamps live reasoning passes and keeps a resumed run from overwriting earlier passes', () => {
    const store = makeStore();

    thinking(store, 1, 'Looking up the hotel', '2026-10-04T16:39:00', false);
    thinking(store, 1, 'Looking up the hotel name', '2026-10-04T16:39:05');
    thinking(store, 1, 'Searching shops near La Fantaisie', '2026-10-04T16:45:00');

    const segments = store.getAgent('task-1')!.thinkingSegments;
    expect(segments.map(segment => [segment.iteration, segment.text, segment.recordedAt])).toEqual([
      [1, 'Looking up the hotel name', '2026-10-04T16:39:00'],
      [2, 'Searching shops near La Fantaisie', '2026-10-04T16:45:00'],
    ]);
  });
});
