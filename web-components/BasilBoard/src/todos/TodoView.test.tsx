import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TodoItemDetail, TodoItemSummary } from '../contracts';
import TodoView from './TodoView';

const apiMocks = vi.hoisted(() => ({
  hydrateTodoWorkspace: vi.fn(),
  getTodoAgentStatuses: vi.fn().mockResolvedValue({}),
  getTodoItem: vi.fn(),
  addTodoReference: vi.fn(),
  removeTodoReference: vi.fn(),
  acceptTodoCandidate: vi.fn(),
  dismissTodoCandidate: vi.fn(),
  completeTodoItem: vi.fn(),
  createTodoItem: vi.fn(),
  deleteTodoItem: vi.fn(),
  reopenTodoItem: vi.fn(),
  cancelTodoItem: vi.fn(),
  replaceTodoNotes: vi.fn(),
  launchTodoWorker: vi.fn(),
  updateTodoItem: vi.fn(),
}));
const bridgeMocks = vi.hoisted(() => ({
  pickTodoReferenceFiles: vi.fn(),
  registerTodoReferenceFilesPickedHandler: vi.fn(),
  openExistingAgentTaskWidget: vi.fn(),
}));
vi.mock('../services/api', () => apiMocks);
vi.mock('../services/bridge', () => bridgeMocks);
vi.mock('./TodoWorkspacePane', () => ({
  default: ({
    focusRequest,
    selectedItems,
  }: {
    focusRequest?: { originType: string };
    selectedItems?: Array<{ id: string }>;
  }) => (
    <div
      data-testid="workspace-pane-stub"
      data-focused={focusRequest?.originType === 'todo_workspace'}
      data-selected-count={String(selectedItems?.length ?? 0)}
    />
  ),
}));

function summary(overrides: Partial<TodoItemSummary> = {}): TodoItemSummary {
  return {
    id: 'todo-1', title: 'Draft the follow-up', status: 'open', responsibility: 'user', priority: 'normal',
    due_at: null, revision: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    attention: { needs_attention: false }, ...overrides,
  };
}

function detail(overrides: Partial<TodoItemDetail> = {}): TodoItemDetail {
  return {
    ...summary(overrides),
    description: 'Some description', notes: 'Some notes', idempotency_key: null, created_by_kind: 'user',
    created_by_id: null, sources: [], references: [], worker_attempts: [], ...overrides,
  };
}

beforeEach(() => {
  Object.values(apiMocks).forEach((mockFn) => mockFn.mockReset());
  bridgeMocks.pickTodoReferenceFiles.mockReset();
  bridgeMocks.registerTodoReferenceFilesPickedHandler.mockReset();
  bridgeMocks.openExistingAgentTaskWidget.mockReset();
  bridgeMocks.registerTodoReferenceFilesPickedHandler.mockReturnValue(() => {});
  apiMocks.hydrateTodoWorkspace.mockResolvedValue({ items: [], next_cursor: null, counts_by_status: {} });
  apiMocks.createTodoItem.mockResolvedValue(detail());
  apiMocks.getTodoAgentStatuses.mockResolvedValue({});
});

describe('TodoView loading and empty states', () => {
  it('shows a loading indicator while hydrating', async () => {
    let resolveHydration: (value: unknown) => void = () => {};
    apiMocks.hydrateTodoWorkspace.mockReturnValue(new Promise((resolve) => { resolveHydration = resolve; }));

    render(<TodoView />);

    expect(screen.getByText(/Loading To-Dos/i)).toBeInTheDocument();
    resolveHydration({ items: [], next_cursor: null, counts_by_status: {} });
    await waitFor(() => expect(screen.queryByText(/Loading To-Dos/i)).not.toBeInTheDocument());
  });

  it('shows an empty-state message once loaded with no items', async () => {
    render(<TodoView />);
    await waitFor(() => expect(screen.getByText(/No To-Dos in this view yet/i)).toBeInTheDocument());
  });

  it('shows an error message when hydration fails', async () => {
    apiMocks.hydrateTodoWorkspace.mockRejectedValue(new Error('backend unavailable'));
    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('backend unavailable')).toBeInTheDocument());
  });

  it('retries the first page after an initial loading failure', async () => {
    apiMocks.hydrateTodoWorkspace
      .mockRejectedValueOnce(new Error('backend unavailable'))
      .mockResolvedValueOnce({ items: [summary({ title: 'Recovered item' })], next_cursor: null, has_more: false, counts_by_status: {} });

    render(<TodoView />);

    await userEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Recovered item')).toBeInTheDocument();
  });
});

describe('TodoView list and selection', () => {
  it('renders the candidate list under the default open filter after hydration', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Open one', status: 'open' }), summary({ id: 't2', title: 'Done one', status: 'completed' })],
      next_cursor: null, counts_by_status: { open: 1, completed: 1 },
    });

    render(<TodoView />);

    await waitFor(() => expect(screen.getByText('Open one')).toBeInTheDocument());
    expect(screen.queryByText('Done one')).not.toBeInTheDocument(); // filtered out by default 'open' filter
  });

  it('shows every status when the All filter is selected', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [
        summary({ id: 't1', title: 'Open one', status: 'open' }),
        summary({ id: 't2', title: 'Done one', status: 'completed' }),
      ],
      next_cursor: null,
      counts_by_status: { open: 1, completed: 1 },
    });

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Open one')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: 'All' }));

    expect(screen.getByText('Done one')).toBeInTheDocument();
  });

  it('shows creation metadata and reloads the list when sorting changes', async () => {
    const createdItem = summary({ id: 't1', title: 'Created item', created_at: '2026-01-01T00:00:00Z' });
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [createdItem],
      next_cursor: null,
      counts_by_status: { open: 1 },
    });
    apiMocks.getTodoItem.mockResolvedValue(detail(createdItem));

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Created item')).toBeInTheDocument());
    expect(document.querySelector('.todo-list-item-meta')?.textContent).toContain('Created ');
    expect(apiMocks.hydrateTodoWorkspace).toHaveBeenCalledWith(
      { column: 'created_at' },
      { query: undefined, statuses: ['open', 'in_progress', 'ready_for_review'], limit: 50 },
    );
    await userEvent.click(screen.getByRole('button', { name: 'Created item' }));
    expect(await screen.findByRole('heading', { name: 'Created date' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Choose the To-Do sort column' }));
    await userEvent.click(screen.getByRole('option', { name: 'Last updated' }));
    await waitFor(() => expect(apiMocks.hydrateTodoWorkspace).toHaveBeenLastCalledWith(
      { column: 'updated_at', direction: undefined },
      { query: undefined, statuses: ['open', 'in_progress', 'ready_for_review'], limit: 50 },
    ));
  });

  it('shows a status indicator for a To-Do with an in-progress Agent Task, and none for a To-Do without one', async () => {
    const withAgent = summary({
      id: 't-with-agent', title: 'Has an agent task',
      agent_status: { agent_task_id: 'a1', status: 'processing', result_severity: null, is_active: true, updated_at: '2026-01-01T00:00:00Z' },
    });
    const withoutAgent = summary({ id: 't-without-agent', title: 'No agent task yet' });
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [withAgent, withoutAgent],
      next_cursor: null,
      counts_by_status: { open: 2 },
    });

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Has an agent task')).toBeInTheDocument());

    expect(document.querySelector('.todo-list-item-agent-status')).toBeInTheDocument();
    const rows = document.querySelectorAll('.todo-list-item');
    const rowWithoutAgent = Array.from(rows).find((row) => row.textContent?.includes('No agent task yet'));
    expect(rowWithoutAgent?.querySelector('.todo-list-item-agent-status')).toBeNull();
  });

  it('renders canceled To-Dos with American-English copy', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Canceled item', status: 'canceled' })],
      next_cursor: null,
      counts_by_status: { canceled: 1 },
    });

    render(<TodoView />);
    await userEvent.click(screen.getByRole('tab', { name: 'All' }));
    expect(await screen.findByText('Canceled')).toBeInTheDocument();
    expect(screen.queryByText('canceled')).not.toBeInTheDocument();
  });

  it('clicking a title views the item without adding it to the workspace selection', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Selectable item' })], next_cursor: null, counts_by_status: {},
    });
    apiMocks.getTodoItem.mockResolvedValue(detail({ id: 't1', title: 'Selectable item' }));

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Selectable item')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Selectable item' }));

    await waitFor(() => expect(apiMocks.getTodoItem).toHaveBeenCalledWith('t1'));
    await waitFor(() => expect(screen.getByText('Some description')).toBeInTheDocument());
    expect(screen.getByTestId('workspace-pane-stub')).toHaveAttribute('data-selected-count', '0');
  });

  it('selecting a checkbox adds the item to the workspace without viewing it', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Selectable item' })], next_cursor: null, counts_by_status: {},
    });

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Selectable item')).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText(/Select Selectable item for the workspace/i));

    expect(screen.getByTestId('workspace-pane-stub')).toHaveAttribute('data-selected-count', '1');
    expect(apiMocks.getTodoItem).not.toHaveBeenCalled();
    expect(screen.getByText('Select a To-Do to see its details.')).toBeInTheDocument();
  });

  it('does not let a stale detail response overwrite the more recently viewed To-Do', async () => {
    let resolveFirst: (item: TodoItemDetail) => void = () => {};
    let resolveSecond: (item: TodoItemDetail) => void = () => {};
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [
        summary({ id: 't1', title: 'First item' }),
        summary({ id: 't2', title: 'Second item' }),
      ],
      next_cursor: null,
      counts_by_status: {},
    });
    apiMocks.getTodoItem
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('First item')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'First item' }));
    await userEvent.click(screen.getByRole('button', { name: 'Second item' }));

    resolveSecond(detail({ id: 't2', title: 'Second item', description: 'Second detail' }));
    await waitFor(() => expect(screen.getByText('Second detail')).toBeInTheDocument());
    resolveFirst(detail({ id: 't1', title: 'First item', description: 'First detail' }));

    await waitFor(() => expect(screen.queryByText('First detail')).not.toBeInTheDocument());
    expect(screen.getByText('Second detail')).toBeInTheDocument();
  });

  it('selects and hydrates the exact To-Do referenced by an Agent Task origin', async () => {
    apiMocks.getTodoItem.mockResolvedValue(detail({
      id: 'linked-todo',
      title: 'Linked To-Do',
      status: 'completed',
    }));

    render(<TodoView originNavigation={{ originType: 'todo', originId: 'linked-todo' }} />);

    await waitFor(() => expect(apiMocks.getTodoItem).toHaveBeenCalledWith('linked-todo'));
    expect((await screen.findAllByText('Linked To-Do')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Some description')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-pane-stub')).toHaveAttribute('data-selected-count', '0');
  });

  it('shows a deterministic error when the referenced To-Do is missing', async () => {
    apiMocks.getTodoItem.mockRejectedValue(new Error('not found'));

    render(<TodoView originNavigation={{ originType: 'todo', originId: 'missing-todo' }} />);

    expect(await screen.findByText('The referenced To-Do could not be found.')).toBeInTheDocument();
  });

  it('focuses the workspace for a To-Do workspace origin', async () => {
    render(<TodoView originNavigation={{ originType: 'todo_workspace', originId: 'workspace-1' }} />);

    await waitFor(() => expect(screen.getByTestId('workspace-pane-stub')).toHaveAttribute('data-focused', 'true'));
  });
});

describe('TodoView query and pagination', () => {
  it('searches titles through the paginated workspace endpoint', async () => {
    apiMocks.hydrateTodoWorkspace
      .mockResolvedValueOnce({ items: [summary({ title: 'Initial item' })], next_cursor: null, has_more: false, counts_by_status: {} })
      .mockResolvedValueOnce({ items: [summary({ title: 'Review budget' })], next_cursor: null, has_more: false, counts_by_status: {} });

    render(<TodoView />);
    await screen.findByText('Initial item');
    await userEvent.type(screen.getByLabelText('Search To-Dos'), 'ReViEw');

    await waitFor(() => expect(apiMocks.hydrateTodoWorkspace).toHaveBeenLastCalledWith(
      { column: 'created_at' },
      { query: 'ReViEw', statuses: ['open', 'in_progress', 'ready_for_review'], limit: 50 },
    ));
    expect(await screen.findByText('Review budget')).toBeInTheDocument();
  });

  it('loads a cursor page and keeps rows from the first page', async () => {
    apiMocks.hydrateTodoWorkspace
      .mockResolvedValueOnce({
        items: [summary({ id: 'first-page', title: 'First page item' })],
        next_cursor: 'next-page',
        has_more: true,
        counts_by_status: { open: 2 },
      })
      .mockResolvedValueOnce({
        items: [summary({ id: 'second-page', title: 'Second page item' })],
        next_cursor: null,
        has_more: false,
        counts_by_status: { open: 2 },
      });

    render(<TodoView />);

    await userEvent.click(await screen.findByRole('button', { name: 'Load more To-Dos' }));
    await waitFor(() => expect(apiMocks.hydrateTodoWorkspace).toHaveBeenLastCalledWith(
      { column: 'created_at' },
      {
        query: undefined,
        statuses: ['open', 'in_progress', 'ready_for_review'],
        limit: 50,
        cursor: 'next-page',
      },
    ));
    expect(await screen.findByText('First page item')).toBeInTheDocument();
    expect(screen.getByText('Second page item')).toBeInTheDocument();
  });

  it('shows a retry control when loading another page fails', async () => {
    apiMocks.hydrateTodoWorkspace
      .mockResolvedValueOnce({
        items: [summary({ id: 'first-page', title: 'First page item' })],
        next_cursor: 'next-page',
        has_more: true,
        counts_by_status: { open: 2 },
      })
      .mockRejectedValueOnce(new Error('page unavailable'))
      .mockResolvedValueOnce({
        items: [summary({ id: 'second-page', title: 'Second page item' })],
        next_cursor: null,
        has_more: false,
        counts_by_status: { open: 2 },
      });

    render(<TodoView />);

    await userEvent.click(await screen.findByRole('button', { name: 'Load more To-Dos' }));
    expect(await screen.findByText('page unavailable')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Second page item')).toBeInTheDocument();
  });
});

describe('TodoView manual creation', () => {
  it('creates an open To-Do with a client idempotency key and selects it', async () => {
    const created = detail({ id: 'manual-1', title: 'Manual item' });
    apiMocks.createTodoItem.mockResolvedValue(created);
    apiMocks.getTodoItem.mockResolvedValue(created);
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [created], next_cursor: null, counts_by_status: { open: 1 },
    });

    render(<TodoView />);
    await userEvent.click(screen.getByRole('button', { name: 'New To-Do' }));
    await userEvent.type(screen.getByLabelText('New To-Do title'), 'Manual item');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(apiMocks.createTodoItem).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Manual item', idempotency_key: expect.any(String) }),
    ));
    await waitFor(() => expect(screen.getByText('Some description')).toBeInTheDocument());
  });
});

describe('TodoView conflict handling', () => {
  async function selectItem(): Promise<void> {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Conflict target' })], next_cursor: null, counts_by_status: {},
    });
    apiMocks.getTodoItem.mockResolvedValue(detail({ id: 't1', title: 'Conflict target', revision: 1 }));
    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Conflict target')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Conflict target' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument());
  }

  it('shows a conflict message and offers a refresh action on a 409', async () => {
    await selectItem();
    apiMocks.completeTodoItem.mockRejectedValue(new Error('Conflict on To-Do t1'));

    await userEvent.click(screen.getByRole('button', { name: 'Mark complete' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Conflict on To-Do t1'));
  });

  it('refresh-after-conflict re-fetches the item and clears the conflict banner', async () => {
    await selectItem();
    apiMocks.completeTodoItem.mockRejectedValue(new Error('Conflict on To-Do t1'));
    await userEvent.click(screen.getByRole('button', { name: 'Mark complete' }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());

    apiMocks.getTodoItem.mockResolvedValue(detail({ id: 't1', title: 'Conflict target', revision: 2, status: 'completed' }));
    await userEvent.click(screen.getByRole('button', { name: 'Refresh latest' }));

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('a successful action clears any prior conflict and refreshes the list', async () => {
    await selectItem();
    apiMocks.completeTodoItem.mockRejectedValueOnce(new Error('Conflict on To-Do t1'));
    await userEvent.click(screen.getByRole('button', { name: 'Mark complete' }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());

    apiMocks.completeTodoItem.mockResolvedValueOnce(
      detail({ id: 't1', title: 'Conflict target', revision: 2, status: 'completed' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Mark complete' }));

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(apiMocks.hydrateTodoWorkspace).toHaveBeenCalledTimes(2); // initial load + post-success refresh
  });
});

describe('TodoView launch-worker action', () => {
  it('clicking "Start agent on this" keeps the Agent Task surface closed and applies the returned item', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Launchable item' })], next_cursor: null, counts_by_status: {},
    });
    apiMocks.getTodoItem.mockResolvedValue(detail({ id: 't1', title: 'Launchable item', revision: 1, status: 'open' }));
    apiMocks.launchTodoWorker.mockResolvedValue({
      item: detail({ id: 't1', title: 'Launchable item', revision: 2, status: 'in_progress' }),
      agent_task_id: 'worker-1',
    });

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Launchable item')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Launchable item' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Start agent on this' })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Start agent on this' }));

    await waitFor(() => expect(apiMocks.launchTodoWorker).toHaveBeenCalledWith('t1', 1));
    expect(bridgeMocks.openExistingAgentTaskWidget).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Open in Paprika' }));
    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenCalledWith('worker-1');
  });
});

describe('TodoView deletion', () => {
  async function selectDeletableItem(): Promise<void> {
    const item = detail({ id: 'delete-1', title: 'Delete target', revision: 3 });
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [item],
      next_cursor: null,
      counts_by_status: { open: 1 },
    });
    apiMocks.getTodoItem.mockResolvedValue(item);
    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Delete target')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Delete target' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete To-Do' })).toBeInTheDocument());
  }

  it('requires explicit confirmation before permanently deleting and clears the selected detail', async () => {
    await selectDeletableItem();
    apiMocks.deleteTodoItem.mockResolvedValue({ id: 'delete-1' });
    apiMocks.hydrateTodoWorkspace.mockResolvedValueOnce({
      items: [],
      next_cursor: null,
      counts_by_status: {},
    });

    await userEvent.click(screen.getByRole('button', { name: 'Delete To-Do' }));
    expect(apiMocks.deleteTodoItem).not.toHaveBeenCalled();
    expect(screen.getByText(/provenance, attachments, and work history/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Delete permanently' }));
    await waitFor(() => expect(apiMocks.deleteTodoItem).toHaveBeenCalledWith('delete-1', 3));
    await waitFor(() => expect(screen.getByText('Select a To-Do to see its details.')).toBeInTheDocument());
    expect(screen.queryByText('Delete target')).not.toBeInTheDocument();
  });

  it('keeps the detail visible when deletion is rejected', async () => {
    await selectDeletableItem();
    apiMocks.deleteTodoItem.mockRejectedValue(new Error('Cannot delete while a directly sourced Agent Task is active.'));

    await userEvent.click(screen.getByRole('button', { name: 'Delete To-Do' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete permanently' }));

    expect(await screen.findByText('Cannot delete while a directly sourced Agent Task is active.')).toBeInTheDocument();
    expect(screen.getAllByText('Delete target')).toHaveLength(2);
  });

  it('requires confirmation from the sidebar reveal and preserves its error state on a stale delete', async () => {
    const item = summary({ id: 'sidebar-delete', title: 'Sidebar delete target', revision: 7 });
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [item],
      next_cursor: null,
      counts_by_status: { open: 1 },
    });
    apiMocks.deleteTodoItem.mockRejectedValue(new Error('That To-Do has changed. Refresh before deleting it.'));

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Sidebar delete target')).toBeInTheDocument());
    fireEvent.wheel(document.querySelector('.todo-list-item')!, { deltaX: 80, deltaY: 0 });
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(screen.getByText(/provenance, attachments, and work history/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Delete permanently' }));

    await waitFor(() => expect(apiMocks.deleteTodoItem).toHaveBeenCalledWith('sidebar-delete', 7));
    expect(screen.getByText('That To-Do has changed. Refresh before deleting it.')).toBeInTheDocument();
    expect(screen.getByText('Sidebar delete target')).toBeInTheDocument();
  });
});

describe('TodoView due date', () => {
  it('marks a past-due open To-Do in the list', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Overdue item', due_at: '2000-01-01T00:00:00.000Z' })],
      next_cursor: null,
      counts_by_status: { open: 1 },
    });

    render(<TodoView />);

    await waitFor(() => expect(screen.getByText('Overdue item')).toBeInTheDocument());
    expect(screen.getByText(/^Due /)).toHaveClass('todo-list-item-due--overdue');
  });

  it('saves a due date through updateTodoItem with the current revision', async () => {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [summary({ id: 't1', title: 'Dated item' })], next_cursor: null, counts_by_status: {},
    });
    apiMocks.getTodoItem.mockResolvedValue(detail({ id: 't1', title: 'Dated item', revision: 1 }));
    apiMocks.updateTodoItem.mockResolvedValue(detail({
      id: 't1', title: 'Dated item', revision: 2, due_at: '2026-08-20T00:00:00.000Z',
    }));

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Dated item')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Dated item' }));
    expect(screen.queryByLabelText('Due date')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add due date' }));
    await waitFor(() => expect(screen.getByLabelText('Due date')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-08-20' } });

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1',
      expect.objectContaining({ expected_revision: 1, due_at: '2026-08-20T00:00:00.000Z' }),
    ));
  });

  it('clears a due date through updateTodoItem with null', async () => {
    const datedItem = detail({
      id: 't1',
      title: 'Dated item',
      revision: 1,
      due_at: '2026-08-20T00:00:00.000Z',
    });
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [datedItem],
      next_cursor: null,
      counts_by_status: { open: 1 },
    });
    apiMocks.getTodoItem.mockResolvedValue(datedItem);
    apiMocks.updateTodoItem.mockResolvedValue(detail({ id: 't1', title: 'Dated item', revision: 2, due_at: null }));

    render(<TodoView />);
    await waitFor(() => expect(screen.getByText('Dated item')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Dated item' }));
    await userEvent.click(screen.getByRole('button', { name: new Date(datedItem.due_at!).toLocaleDateString() }));
    await waitFor(() => expect(screen.getByLabelText('Due date')).toHaveValue('2026-08-20'));

    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1',
      expect.objectContaining({ expected_revision: 1, due_at: null }),
    ));
  });
});

describe('TodoView completed date', () => {
  it('renders, edits, and clears a completed date', async () => {
    const completed = detail({
      id: 't1',
      title: 'Completed item',
      status: 'completed',
      revision: 1,
      completed_at: '2025-12-24T09:30:00Z',
    });
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [completed], next_cursor: null, counts_by_status: { completed: 1 },
    });
    apiMocks.getTodoItem.mockResolvedValue(completed);
    apiMocks.updateTodoItem
      .mockResolvedValueOnce(detail({ ...completed, revision: 2, completed_at: '2025-12-25T00:00:00.000Z' }))
      .mockResolvedValueOnce(detail({ ...completed, revision: 3, completed_at: null }));

    render(<TodoView />);
    await userEvent.click(screen.getByRole('tab', { name: 'All' }));
    await waitFor(() => expect(screen.getByText('Completed item')).toBeInTheDocument());
    expect(screen.getByText(`Completed ${new Date(completed.completed_at!).toLocaleDateString()}`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Completed item' }));
    await userEvent.click(screen.getByRole('button', { name: new Date(completed.completed_at!).toLocaleDateString() }));
    await waitFor(() => expect(screen.getByLabelText('Completed date')).toHaveValue('2025-12-24'));

    fireEvent.change(screen.getByLabelText('Completed date'), { target: { value: '2025-12-25' } });
    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1',
      expect.objectContaining({ expected_revision: 1, completed_at: '2025-12-25T00:00:00.000Z' }),
    ));

    await userEvent.click(screen.getByRole('button', { name: new Date('2025-12-25T00:00:00.000Z').toLocaleDateString() }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1',
      expect.objectContaining({ expected_revision: 2, completed_at: null }),
    ));
  });
});

describe('TodoView detail editing and attachments', () => {
  async function renderSelectedDetail(item = detail({ id: 't1', title: 'Editable item' })): Promise<void> {
    apiMocks.hydrateTodoWorkspace.mockResolvedValue({
      items: [item],
      next_cursor: null,
      counts_by_status: { [item.status]: 1 },
    });
    apiMocks.getTodoItem.mockResolvedValue(item);

    render(<TodoView />);
    if (item.status !== 'open') {
      await userEvent.click(screen.getByRole('tab', { name: 'All' }));
    }
    await waitFor(() => expect(screen.getByText('Editable item')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Editable item' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit To-Do' })).toBeInTheDocument());
  }

  it('edits title and description together using the item revision', async () => {
    await renderSelectedDetail();
    apiMocks.updateTodoItem.mockResolvedValue(detail({
      id: 't1',
      title: 'Updated title',
      description: 'Updated description',
      revision: 2,
    }));

    await userEvent.click(screen.getByRole('button', { name: 'Edit To-Do' }));
    await userEvent.clear(screen.getByLabelText('To-Do title'));
    await userEvent.type(screen.getByLabelText('To-Do title'), 'Updated title');
    await userEvent.clear(screen.getByLabelText('To-Do description'));
    await userEvent.type(screen.getByLabelText('To-Do description'), 'Updated description');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1',
      { expected_revision: 1, title: 'Updated title', description: 'Updated description' },
    ));
    expect(screen.getByText('Updated description')).toBeInTheDocument();
  });

  it('persists rich description formatting while stripping unexpected markup', async () => {
    await renderSelectedDetail();
    apiMocks.updateTodoItem.mockResolvedValue(detail({
      id: 't1',
      title: 'Editable item',
      description: '<strong>Formatted description</strong>',
      revision: 2,
    }));

    await userEvent.click(screen.getByRole('button', { name: 'Edit To-Do' }));
    const description = screen.getByLabelText('To-Do description');
    description.innerHTML = '<strong>Formatted description</strong><img src="x" onerror="alert(1)">';
    fireEvent.input(description);
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1',
      { expected_revision: 1, title: 'Editable item', description: '<strong>Formatted description</strong>' },
    ));
    expect(screen.getByText('Formatted description')).toBeInTheDocument();
  });

  it('persists rich notes formatting through the existing revisioned notes API', async () => {
    await renderSelectedDetail();
    apiMocks.replaceTodoNotes.mockResolvedValue(detail({
      id: 't1',
      title: 'Editable item',
      notes: '<ul><li>Review the draft</li></ul>',
      revision: 2,
    }));

    const notes = screen.getByLabelText('To-Do notes');
    notes.innerHTML = '<ul><li>Review the draft</li></ul>';
    fireEvent.input(notes);
    await userEvent.click(screen.getByRole('button', { name: 'Save notes' }));

    await waitFor(() => expect(apiMocks.replaceTodoNotes).toHaveBeenCalledWith(
      't1',
      '<ul><li>Review the draft</li></ul>',
      1,
    ));
  });

  it('retains multiline description and provenance text in dedicated display elements', async () => {
    await renderSelectedDetail(detail({
      id: 't1',
      title: 'Editable item',
      description: 'First follow-up\nSecond follow-up',
      sources: [{
        id: 'source-1',
        todo_id: 't1',
        source_kind: 'meeting_analysis_proposal',
        source_id: 'meeting-1:analysis.json:proposal-1',
        source_locator: {},
        source_excerpt: '[00:01] Microphone: First line\n[00:02] System Audio: Second line',
        created_by_kind: 'system',
        created_at: '2026-08-18T00:00:00Z',
      }],
    }));

    const description = document.querySelector('.todo-detail-description');
    const provenance = document.querySelector('.todo-detail-sources li');
    expect(description?.textContent).toBe('First follow-up\nSecond follow-up');
    expect(provenance?.textContent).toBe('meeting_analysis_proposal: [00:01] Microphone: First line\n[00:02] System Audio: Second line');
    expect(screen.getByText('No attachments yet.')).toBeInTheDocument();
  });

  it('shows Reopen for terminal To-Do statuses', async () => {
    await renderSelectedDetail(detail({
      id: 't1',
      title: 'Editable item',
      status: 'completed',
      revision: 2,
    }));

    expect(screen.getByRole('button', { name: 'Reopen' })).toBeInTheDocument();
  });

  it('removes the completed date after a reopened response clears it', async () => {
    const completed = detail({
      id: 't1',
      title: 'Editable item',
      status: 'completed',
      revision: 2,
      completed_at: '2025-12-24T09:30:00Z',
    });
    await renderSelectedDetail(completed);
    apiMocks.reopenTodoItem.mockResolvedValue(detail({
      ...completed,
      status: 'open',
      revision: 3,
      completed_at: null,
    }));

    await userEvent.click(screen.getByRole('button', { name: new Date(completed.completed_at!).toLocaleDateString() }));
    expect(screen.getByLabelText('Completed date')).toHaveValue('2025-12-24');
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }));

    await waitFor(() => expect(screen.queryByLabelText('Completed date')).not.toBeInTheDocument());
  });

  it('does not show Reopen for non-terminal To-Do statuses', async () => {
    await renderSelectedDetail(detail({ id: 't1', title: 'Editable item', status: 'open' }));

    expect(screen.queryByRole('button', { name: 'Reopen' })).not.toBeInTheDocument();
  });

  it('uses the native attachment picker and presents the persisted attachment as a filename chip', async () => {
    const attached = detail({
      id: 't1',
      title: 'Editable item',
      revision: 2,
      references: [{
        id: 'ref-1',
        todo_id: 't1',
        path: '/tmp/brief.pdf',
        created_by_kind: 'user',
        created_by_id: null,
        created_at: '2026-08-18T00:00:00Z',
      }],
    });
    apiMocks.addTodoReference.mockResolvedValue(attached);
    apiMocks.removeTodoReference.mockResolvedValue(detail({ id: 't1', title: 'Editable item', revision: 3 }));
    let pickedHandler: ((paths: string[]) => void) | undefined;
    bridgeMocks.registerTodoReferenceFilesPickedHandler.mockImplementation((handler: (paths: string[]) => void) => {
      pickedHandler = handler;
      return () => {};
    });

    await renderSelectedDetail();
    await userEvent.click(screen.getByRole('button', { name: 'Attach files or folders' }));
    expect(bridgeMocks.pickTodoReferenceFiles).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('Local absolute path')).not.toBeInTheDocument();

    pickedHandler?.(['/tmp/brief.pdf']);
    await waitFor(() => expect(apiMocks.addTodoReference).toHaveBeenCalledWith('t1', '/tmp/brief.pdf', 1));
    expect(screen.getByText('brief.pdf')).toHaveAttribute('title', '/tmp/brief.pdf');

    await userEvent.click(screen.getByRole('button', { name: 'Remove /tmp/brief.pdf' }));
    await waitFor(() => expect(apiMocks.removeTodoReference).toHaveBeenCalledWith('t1', 'ref-1', 2));
  });
});
