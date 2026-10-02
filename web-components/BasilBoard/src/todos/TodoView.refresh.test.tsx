import { render, screen, waitFor } from '@testing-library/react';
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
  default: () => <div data-testid="workspace-pane-stub" />,
}));

function summary(overrides: Partial<TodoItemSummary> = {}): TodoItemSummary {
  return {
    id: 'todo-1', title: 'Existing item', status: 'open', responsibility: 'user', priority: 'normal',
    due_at: null, revision: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    attention: { needs_attention: false }, ...overrides,
  };
}

function detail(overrides: Partial<TodoItemDetail> = {}): TodoItemDetail {
  return {
    ...summary(overrides),
    description: 'Created description', notes: '', idempotency_key: null, created_by_kind: 'user',
    created_by_id: null, sources: [], references: [], worker_attempts: [], ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const existing = summary();
const created = detail({ id: 'todo-2', title: 'Manual item' });

beforeEach(() => {
  Object.values(apiMocks).forEach((mockFn) => mockFn.mockReset());
  Object.values(bridgeMocks).forEach((mockFn) => mockFn.mockReset());
  bridgeMocks.registerTodoReferenceFilesPickedHandler.mockReturnValue(() => {});
  apiMocks.getTodoAgentStatuses.mockResolvedValue({});
  apiMocks.createTodoItem.mockResolvedValue(created);
  apiMocks.getTodoItem.mockResolvedValue(created);
});

async function createManualItem() {
  await userEvent.click(screen.getByRole('button', { name: 'New To-Do' }));
  await userEvent.type(screen.getByLabelText('New To-Do title'), 'Manual item');
  await userEvent.click(screen.getByRole('button', { name: 'Create' }));
}

describe('TodoView refresh continuity', () => {
  it('keeps existing rows visible without a loading row while a mutation refresh is in flight', async () => {
    const refresh = deferred<{ items: TodoItemSummary[]; next_cursor: null; has_more: boolean; counts_by_status: Record<string, number> }>();
    apiMocks.hydrateTodoWorkspace
      .mockResolvedValueOnce({ items: [existing], next_cursor: null, has_more: false, counts_by_status: { open: 1 } })
      .mockReturnValueOnce(refresh.promise);

    render(<TodoView />);
    expect(await screen.findByText('Existing item')).toBeInTheDocument();

    await createManualItem();
    await waitFor(() => expect(apiMocks.hydrateTodoWorkspace).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Existing item')).toBeInTheDocument();
    expect(screen.queryByText(/Loading To-Dos/i)).not.toBeInTheDocument();
    expect(apiMocks.hydrateTodoWorkspace).toHaveBeenLastCalledWith(
      { column: 'created_at' },
      { query: undefined, statuses: ['open', 'in_progress', 'ready_for_review'], limit: 50 },
    );

    refresh.resolve({ items: [created, existing], next_cursor: null, has_more: false, counts_by_status: { open: 2 } });
    await waitFor(() => expect(screen.getAllByText('Manual item').length).toBeGreaterThan(0));
    expect(screen.getByText('Existing item')).toBeInTheDocument();
  });

  it('keeps existing rows and shows no list error when a mutation refresh fails', async () => {
    apiMocks.hydrateTodoWorkspace
      .mockResolvedValueOnce({ items: [existing], next_cursor: null, has_more: false, counts_by_status: { open: 1 } })
      .mockRejectedValueOnce(new Error('refresh failed'));

    render(<TodoView />);
    expect(await screen.findByText('Existing item')).toBeInTheDocument();

    await createManualItem();
    await waitFor(() => expect(apiMocks.hydrateTodoWorkspace).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('refresh failed')).not.toBeInTheDocument());
    expect(screen.getByText('Existing item')).toBeInTheDocument();
  });

  it('keeps prior rows visible and marks the list busy while a search reloads', async () => {
    const search = deferred<{ items: TodoItemSummary[]; next_cursor: null; has_more: boolean; counts_by_status: Record<string, number> }>();
    apiMocks.hydrateTodoWorkspace
      .mockResolvedValueOnce({ items: [existing], next_cursor: null, has_more: false, counts_by_status: { open: 1 } })
      .mockReturnValueOnce(search.promise);

    const { container } = render(<TodoView />);
    expect(await screen.findByText('Existing item')).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText('Search titles...'), 'Existing');
    await waitFor(() => expect(apiMocks.hydrateTodoWorkspace).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Existing item')).toBeInTheDocument();
    expect(screen.queryByText(/Loading To-Dos/i)).not.toBeInTheDocument();
    expect(container.querySelector('.todo-list-items')?.getAttribute('aria-busy')).toBe('true');

    search.resolve({ items: [existing], next_cursor: null, has_more: false, counts_by_status: { open: 1 } });
    await waitFor(() => expect(container.querySelector('.todo-list-items')?.hasAttribute('aria-busy')).toBe(false));
  });
});
