import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  AgentTaskOriginNavigationPayload,
  TodoItemDetail,
  TodoItemSummary,
} from '../contracts';
import {
  acceptTodoCandidate,
  addTodoReference,
  cancelTodoItem,
  completeTodoItem,
  createTodoItem,
  deleteTodoItem,
  dismissTodoCandidate,
  getTodoItem,
  hydrateTodoWorkspace,
  launchTodoWorker,
  reopenTodoItem,
  removeTodoReference,
  replaceTodoNotes,
  type TodoSortBy,
  updateTodoItem,
} from '../services/api';
import { openExistingAgentTaskWidget } from '../services/bridge';
import { filterToStatuses, type TodoListFilter } from './todoState';
import TodoDetailPane from './TodoDetailPane';
import TodoListPane from './TodoListPane';
import TodoWorkspacePane from './TodoWorkspacePane';
import useTodoListAgentStatus from './useTodoListAgentStatus';
import useTodoWorkerProgress from './useTodoWorkerProgress';

interface TodoViewProps {
  originNavigation?: AgentTaskOriginNavigationPayload;
}

function filterForTodoStatus(status: string): TodoListFilter {
  switch (status) {
    case 'candidate': return 'inbox';
    case 'in_progress': return 'in_progress';
    case 'ready_for_review': return 'ready_for_review';
    case 'completed': return 'completed';
    default: return 'open';
  }
}

function withLaunchedWorkerAttempt(item: TodoItemDetail, agentTaskId: string): TodoItemDetail {
  if (item.worker_attempts.some((attempt) => attempt.agent_task_id === agentTaskId)) return item;
  return {
    ...item,
    worker_attempts: [
      ...item.worker_attempts,
      {
        agent_task_id: agentTaskId,
        title: null,
        status: 'processing',
        created_at: item.updated_at,
        updated_at: item.updated_at,
        result_summary: null,
        attention: false,
      },
    ],
  };
}

const TODO_WORKSPACE_PAGE_SIZE = 50;
const TODO_WORKSPACE_MAX_REFRESH_SIZE = 200;

function mergeTodoPages(current: TodoItemSummary[], next: TodoItemSummary[]): TodoItemSummary[] {
  const knownIds = new Set(current.map((item) => item.id));
  return [...current, ...next.filter((item) => !knownIds.has(item.id))];
}

export default function TodoView({ originNavigation }: TodoViewProps) {
  const [items, setItems] = useState<TodoItemSummary[]>([]);
  const itemsRef = useRef<TodoItemSummary[]>([]);
  itemsRef.current = items;
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<TodoListFilter>('open');
  const [sortBy, setSortBy] = useState<TodoSortBy>({ column: 'created_at' });
  const [selectedItemsById, setSelectedItemsById] = useState<Record<string, TodoItemSummary>>({});
  const [viewingId, setViewingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TodoItemDetail | null>(null);
  const detailRef = useRef<TodoItemDetail | null>(null);
  const nextCursorRef = useRef<string>();
  const requestVersionRef = useRef(0);
  const loadingMoreRef = useRef(false);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deletingTodoId, setDeletingTodoId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const refreshList = useCallback(async (options: { quiet?: boolean } = {}) => {
    const quiet = options.quiet === true;
    const version = ++requestVersionRef.current;
    const statuses = filterToStatuses(filter);
    const normalizedQuery = query.trim();
    const previousCursor = nextCursorRef.current;
    nextCursorRef.current = undefined;
    loadingMoreRef.current = false;
    setLoadingMore(false);
    setLoadMoreError(null);
    if (!quiet) {
      setHasMore(false);
      setLoading(true);
      setError(null);
    }
    try {
      const hydration = await hydrateTodoWorkspace(sortBy, {
        query: normalizedQuery || undefined,
        statuses,
        limit: quiet
          ? Math.min(TODO_WORKSPACE_MAX_REFRESH_SIZE, Math.max(TODO_WORKSPACE_PAGE_SIZE, itemsRef.current.length))
          : TODO_WORKSPACE_PAGE_SIZE,
      });
      if (version !== requestVersionRef.current) return;
      setItems(hydration.items);
      setHasMore(hydration.has_more);
      nextCursorRef.current = hydration.next_cursor ?? undefined;
    } catch (err) {
      if (version !== requestVersionRef.current) return;
      if (quiet) {
        nextCursorRef.current = previousCursor;
        return;
      }
      setItems([]);
      setError(err instanceof Error ? err.message : 'Failed to load To-Dos');
    } finally {
      if (version === requestVersionRef.current) setLoading(false);
    }
  }, [filter, query, sortBy]);

  const loadMore = useCallback(async () => {
    const cursor = nextCursorRef.current;
    if (!cursor || !hasMore || loadingMoreRef.current) return;
    const version = requestVersionRef.current;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const hydration = await hydrateTodoWorkspace(sortBy, {
        query: query.trim() || undefined,
        statuses: filterToStatuses(filter),
        limit: TODO_WORKSPACE_PAGE_SIZE,
        cursor,
      });
      if (version !== requestVersionRef.current) return;
      setItems((current) => mergeTodoPages(current, hydration.items));
      setHasMore(hydration.has_more);
      nextCursorRef.current = hydration.next_cursor ?? undefined;
    } catch (err) {
      if (version !== requestVersionRef.current) return;
      setLoadMoreError(err instanceof Error ? err.message : 'Failed to load more To-Dos');
    } finally {
      if (version === requestVersionRef.current) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }, [filter, hasMore, query, sortBy]);

  function resetPagination(): void {
    requestVersionRef.current += 1;
    nextCursorRef.current = undefined;
    loadingMoreRef.current = false;
    setHasMore(false);
    setLoadingMore(false);
    setError(null);
    setLoadMoreError(null);
  }

  function changeQuery(nextQuery: string): void {
    resetPagination();
    setQuery(nextQuery);
  }

  function changeFilter(nextFilter: TodoListFilter): void {
    resetPagination();
    setFilter(nextFilter);
  }

  function changeSort(nextSort: TodoSortBy): void {
    resetPagination();
    setSortBy(nextSort);
  }

  function setCurrentDetail(nextDetail: TodoItemDetail | null): void {
    detailRef.current = nextDetail;
    setDetail(nextDetail);
  }

  const refreshSelectedWorkerDetail = useCallback(() => {
    const selected = detailRef.current;
    if (!selected) return;
    void getTodoItem(selected.id).then((refreshed) => {
      if (detailRef.current?.id !== refreshed.id) return;
      detailRef.current = refreshed;
      setDetail(refreshed);
      setItems((current) => current.map((item) => item.id === refreshed.id ? refreshed : item));
      setSelectedItemsById((current) => current[refreshed.id] ? { ...current, [refreshed.id]: refreshed } : current);
    }).catch(() => {
      // The next explicit refresh presents a durable retrieval error.
    });
  }, []);

  const workerProgress = useTodoWorkerProgress(
    detail?.worker_attempts ?? [],
    refreshSelectedWorkerDetail,
    openExistingAgentTaskWidget,
  );

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void refreshList();
    }, query.trim() ? 300 : 0);
    return () => window.clearTimeout(handle);
  }, [query, refreshList]);

  useEffect(() => {
    if (originNavigation?.originType !== 'todo' || loading) return;
    let canceled = false;
    setConflictMessage(null);
    void getTodoItem(originNavigation.originId)
      .then((item) => {
        if (canceled) return;
        setError(null);
        setItems(current => current.some(existing => existing.id === item.id)
          ? current.map(existing => existing.id === item.id ? item : existing)
          : [item, ...current]);
        setFilter(filterForTodoStatus(item.status));
        setViewingId(item.id);
        setCurrentDetail(item);
      })
      .catch(() => {
        if (canceled) return;
        setViewingId(null);
        setCurrentDetail(null);
        setError('The referenced To-Do could not be found.');
      });
    return () => {
      canceled = true;
    };
  }, [loading, originNavigation]);

  useEffect(() => {
    if (!viewingId) {
      setCurrentDetail(null);
      return;
    }
    let canceled = false;
    void getTodoItem(viewingId)
      .then((item) => {
        if (!canceled) setCurrentDetail(item);
      })
      .catch(() => {
        if (canceled) return;
        setDetail((current) => {
          const nextDetail = current?.id === viewingId ? current : null;
          detailRef.current = nextDetail;
          return nextDetail;
        });
      });
    return () => {
      canceled = true;
    };
  }, [viewingId]);

  const visibleItems = items.filter((item) => {
    const wantedStatuses = filterToStatuses(filter);
    return !wantedStatuses || wantedStatuses.includes(item.status);
  });
  const selectedIds = Object.keys(selectedItemsById);
  const selectedSummaries = Object.values(selectedItemsById);

  const liveAgentStatuses = useTodoListAgentStatus(visibleItems.map((item) => item.id));
  const visibleItemsWithLiveStatus = visibleItems.map((item) => (
    item.id in liveAgentStatuses ? { ...item, agent_status: liveAgentStatuses[item.id] } : item
  ));

  function toggleSelected(id: string) {
    if (workspaceBusy) return;
    setSelectedItemsById((current) => {
      if (current[id]) {
        const { [id]: _removed, ...remaining } = current;
        return remaining;
      }
      const item = items.find((candidate) => candidate.id === id);
      return item ? { ...current, [id]: item } : current;
    });
  }

  function viewItem(id: string): void {
    setViewingId(id);
  }

  async function createManualTodo(title: string): Promise<void> {
    const item = await createTodoItem({
      title,
      idempotency_key: `todo-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    });
    setViewingId(item.id);
    setCurrentDetail(item);
    await refreshList({ quiet: true });
  }

  async function withConflictHandling(action: () => Promise<TodoItemDetail>) {
    try {
      const updated = await action();
      setCurrentDetail(updated);
      setSelectedItemsById((current) => current[updated.id] ? { ...current, [updated.id]: updated } : current);
      setConflictMessage(null);
      await refreshList({ quiet: true });
    } catch (err) {
      setConflictMessage(err instanceof Error ? err.message : 'That change could not be applied. It may be stale.');
    }
  }

  async function withReferenceConflictHandling(action: () => Promise<TodoItemDetail>): Promise<TodoItemDetail> {
    try {
      const updated = await action();
      setCurrentDetail(updated);
      setSelectedItemsById((current) => current[updated.id] ? { ...current, [updated.id]: updated } : current);
      setConflictMessage(null);
      await refreshList({ quiet: true });
      return updated;
    } catch (err) {
      setConflictMessage(err instanceof Error ? err.message : 'That change could not be applied. It may be stale.');
      throw err;
    }
  }

  async function launchWorkerFromTodo(todoId: string, expectedRevision: number): Promise<void> {
    try {
      const response = await launchTodoWorker(todoId, expectedRevision);
      const updated = withLaunchedWorkerAttempt(response.item, response.agent_task_id);
      setCurrentDetail(updated);
      setSelectedItemsById((current) => current[updated.id] ? { ...current, [updated.id]: updated } : current);
      setConflictMessage(null);
      await refreshList({ quiet: true });
    } catch (err) {
      setConflictMessage(err instanceof Error ? err.message : 'That change could not be applied. It may be stale.');
    }
  }

  async function deleteTodoFromView(todoId: string, expectedRevision: number): Promise<boolean> {
    try {
      await deleteTodoItem(todoId, expectedRevision);
      setItems((current) => current.filter((item) => item.id !== todoId));
      setSelectedItemsById((current) => {
        const { [todoId]: _removed, ...remaining } = current;
        return remaining;
      });
      if (detailRef.current?.id === todoId) {
        setViewingId(null);
        setCurrentDetail(null);
      }
      setPendingDeleteId((current) => current === todoId ? null : current);
      setDeleteError(null);
      await refreshList({ quiet: true });
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'That To-Do could not be deleted.';
      setDeleteError(message);
      return false;
    }
  }

  async function confirmTodoDelete(todoId: string, expectedRevision: number): Promise<void> {
    setDeletingTodoId(todoId);
    const deleted = await deleteTodoFromView(todoId, expectedRevision);
    setDeletingTodoId(null);
    if (deleted) setPendingDeleteId(null);
  }

  const refreshAfterWorkspaceResult = useCallback(() => {
    void refreshList({ quiet: true });
  }, [refreshList]);

  return (
    <div className="todo-view">
      <TodoListPane
        items={visibleItemsWithLiveStatus}
        loading={loading}
        error={error}
        query={query}
        onQueryChange={changeQuery}
        activeFilter={filter}
        onFilterChange={changeFilter}
        selectedIds={selectedIds}
        onToggleSelected={toggleSelected}
        selectionDisabled={workspaceBusy}
        onCreate={createManualTodo}
        sortBy={sortBy}
        onSortChange={changeSort}
        viewingId={viewingId}
        onView={viewItem}
        loadingMore={loadingMore}
        loadMoreError={loadMoreError}
        hasMore={hasMore}
        onRetryLoad={() => { void refreshList(); }}
        onRetryLoadMore={() => { void loadMore(); }}
        onLoadMore={() => { void loadMore(); }}
        pendingDeleteId={pendingDeleteId}
        deletingId={deletingTodoId}
        deleteError={deleteError}
        onRequestDelete={(todoId) => {
          setConflictMessage(null);
          setDeleteError(null);
          setPendingDeleteId(todoId);
        }}
        onCancelDelete={() => setPendingDeleteId(null)}
        onConfirmDelete={confirmTodoDelete}
      />
      <TodoDetailPane
        item={detail}
        conflictMessage={conflictMessage}
        onRefreshAfterConflict={() => {
          if (!detail) return;
          void getTodoItem(detail.id).then((updated) => {
            setCurrentDetail(updated);
            setConflictMessage(null);
          });
        }}
        onSaveDetails={(title, description) => withConflictHandling(() => updateTodoItem(
          detail!.id,
          { expected_revision: detail!.revision, title, description },
        ))}
        onSaveNotes={(notes) => withConflictHandling(() => replaceTodoNotes(detail!.id, notes, detail!.revision))}
        onSaveDueDate={(dueAt) => withConflictHandling(() => updateTodoItem(detail!.id, { expected_revision: detail!.revision, due_at: dueAt }))}
        onSaveCompletedDate={(completedAt) => withConflictHandling(() => updateTodoItem(
          detail!.id,
          { expected_revision: detail!.revision, completed_at: completedAt },
        ))}
        onAddReference={(path) => {
          const currentDetail = detailRef.current;
          if (!currentDetail) return Promise.resolve();
          return withReferenceConflictHandling(() => addTodoReference(currentDetail.id, path, currentDetail.revision));
        }}
        onRemoveReference={(referenceId) => {
          const currentDetail = detailRef.current;
          if (!currentDetail) return Promise.resolve();
          return withReferenceConflictHandling(() => removeTodoReference(currentDetail.id, referenceId, currentDetail.revision));
        }}
        onAccept={() => withConflictHandling(() => acceptTodoCandidate(detail!.id, detail!.revision))}
        onDismiss={() => withConflictHandling(() => dismissTodoCandidate(detail!.id, detail!.revision))}
        onComplete={() => withConflictHandling(() => completeTodoItem(detail!.id, detail!.revision))}
        onReopen={() => withConflictHandling(() => reopenTodoItem(detail!.id, detail!.revision))}
        onCancel={() => withConflictHandling(() => cancelTodoItem(detail!.id, detail!.revision))}
        onDelete={async () => { await deleteTodoFromView(detail!.id, detail!.revision); }}
        onLaunchWorker={() => launchWorkerFromTodo(detail!.id, detail!.revision)}
        workerProgress={workerProgress}
      />
      <TodoWorkspacePane
        selectedItems={selectedSummaries}
        onBusyChange={setWorkspaceBusy}
        onWorkerOrManagerResultSettled={refreshAfterWorkspaceResult}
        focusRequest={originNavigation?.originType === 'todo_workspace' ? originNavigation : undefined}
        onDeselectItem={toggleSelected}
      />
    </div>
  );
}
