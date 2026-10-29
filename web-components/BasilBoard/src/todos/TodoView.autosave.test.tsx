import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  setTodoItemStatus: vi.fn(),
}));
const bridgeMocks = vi.hoisted(() => ({
  setBoardFileDropTarget: vi.fn(),
  pickTodoReferenceFiles: vi.fn(),
  registerTodoReferenceFilesPickedHandler: vi.fn(),
  openExistingAgentTaskWidget: vi.fn(),
  openMeetingWorkspace: vi.fn(),
}));
vi.mock('../services/api', () => apiMocks);
vi.mock('../services/bridge', () => bridgeMocks);
vi.mock('./TodoWorkspacePane', () => ({ default: () => <div data-testid="workspace-pane-stub" /> }));

function summary(overrides: Partial<TodoItemSummary> = {}): TodoItemSummary {
  return {
    id: 't1', title: 'Autosave item', status: 'open', responsibility: 'user', priority: 'normal',
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

async function renderSelected(item = detail()): Promise<void> {
  apiMocks.hydrateTodoWorkspace.mockResolvedValue({
    items: [item], next_cursor: null, counts_by_status: { [item.status]: 1 },
  });
  apiMocks.getTodoItem.mockResolvedValue(item);
  render(<TodoView />);
  await userEvent.click(screen.getByRole('tab', { name: 'All' }));
  await userEvent.click(await screen.findByRole('button', { name: item.title }));
  await waitFor(() => expect(screen.getByLabelText('To-Do title')).toHaveValue(item.title));
}

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  let reject: (reason: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  Object.values(apiMocks).forEach((mockFn) => mockFn.mockReset());
  bridgeMocks.registerTodoReferenceFilesPickedHandler.mockReset();
  bridgeMocks.registerTodoReferenceFilesPickedHandler.mockReturnValue(() => {});
  apiMocks.hydrateTodoWorkspace.mockResolvedValue({ items: [], next_cursor: null, counts_by_status: {} });
  apiMocks.getTodoAgentStatuses.mockResolvedValue({});
});

describe('TodoView manual status', () => {
  it('lists every status and saves the chosen one with the current revision', async () => {
    await renderSelected();
    expect(screen.queryByRole('listbox', { name: 'Status' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Status' }));
    const menu = screen.getByRole('listbox', { name: 'Status' });
    expect(within(menu).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Candidate', 'Open', 'In progress', 'Ready for review', 'Completed', 'Dismissed', 'Canceled',
    ]);
    apiMocks.setTodoItemStatus.mockResolvedValue(detail({ status: 'ready_for_review', revision: 2 }));

    await userEvent.click(within(menu).getByRole('option', { name: 'Ready for review' }));

    await waitFor(() => expect(apiMocks.setTodoItemStatus).toHaveBeenCalledWith('t1', 'ready_for_review', 1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Status' })).toHaveTextContent('Ready for review'));
    expect(screen.queryByRole('listbox', { name: 'Status' })).not.toBeInTheDocument();
  });

  it('shows status and dates as plain text until clicked, and Escape closes the status menu without saving', async () => {
    await renderSelected();

    expect(screen.queryByRole('listbox', { name: 'Status' })).not.toBeInTheDocument();
    expect(document.querySelector('select')).toBeNull();
    expect(screen.queryByLabelText('Due date')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add due date' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Status' }));
    expect(screen.getByRole('listbox', { name: 'Status' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('listbox', { name: 'Status' })).not.toBeInTheDocument();
    expect(apiMocks.setTodoItemStatus).not.toHaveBeenCalled();
  });

  it('returns the status pill to the persisted status and shows the error when the change is rejected', async () => {
    await renderSelected();
    apiMocks.setTodoItemStatus.mockRejectedValue(new Error('Conflict on To-Do t1'));

    await userEvent.click(screen.getByRole('button', { name: 'Status' }));
    await userEvent.click(screen.getByRole('option', { name: 'Dismissed' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Conflict on To-Do t1');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Status' })).toHaveTextContent('Open'));
  });
});

describe('TodoView click-to-edit autosave', () => {
  it('saves the title on blur with the item revision', async () => {
    await renderSelected();
    apiMocks.updateTodoItem.mockResolvedValue(detail({ title: 'Updated title', revision: 2 }));

    const title = screen.getByLabelText('To-Do title');
    await userEvent.clear(title);
    await userEvent.type(title, 'Updated title');
    await userEvent.tab();

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1', { expected_revision: 1, title: 'Updated title' },
    ));
    expect(await screen.findByText('Saved')).toBeInTheDocument();
  });

  it('saves the title when Enter is pressed and does not save twice', async () => {
    await renderSelected();
    apiMocks.updateTodoItem.mockResolvedValue(detail({ title: 'Enter title', revision: 2 }));

    const title = screen.getByLabelText('To-Do title');
    await userEvent.clear(title);
    await userEvent.type(title, 'Enter title{Enter}');

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledTimes(1));
    expect(title).not.toHaveFocus();
  });

  it('reverts the title on Escape without saving', async () => {
    await renderSelected();

    const title = screen.getByLabelText('To-Do title');
    await userEvent.type(title, ' extra{Escape}');

    expect(title).toHaveValue('Autosave item');
    expect(apiMocks.updateTodoItem).not.toHaveBeenCalled();
  });

  it('rejects an empty title by restoring the saved one', async () => {
    await renderSelected();

    const title = screen.getByLabelText('To-Do title');
    await userEvent.clear(title);
    await userEvent.type(title, '   ');
    await userEvent.tab();

    expect(apiMocks.updateTodoItem).not.toHaveBeenCalled();
    expect(title).toHaveValue('Autosave item');
  });

  it('does not save when focus enters and leaves a field without a change', async () => {
    await renderSelected();

    await userEvent.click(screen.getByLabelText('To-Do title'));
    await userEvent.click(screen.getByLabelText('To-Do description'));
    await userEvent.click(screen.getByLabelText('To-Do notes'));
    await userEvent.tab();

    expect(apiMocks.updateTodoItem).not.toHaveBeenCalled();
    expect(apiMocks.replaceTodoNotes).not.toHaveBeenCalled();
  });

  it('persists rich description formatting on blur while stripping unexpected markup', async () => {
    await renderSelected();
    apiMocks.updateTodoItem.mockResolvedValue(detail({ description: '<strong>Formatted description</strong>', revision: 2 }));

    const description = screen.getByLabelText('To-Do description');
    await userEvent.click(description);
    description.innerHTML = '<strong>Formatted description</strong><img src="x" onerror="alert(1)">';
    fireEvent.input(description);
    await userEvent.tab();

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1', { expected_revision: 1, description: '<strong>Formatted description</strong>' },
    ));
  });

  it('keeps ampersands and angle brackets as text when saving a description', async () => {
    await renderSelected(detail({ description: 'Plain\nline two' }));
    apiMocks.updateTodoItem.mockResolvedValue(detail({ revision: 2 }));

    const description = screen.getByLabelText('To-Do description');
    expect(description.textContent).toBe('Plain\nline two');
    await userEvent.click(description);
    description.textContent = 'Fish & chips <b>';
    fireEvent.input(description);
    await userEvent.tab();

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1', { expected_revision: 1, description: 'Fish &amp; chips &lt;b&gt;' },
    ));
  });

  it('saves a cleared description as an empty string', async () => {
    await renderSelected();
    apiMocks.updateTodoItem.mockResolvedValue(detail({ description: '', revision: 2 }));

    const description = screen.getByLabelText('To-Do description');
    await userEvent.click(description);
    description.innerHTML = '<br>';
    fireEvent.input(description);
    await userEvent.tab();

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledWith(
      't1', { expected_revision: 1, description: '' },
    ));
  });

  it('saves notes with Command-Return', async () => {
    await renderSelected();
    apiMocks.replaceTodoNotes.mockResolvedValue(detail({ notes: 'Fresh note', revision: 2 }));

    const notes = screen.getByLabelText('To-Do notes');
    await userEvent.click(notes);
    notes.textContent = 'Fresh note';
    fireEvent.input(notes);
    fireEvent.keyDown(notes, { key: 'Enter', metaKey: true });

    await waitFor(() => expect(apiMocks.replaceTodoNotes).toHaveBeenCalledWith('t1', 'Fresh note', 1));
  });

  it('reverts notes on Escape without saving', async () => {
    await renderSelected();

    const notes = screen.getByLabelText('To-Do notes');
    await userEvent.click(notes);
    notes.textContent = 'Discard me';
    fireEvent.input(notes);
    fireEvent.keyDown(notes, { key: 'Escape' });

    expect(notes.textContent).toBe('Some notes');
    expect(apiMocks.replaceTodoNotes).not.toHaveBeenCalled();
  });

  it('keeps the typed draft and shows an error indicator when a save fails, then retries on the next blur', async () => {
    await renderSelected();
    apiMocks.updateTodoItem.mockRejectedValueOnce(new Error('Network down'));

    const title = screen.getByLabelText('To-Do title');
    await userEvent.clear(title);
    await userEvent.type(title, 'Kept title');
    await userEvent.tab();

    expect(await screen.findByRole('alert')).toHaveTextContent('Network down');
    expect(title).toHaveValue('Kept title');
    expect(screen.getByRole('status')).toHaveTextContent('Not saved');

    apiMocks.updateTodoItem.mockResolvedValue(detail({ title: 'Kept title', revision: 2 }));
    await userEvent.click(title);
    await userEvent.tab();

    await waitFor(() => expect(apiMocks.updateTodoItem).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('sends quick successive edits to two fields on consecutive revisions', async () => {
    await renderSelected();
    const titleSave = deferred<TodoItemDetail>();
    apiMocks.updateTodoItem.mockReturnValue(titleSave.promise);
    apiMocks.replaceTodoNotes.mockResolvedValue(detail({ title: 'Quick title', notes: 'Quick note', revision: 3 }));

    const title = screen.getByLabelText('To-Do title');
    await userEvent.clear(title);
    await userEvent.type(title, 'Quick title');
    const notes = screen.getByLabelText('To-Do notes');
    await userEvent.click(notes);
    notes.textContent = 'Quick note';
    fireEvent.input(notes);
    await userEvent.tab();

    expect(apiMocks.replaceTodoNotes).not.toHaveBeenCalled();
    titleSave.resolve(detail({ title: 'Quick title', revision: 2 }));

    await waitFor(() => expect(apiMocks.replaceTodoNotes).toHaveBeenCalledWith('t1', 'Quick note', 2));
    expect(apiMocks.updateTodoItem).toHaveBeenCalledWith('t1', { expected_revision: 1, title: 'Quick title' });
  });

  it('does not overwrite text being typed in notes when a title autosave refreshes the item', async () => {
    await renderSelected();
    const titleSave = deferred<TodoItemDetail>();
    apiMocks.updateTodoItem.mockReturnValue(titleSave.promise);

    const title = screen.getByLabelText('To-Do title');
    await userEvent.clear(title);
    await userEvent.type(title, 'Fresh title');
    const notes = screen.getByLabelText('To-Do notes');
    await userEvent.click(notes);
    notes.textContent = 'Half-typed note';
    fireEvent.input(notes);

    titleSave.resolve(detail({ title: 'Fresh title', revision: 2 }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'));

    expect(notes.textContent).toBe('Half-typed note');
    expect(title).toHaveValue('Fresh title');
  });

  it('adopts a server update to an untouched field', async () => {
    await renderSelected();
    apiMocks.setTodoItemStatus.mockResolvedValue(detail({ title: 'Renamed elsewhere', status: 'completed', revision: 2 }));

    await userEvent.click(screen.getByRole('button', { name: 'Status' }));
    await userEvent.click(screen.getByRole('option', { name: 'Completed' }));

    await waitFor(() => expect(screen.getByLabelText('To-Do title')).toHaveValue('Renamed elsewhere'));
  });
});

describe('TodoView description editor and bold', () => {
  it('clicking into the description does not toggle bold', async () => {
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });
    await renderSelected();

    await userEvent.click(screen.getByLabelText('To-Do description'));
    await userEvent.click(screen.getByText('Description'));

    expect(execCommand).not.toHaveBeenCalledWith('bold', false, undefined);
    expect(execCommand.mock.calls.filter(([command]) => command === 'bold')).toHaveLength(0);
    expect(screen.getAllByRole('button', { name: 'Bold' })[0]).not.toHaveClass('is-active');
  });

  it('does not wrap the description editor in a label', async () => {
    await renderSelected();

    expect(screen.getByLabelText('To-Do description').closest('label')).toBeNull();
  });
});
