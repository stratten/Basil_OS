import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TodoItemSummary, WSEvent } from '../contracts';
import TodoWorkspacePane from './TodoWorkspacePane';

const wsMocks = vi.hoisted(() => ({
  basilBoardWebSocket: {
    subscribe: vi.fn(),
    sendTodoWorkspaceMessage: vi.fn(),
  },
}));

const apiMocks = vi.hoisted(() => ({
  getReasoningModels: vi.fn(),
}));

const bridgeMocks = vi.hoisted(() => ({
  pickTodoWorkspaceFiles: vi.fn(),
  registerTodoWorkspaceFilesPickedHandler: vi.fn(),
  setBoardFileDropTarget: vi.fn(),
  todoWorkspaceFilesPickedHandler: undefined as undefined | ((paths: string[]) => void),
}));

vi.mock('../services/websocket', () => wsMocks);
vi.mock('../services/api', () => apiMocks);
vi.mock('../services/bridge', () => ({
  pickTodoWorkspaceFiles: bridgeMocks.pickTodoWorkspaceFiles,
  registerTodoWorkspaceFilesPickedHandler: (handler: (paths: string[]) => void) => {
    bridgeMocks.todoWorkspaceFilesPickedHandler = handler;
    bridgeMocks.registerTodoWorkspaceFilesPickedHandler(handler);
    return () => {
      if (bridgeMocks.todoWorkspaceFilesPickedHandler === handler) {
        bridgeMocks.todoWorkspaceFilesPickedHandler = undefined;
      }
    };
  },
  setBoardFileDropTarget: bridgeMocks.setBoardFileDropTarget,
}));

function summary(overrides: Partial<TodoItemSummary> = {}): TodoItemSummary {
  return {
    id: 'todo-1', title: 'A selected item', status: 'open', responsibility: 'user', priority: 'normal',
    due_at: null, revision: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    attention: { needs_attention: false }, ...overrides,
  };
}

let latestHandler: ((event: WSEvent) => void) | null = null;
const unsubscribeSpy = vi.fn();

beforeEach(() => {
  wsMocks.basilBoardWebSocket.subscribe.mockReset();
  wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReset();
  bridgeMocks.pickTodoWorkspaceFiles.mockReset();
  bridgeMocks.registerTodoWorkspaceFilesPickedHandler.mockReset();
  bridgeMocks.setBoardFileDropTarget.mockReset();
  bridgeMocks.todoWorkspaceFilesPickedHandler = undefined;
  apiMocks.getReasoningModels.mockResolvedValue({
    current_model: 'model-default',
    models: [{
      id: 'model-default',
      name: 'Default model',
      display_name: 'Default model',
      provider: 'local',
      category: 'local',
    }],
  });
  unsubscribeSpy.mockReset();
  latestHandler = null;
  wsMocks.basilBoardWebSocket.subscribe.mockImplementation((handler: (event: WSEvent) => void) => {
    latestHandler = handler;
    return unsubscribeSpy;
  });
});

describe('TodoWorkspacePane intake and disabled states', () => {
  it('enables intake mode when nothing is selected but keeps an empty draft unsendable', () => {
    render(<TodoWorkspacePane selectedItems={[]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    expect(screen.getByText(/No To-Dos selected/i)).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' }).getAttribute('contenteditable')).toBe('true');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(screen.getByLabelText('Command-Return sends')).toBeInTheDocument();
  });

  it('shows a no-messages-yet placeholder before any turn is sent', () => {
    render(<TodoWorkspacePane selectedItems={[summary()]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);
    expect(screen.getByText(/No messages yet this session/i)).toBeInTheDocument();
  });

  it('loads the reasoning model selector for the To-Do agent', async () => {
    render(<TodoWorkspacePane selectedItems={[summary()]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Reasoning model' })).toHaveTextContent('Default model'));
  });

  it('subscribes exactly once on mount and unsubscribes on unmount', () => {
    const { unmount } = render(<TodoWorkspacePane selectedItems={[summary()]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);
    expect(wsMocks.basilBoardWebSocket.subscribe).toHaveBeenCalledTimes(1);
    unmount();
    expect(unsubscribeSpy).toHaveBeenCalledTimes(1);
  });

  it('starts expanded and preserves the workspace state while collapsed', async () => {
    render(<TodoWorkspacePane selectedItems={[summary()]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    const draft = screen.getByRole('textbox', { name: 'Message' });
    await userEvent.type(draft, 'Keep this unsent draft.');
    await userEvent.click(screen.getByRole('button', { name: 'Collapse To-Do workspace' }));
    expect(draft.closest('[hidden]')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Expand To-Do workspace' })).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(screen.getByRole('button', { name: 'Expand To-Do workspace' }));
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveTextContent('Keep this unsent draft.');
  });

  it('exposes a keyboard-resizable drag handle on its left edge, matching the chats artifact sidebar', () => {
    const { container } = render(<TodoWorkspacePane selectedItems={[summary()]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    const resizeHandle = container.querySelector<HTMLDivElement>('.todo-workspace-pane-resize-handle');
    expect(resizeHandle?.getAttribute('role')).toBe('separator');
    expect(resizeHandle?.getAttribute('aria-valuenow')).toBe('360');

    act(() => {
      resizeHandle?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    });

    expect(
      container.querySelector<HTMLElement>('.todo-workspace-pane')?.style.getPropertyValue('--todo-workspace-pane-width'),
    ).toBe('384px');
  });

  it('hides the resize handle while the workspace pane is collapsed', async () => {
    const { container } = render(<TodoWorkspacePane selectedItems={[summary()]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Collapse To-Do workspace' }));
    expect(container.querySelector('.todo-workspace-pane-resize-handle')).toBeNull();
  });
});

describe('TodoWorkspacePane sending a turn', () => {
  it('submits an intake request without a selected To-Do', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(true);
    render(<TodoWorkspacePane selectedItems={[]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'Create candidates from this brief.');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Create candidates from this brief.',
        selectedTodoIds: [],
        referencePaths: [],
      }),
    );
  });

  it('deduplicates attached paths, supports removal, and submits retained paths', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(true);
    render(<TodoWorkspacePane selectedItems={[summary({ id: 't1' })]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    bridgeMocks.todoWorkspaceFilesPickedHandler?.(['/tmp/action-items.pdf', '/tmp/action-items.pdf']);
    expect(await screen.findByText('action-items.pdf')).toBeInTheDocument();
    expect(screen.getAllByText('action-items.pdf')).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: 'Remove action-items.pdf' }));
    expect(screen.queryByText('action-items.pdf')).not.toBeInTheDocument();

    bridgeMocks.todoWorkspaceFilesPickedHandler?.(['/tmp/action-items.pdf']);
    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'Create candidates from the attachment.');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        selectedTodoIds: ['t1'],
        referencePaths: ['/tmp/action-items.pdf'],
      }),
    );
  });

  it('sends a message with the selected item ids and shows a working indicator', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(true);
    render(<TodoWorkspacePane selectedItems={[summary({ id: 't1' }), summary({ id: 't2' })]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'What is the status?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'What is the status?',
        selectedTodoIds: ['t1', 't2'],
        modelId: 'model-default',
      }),
    );
    expect(screen.getByText('Working')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled(); // busy while pending
  });

  it('shows a "not connected" error and does not enter a busy state when send fails locally', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(false);
    render(<TodoWorkspacePane selectedItems={[summary()]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'hi');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(screen.getByText('Not connected to Basil.')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Send' })).not.toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Message' }).textContent).toBe('hi');
  });

  it('renders the assistant reply and calls onWorkerOrManagerResultSettled when a matching result event arrives', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(true);
    const onSettled = vi.fn();
    render(<TodoWorkspacePane selectedItems={[summary({ id: 't1' })]} onWorkerOrManagerResultSettled={onSettled} onDeselectItem={vi.fn()} />);

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'What is the status?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const sentMessage = wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[0][0] as {
      requestId: string; workspaceId: string;
    };

    latestHandler?.({
      event_type: 'todo_workspace_result', workspace_id: sentMessage.workspaceId,
      request_id: sentMessage.requestId, agent_task_id: 'task-1', status: 'completed',
      summary: 'The To-Do is still open.', selected_todo_ids: ['t1'],
    } as unknown as WSEvent);

    await waitFor(() => expect(screen.getByText('The To-Do is still open.')).toBeInTheDocument());
    expect(onSettled).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Working')).not.toBeInTheDocument();
  });

  it('renders an error transcript entry on a todo_workspace_error event and does not call onWorkerOrManagerResultSettled', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(true);
    const onSettled = vi.fn();
    render(<TodoWorkspacePane selectedItems={[summary({ id: 't1' })]} onWorkerOrManagerResultSettled={onSettled} onDeselectItem={vi.fn()} />);

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'delegate this');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const sentRequestId = (wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[0][0] as { requestId: string; workspaceId: string });

    latestHandler?.({
      event_type: 'todo_workspace_error', workspace_id: sentRequestId.workspaceId, request_id: sentRequestId.requestId,
      message: 'selected_todo_ids must contain 1 to 100 unique nonblank ids',
    } as unknown as WSEvent);

    await waitFor(() =>
      expect(screen.getByText('selected_todo_ids must contain 1 to 100 unique nonblank ids')).toBeInTheDocument(),
    );
    expect(onSettled).not.toHaveBeenCalled();
  });

  it('"New conversation" clears the transcript and starts a fresh workspace id', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(true);
    render(<TodoWorkspacePane selectedItems={[summary({ id: 't1' })]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'first message');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const firstWorkspaceId = (wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[0][0] as { workspaceId: string }).workspaceId;
    latestHandler?.({
      event_type: 'todo_workspace_result', workspace_id: firstWorkspaceId,
      request_id: (wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[0][0] as { requestId: string }).requestId,
      agent_task_id: 'task-1', status: 'completed', summary: 'First reply', selected_todo_ids: ['t1'],
    } as unknown as WSEvent);
    await waitFor(() => expect(screen.getByText('First reply')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'New conversation' }));

    expect(screen.queryByText('First reply')).not.toBeInTheDocument();
    expect(screen.getByText(/No messages yet this session/i)).toBeInTheDocument();

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'second message');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const secondWorkspaceId = (wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[1][0] as { workspaceId: string }).workspaceId;
    expect(secondWorkspaceId).not.toBe(firstWorkspaceId);
  });

  it('"New conversation" clears unsent attachments and draft context', async () => {
    render(<TodoWorkspacePane selectedItems={[summary({ id: 't1' })]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);

    bridgeMocks.todoWorkspaceFilesPickedHandler?.(['/tmp/action-items.pdf']);
    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'Keep this only until the reset.');
    await userEvent.click(screen.getByRole('button', { name: 'New conversation' }));

    expect(screen.queryByText('action-items.pdf')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' }).textContent).toBe('');
  });

  it('"Clear" empties the transcript without changing the workspace id', async () => {
    wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mockReturnValue(true);
    render(<TodoWorkspacePane selectedItems={[summary({ id: 't1' })]} onWorkerOrManagerResultSettled={vi.fn()} onDeselectItem={vi.fn()} />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'first message');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const workspaceId = (wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[0][0] as { workspaceId: string }).workspaceId;
    latestHandler?.({
      event_type: 'todo_workspace_result', workspace_id: workspaceId,
      request_id: (wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[0][0] as { requestId: string }).requestId,
      agent_task_id: 'task-1', status: 'completed', summary: 'A reply', selected_todo_ids: ['t1'],
    } as unknown as WSEvent);
    await waitFor(() => expect(screen.getByText('A reply')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));

    expect(screen.queryByText('A reply')).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'after clear');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect((wsMocks.basilBoardWebSocket.sendTodoWorkspaceMessage.mock.calls[1][0] as { workspaceId: string }).workspaceId).toBe(workspaceId);
  });
});

describe('TodoWorkspacePane selection chips', () => {
  it('renders one chip per selected item and deselects on remove', async () => {
    const onDeselectItem = vi.fn();
    render(
      <TodoWorkspacePane
        selectedItems={[
          summary({ id: 't1', title: 'First selected' }),
          summary({ id: 't2', title: 'Second selected', status: 'in_progress' }),
        ]}
        onWorkerOrManagerResultSettled={vi.fn()}
        onDeselectItem={onDeselectItem}
      />,
    );

    expect(screen.getByRole('list', { name: 'Selected To-Dos' })).toBeInTheDocument();
    expect(screen.getByText('First selected')).toBeInTheDocument();
    expect(screen.getByText('Second selected')).toBeInTheDocument();
    expect(screen.getByText('in progress')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Remove First selected from the workspace' }));
    expect(onDeselectItem).toHaveBeenCalledWith('t1');
  });
});
