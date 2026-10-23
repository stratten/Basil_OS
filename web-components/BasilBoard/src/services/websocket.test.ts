import { describe, expect, it, vi } from 'vitest';
import { WebSocketManager } from './websocket';

function attachFakeOpenSocket(manager: WebSocketManager) {
  const send = vi.fn();
  const fakeSocket = { readyState: 1 /* WebSocket.OPEN */, send };
  (manager as unknown as { ws: unknown }).ws = fakeSocket;
  return { send };
}

describe('WebSocketManager.sendTodoWorkspaceMessage', () => {
  it('returns false and sends nothing when not connected', () => {
    const manager = new WebSocketManager();
    const result = manager.sendTodoWorkspaceMessage({
      workspaceId: 'ws-1', requestId: 'req-1', message: 'hi', selectedTodoIds: ['t1'], referencePaths: [], transcript: [],
    });
    expect(result).toBe(false);
  });

  it('sends a todo_workspace_message frame with snake_case fields when connected', () => {
    const manager = new WebSocketManager();
    const { send } = attachFakeOpenSocket(manager);

    const result = manager.sendTodoWorkspaceMessage({
      workspaceId: 'ws-1', requestId: 'req-1', message: 'What is the status?',
      selectedTodoIds: ['t1', 't2'], referencePaths: ['/tmp/action-items.pdf'],
      transcript: [{ role: 'user', content: 'earlier message' }],
      modelId: 'model-a',
    });

    expect(result).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(send.mock.calls[0][0] as string);
    expect(sent).toEqual({
      type: 'todo_workspace_message', workspace_id: 'ws-1', request_id: 'req-1',
      message: 'What is the status?', selected_todo_ids: ['t1', 't2'],
      reference_paths: ['/tmp/action-items.pdf'],
      transcript: [{ role: 'user', content: 'earlier message' }], model_id: 'model-a',
    });
  });

  it('defaults model_id to null when not provided', () => {
    const manager = new WebSocketManager();
    const { send } = attachFakeOpenSocket(manager);

    manager.sendTodoWorkspaceMessage({
      workspaceId: 'ws-1', requestId: 'req-1', message: 'hi', selectedTodoIds: ['t1'], referencePaths: [], transcript: [],
    });

    const sent = JSON.parse(send.mock.calls[0][0] as string);
    expect(sent.model_id).toBeNull();
  });

  it('returns false when the underlying send throws', () => {
    const manager = new WebSocketManager();
    const fakeSocket = {
      readyState: 1,
      send: () => {
        throw new Error('socket closed mid-send');
      },
    };
    (manager as unknown as { ws: unknown }).ws = fakeSocket;

    const result = manager.sendTodoWorkspaceMessage({
      workspaceId: 'ws-1', requestId: 'req-1', message: 'hi', selectedTodoIds: ['t1'], referencePaths: [], transcript: [],
    });

    expect(result).toBe(false);
  });
});
