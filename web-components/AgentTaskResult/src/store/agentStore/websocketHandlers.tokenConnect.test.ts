import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';

function requestEvent(overrides: Partial<WSEvent> = {}): WSEvent {
  return {
    event_type: 'connection_secret_request',
    agent_task_id: 'task-1',
    request_id: 'req-1',
    server_url: 'https://huggingface.co/mcp',
    host: 'huggingface.co',
    friendly_name: 'Hugging Face',
    description: 'Write access for Basil model inventory',
    existing_names: ['Linear'],
    already_connected_as: null,
    ...overrides,
  };
}

describe('AgentStore token-connect overlay', () => {
  it('shows the overlay from a connection_secret_request and never stores a token', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.handleWSEvent(requestEvent({ token: 'hf_should_never_land' }));

    const agent = store.getAgent('task-1');
    expect(agent?.showTokenConnectPrompt).toBe(true);
    expect(agent?.status).toBe('awaitingInput');
    expect(agent?.tokenConnectRequest).toEqual({
      requestId: 'req-1',
      serverUrl: 'https://huggingface.co/mcp',
      host: 'huggingface.co',
      friendlyName: 'Hugging Face',
      description: 'Write access for Basil model inventory',
      existingNames: ['Linear'],
      alreadyConnectedAs: undefined,
    });
    expect(JSON.stringify(agent)).not.toContain('hf_should_never_land');
  });

  it('hides the overlay when the backend cancels the request', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.handleWSEvent(requestEvent());
    store.handleWSEvent({
      event_type: 'connection_secret_cancel',
      agent_task_id: 'task-1',
      request_id: 'req-1',
    });

    const agent = store.getAgent('task-1');
    expect(agent?.showTokenConnectPrompt).toBe(false);
    expect(agent?.tokenConnectRequest).toBeUndefined();
  });

  it('ignores a cancel for a different request', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.handleWSEvent(requestEvent());
    store.handleWSEvent({
      event_type: 'connection_secret_cancel',
      agent_task_id: 'task-1',
      request_id: 'other',
    });

    expect(store.getAgent('task-1')?.showTokenConnectPrompt).toBe(true);
    expect(store.getAgent('task-1')?.tokenConnectRequest?.requestId).toBe('req-1');
  });
});
