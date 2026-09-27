import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';

function makeStoreWithAgent(agentTaskId = 'task-1') {
  const store = new AgentStore();
  store.registerAgent(agentTaskId);
  return store;
}

function dispatch(store: AgentStore, event: WSEvent) {
  store.handleWSEvent(event);
}

describe('AgentStore blocker handling', () => {
  it('records conversation provenance from the creation-time event before progress arrives', () => {
    const store = new AgentStore();

    dispatch(store, {
      event_type: 'agent_task_origin',
      agent_task_id: 'task-origin-1',
      origin_type: 'conversation',
      origin_id: 'conversation-1',
    });

    const agent = store.getAgent('task-origin-1');
    expect(agent?.originType).toBe('conversation');
    expect(agent?.originId).toBe('conversation-1');
  });

  it('keeps background external-service access processing and preserves the active step', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'agent_progress_update',
      agent_task_id: 'task-1',
      message: 'Executing Linear tool schema',
    });
    dispatch(store, {
      event_type: 'agent_task_blocker_waiting',
      agent_task_id: 'task-1',
      kind: 'external_service_token',
      connection_id: 'conn-1',
    });
    dispatch(store, {
      event_type: 'agent_task_blocker_resolved',
      agent_task_id: 'task-1',
      kind: 'token_available',
      connection_id: 'conn-1',
    });

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentStep).toBe('Executing Linear tool schema');
    expect(agent?.currentStep).not.toBe('Waiting for access...');
    expect(agent?.stepDetails[agent.stepDetails.length - 1]?.metadata).toMatchObject({ status: 'completed' });
  });

  it('uses awaiting input only while a native Keychain prompt needs attention', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'agent_task_blocker_waiting',
      agent_task_id: 'task-1',
      kind: 'external_service_token',
      connection_id: 'conn-1',
      user_action_required: true,
    });

    let agent = store.getAgent('task-1');
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentStep).toBe('Keychain access required');

    dispatch(store, {
      event_type: 'agent_task_blocker_resolved',
      agent_task_id: 'task-1',
      kind: 'token_available',
      connection_id: 'conn-1',
    });

    agent = store.getAgent('task-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentStep).toBe('External service access ready. Continuing...');
  });

  it('keeps real checkpoint prompts as Basil input prompts', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'collaborative_checkpoint_request',
      agent_task_id: 'task-1',
      checkpoint: {
        checkpoint_id: 'checkpoint-1',
        prompt: 'Choose a path',
        input_type: 'choice',
        options: ['Path A', 'Path B'],
      },
    });

    let agent = store.getAgent('task-1');
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.showCheckpointPrompt).toBe(true);
    expect(agent?.currentCheckpoint?.input_type).toBe('choice');

    dispatch(store, {
      event_type: 'checkpoint_resumed',
      agent_task_id: 'task-1',
      message: 'Resumed',
    });

    agent = store.getAgent('task-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentCheckpoint).toBeUndefined();
  });

  it('keeps a checkpoint waiting until real execution progress clears its prompt', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'collaborative_checkpoint_request',
      agent_task_id: 'task-1',
      checkpoint: {
        checkpoint_id: 'checkpoint-1',
        prompt: 'Choose a path',
        input_type: 'choice',
        options: ['Path A', 'Path B'],
      },
    });
    dispatch(store, {
      event_type: 'checkpoint_waiting',
      agent_task_id: 'task-1',
      message: 'Waiting for your input...',
    });

    let agent = store.getAgent('task-1');
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.showCheckpointPrompt).toBe(true);

    dispatch(store, {
      event_type: 'agent_task_streaming',
      agent_task_id: 'task-1',
      partial_result: 'Continuing with Path A.',
    });

    agent = store.getAgent('task-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentCheckpoint).toBeUndefined();
    expect(agent?.inlineCheckpoint).toBeUndefined();
  });

  it('surfaces failed external-service access as an error detail', () => {
    const store = makeStoreWithAgent();

    dispatch(store, {
      event_type: 'agent_task_blocker_resolved',
      agent_task_id: 'task-1',
      kind: 'token_missing',
      connection_id: 'conn-1',
      message: 'Basil could not read this token.',
    });

    const agent = store.getAgent('task-1');
    const detail = agent?.stepDetails[agent.stepDetails.length - 1];
    expect(detail?.detail_kind).toBe('error');
    expect(detail?.summary).toBe('External service access unavailable');
    expect(detail?.metadata).toMatchObject({ status: 'failed' });
  });
});
