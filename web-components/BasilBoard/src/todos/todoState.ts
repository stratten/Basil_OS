import type { TodoItemDetail, TodoItemSummary, TodoWorkspaceResultEvent } from '../contracts';

export type TodoListFilter = 'all' | 'inbox' | 'open' | 'in_progress' | 'ready_for_review' | 'completed';

export function filterToStatuses(filter: TodoListFilter): string[] | undefined {
  if (filter === 'all') return undefined;
  if (filter === 'inbox') return ['candidate'];
  if (filter === 'open') return ['open', 'in_progress', 'ready_for_review'];
  return [filter];
}

export function applyOptimisticConflictReplacement(
  items: TodoItemSummary[],
  latest: TodoItemDetail,
): TodoItemSummary[] {
  const replaced = items.map((item) => (item.id === latest.id ? latest : item));
  if (!replaced.some((item) => item.id === latest.id)) {
    replaced.unshift(latest);
  }
  return replaced;
}

export interface WorkspaceTranscriptMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
}

export interface WorkspaceState {
  workspaceId: string;
  pendingRequestId: string | null;
  transcript: WorkspaceTranscriptMessage[];
}

export function createWorkspaceState(workspaceId: string): WorkspaceState {
  return { workspaceId, pendingRequestId: null, transcript: [] };
}

export function appendUserMessage(state: WorkspaceState, requestId: string, content: string): WorkspaceState {
  return {
    ...state,
    pendingRequestId: requestId,
    transcript: [...state.transcript, { id: requestId, role: 'user', content }],
  };
}

export function applyWorkspaceResult(state: WorkspaceState, event: TodoWorkspaceResultEvent): WorkspaceState {
  if (event.workspace_id !== state.workspaceId || event.request_id !== state.pendingRequestId) {
    return state;
  }
  return {
    ...state,
    pendingRequestId: null,
    transcript: [...state.transcript, { id: `${event.request_id}-assistant`, role: 'assistant', content: event.summary }],
  };
}

export function applyWorkspaceError(
  state: WorkspaceState, workspaceId: string, requestId: string, message: string,
): WorkspaceState {
  if (workspaceId !== state.workspaceId || requestId !== state.pendingRequestId) {
    return state;
  }
  return {
    ...state,
    pendingRequestId: null,
    transcript: [...state.transcript, { id: `${requestId}-error`, role: 'error', content: message }],
  };
}

export function clearWorkspace(newWorkspaceId: string): WorkspaceState {
  return createWorkspaceState(newWorkspaceId);
}
