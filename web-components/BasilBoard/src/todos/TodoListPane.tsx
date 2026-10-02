import { useState } from 'react';
import { StatusIcon } from '@agent-task/components/sidebar/SidebarIcons';
import type { TodoItemSummary } from '../contracts';
import { useHistoryRowRevealDelete } from '../../../shared/useHistoryRowRevealDelete';
import type { TodoSortBy } from '../services/api';
import TodoDeleteConfirmation from './TodoDeleteConfirmation';
import type { TodoListFilter } from './todoState';
import { formatTodoDateOnly, isTodoDueDateOverdue } from './todoDates';
import TodoSortMenu from './TodoSortMenu';

const FILTERS: { id: TodoListFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'inbox', label: 'Inbox' },
  { id: 'open', label: 'Open' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'ready_for_review', label: 'Ready for review' },
  { id: 'completed', label: 'Completed' },
];

interface TodoListPaneProps {
  items: TodoItemSummary[];
  loading: boolean;
  error: string | null;
  query: string;
  onQueryChange: (query: string) => void;
  activeFilter: TodoListFilter;
  onFilterChange: (filter: TodoListFilter) => void;
  selectedIds: string[];
  onToggleSelected: (id: string) => void;
  selectionDisabled: boolean;
  onCreate: (title: string) => Promise<void>;
  sortBy: TodoSortBy;
  onSortChange: (sortBy: TodoSortBy) => void;
  viewingId: string | null;
  onView: (id: string) => void;
  loadingMore: boolean;
  loadMoreError: string | null;
  hasMore: boolean;
  onRetryLoad: () => void;
  onRetryLoadMore: () => void;
  onLoadMore: () => void;
  pendingDeleteId: string | null;
  deletingId: string | null;
  deleteError: string | null;
  onRequestDelete: (todoId: string, expectedRevision: number) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (todoId: string, expectedRevision: number) => Promise<void>;
}

function formatTodoStatus(status: string): string {
  return status === 'canceled' ? 'Canceled' : status.replace(/_/g, ' ');
}

function formatTodoDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

export default function TodoListPane({
  items, loading, error, query, onQueryChange, activeFilter, onFilterChange, selectedIds, onToggleSelected, selectionDisabled, onCreate,
  sortBy, onSortChange, viewingId, onView, loadingMore, loadMoreError, hasMore, onRetryLoad, onRetryLoadMore, onLoadMore,
  pendingDeleteId, deletingId, deleteError, onRequestDelete, onCancelDelete, onConfirmDelete,
}: TodoListPaneProps) {
  const [isCreating, setIsCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);

  async function createTodo(): Promise<void> {
    const title = newTitle.trim();
    if (!title) return;
    setCreateError(null);
    try {
      await onCreate(title);
      setNewTitle('');
      setIsCreating(false);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Could not create the To-Do.');
    }
  }

  return (
    <div className="todo-list-pane">
      <div className="todo-list-create">
        <button type="button" onClick={() => setIsCreating((current) => !current)}>
          {isCreating ? 'Cancel new To-Do' : 'New To-Do'}
        </button>
        {isCreating && (
          <form onSubmit={(event) => { event.preventDefault(); void createTodo(); }}>
            <label>
              New To-Do title
              <input
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                maxLength={240}
                autoFocus
              />
            </label>
            <button type="submit" disabled={!newTitle.trim()}>Create</button>
            {createError && <p role="alert" className="todo-list-status todo-list-status--error">{createError}</p>}
          </form>
        )}
      </div>
      <div className="todo-list-filters" role="tablist">
        {FILTERS.map((filter) => (
          <button
            key={filter.id}
            type="button"
            role="tab"
            aria-selected={activeFilter === filter.id}
            className={`todo-list-filter${activeFilter === filter.id ? ' todo-list-filter--active' : ''}`}
            onClick={() => onFilterChange(filter.id)}
          >
            {filter.label}
          </button>
        ))}
      </div>
      <label className="todo-list-search">
        Search To-Dos
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search titles..."
          maxLength={240}
        />
      </label>
      <TodoSortMenu value={sortBy} onChange={onSortChange} />
      {loading && items.length === 0 && <p className="todo-list-status">Loading To-Dos...</p>}
      {!loading && error && (
        <div className="todo-list-status todo-list-status--error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={onRetryLoad}>Retry</button>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <p className="todo-list-status">{query.trim() ? 'No To-Do titles match your search.' : 'No To-Dos in this view yet.'}</p>
      )}
      <ul className="todo-list-items basil-refresh-region" aria-busy={loading && items.length > 0 ? true : undefined}>
        {items.map((item) => (
          <TodoListRow
            key={item.id}
            item={item}
            isViewing={viewingId === item.id}
            isSelected={selectedIds.includes(item.id)}
            selectionDisabled={selectionDisabled}
            isPendingDelete={pendingDeleteId === item.id}
            isDeleting={deletingId === item.id}
            onToggleSelected={onToggleSelected}
            onView={onView}
            onRequestDelete={onRequestDelete}
            onCancelDelete={onCancelDelete}
            onConfirmDelete={onConfirmDelete}
          />
        ))}
      </ul>
      {deleteError && <p className="todo-list-status todo-list-status--error" role="alert">{deleteError}</p>}
      {!loading && !error && loadMoreError && (
        <div className="todo-list-status todo-list-status--error" role="alert">
          <span>{loadMoreError}</span>
          <button type="button" onClick={onRetryLoadMore}>Retry</button>
        </div>
      )}
      {!loading && !error && hasMore && (
        <button
          type="button"
          className="todo-list-load-more"
          onClick={onLoadMore}
          disabled={loadingMore}
          aria-busy={loadingMore}
        >
          {loadingMore ? 'Loading more To-Dos...' : 'Load more To-Dos'}
        </button>
      )}
    </div>
  );
}

interface TodoListRowProps {
  item: TodoItemSummary;
  isViewing: boolean;
  isSelected: boolean;
  selectionDisabled: boolean;
  isPendingDelete: boolean;
  isDeleting: boolean;
  onToggleSelected: (id: string) => void;
  onView: (id: string) => void;
  onRequestDelete: (todoId: string, expectedRevision: number) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (todoId: string, expectedRevision: number) => Promise<void>;
}

function TodoListRow({
  item,
  isViewing,
  isSelected,
  selectionDisabled,
  isPendingDelete,
  isDeleting,
  onToggleSelected,
  onView,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: TodoListRowProps) {
  const isDeleteDisabled = item.agent_status?.is_active === true;
  const revealDelete = useHistoryRowRevealDelete({ enabled: !isDeleteDisabled && !isPendingDelete });
  const requestDelete = () => {
    if (isDeleteDisabled) return;
    revealDelete.close();
    onRequestDelete(item.id, item.revision);
  };
  const viewItem = () => {
    if (revealDelete.isOpen) {
      revealDelete.close();
      return;
    }
    onView(item.id);
  };

  return (
    <li
      className={`todo-list-item todo-list-item--${item.status}${isViewing ? ' todo-list-item--viewing' : ''}${isSelected ? ' todo-list-item--selected' : ''}`}
      onWheel={revealDelete.handleWheel}
    >
      {revealDelete.isOpen && (
        <button type="button" className="todo-list-swipe-delete-button" onClick={requestDelete}>Delete</button>
      )}
      <div
        className="todo-list-item-row-content"
        style={{ transform: revealDelete.offset > 0 ? `translateX(-${revealDelete.offset}px)` : undefined }}
      >
        <input
          type="checkbox"
          checked={isSelected}
          disabled={selectionDisabled}
          onChange={() => onToggleSelected(item.id)}
          aria-label={`Select ${item.title} for the workspace`}
        />
        <div
          className="todo-list-item-content"
          role="button"
          tabIndex={0}
          aria-label={item.title}
          aria-current={isViewing ? 'true' : undefined}
          onClick={viewItem}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            viewItem();
          }}
        >
          <span className="todo-list-item-title" title={item.title}>
            <span className="todo-list-item-title-text">{item.title}</span>
            {item.agent_status && (
              <span
                className="todo-list-item-agent-status"
                title={`Agent Task ${item.agent_status.is_active ? 'in progress' : item.agent_status.status}`}
              >
                <StatusIcon
                  status={item.agent_status.status}
                  resultSeverity={item.agent_status.result_severity ?? undefined}
                  size={8}
                />
              </span>
            )}
          </span>
          <div className="todo-list-item-meta">
            <span className="todo-list-item-status">{formatTodoStatus(item.status)}</span>
            <span>Created {formatTodoDate(item.created_at)}</span>
            {item.due_at && (
              <span
                className={`todo-list-item-due${isTodoDueDateOverdue(item.due_at) && !['completed', 'dismissed', 'canceled'].includes(item.status) ? ' todo-list-item-due--overdue' : ''}`}
              >
                Due {formatTodoDateOnly(item.due_at)}
              </span>
            )}
            {item.status === 'completed' && item.completed_at && (
              <span className="todo-list-item-completed">
                Completed {formatTodoDateOnly(item.completed_at)}
              </span>
            )}
          </div>
        </div>
        {item.attention.needs_attention && (
          <span className="todo-list-item-attention" title={item.attention.reason ?? 'Needs attention'}>!</span>
        )}
      </div>
      {isPendingDelete && (
        <TodoDeleteConfirmation
          className="todo-list-delete-confirmation"
          isDeleting={isDeleting}
          onConfirm={() => { void onConfirmDelete(item.id, item.revision); }}
          onCancel={onCancelDelete}
        />
      )}
    </li>
  );
}
