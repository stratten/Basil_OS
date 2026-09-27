import type {
  BasilBoardHydration,
  BoardInquiryDetail,
  ConversationListItem,
  ConversationMessageItem,
  HomeTurnResponse,
  MeetingListItem,
  TodoItemDetail,
  TodoWorkerLaunchResponse,
  TodoWorkspaceHydration,
} from '../contracts';
import type { AgentTaskDetail } from '@agent-task/types';
import { setBaseUrl as setAgentTaskApiBaseUrl } from '@agent-task/services/api';

let apiBaseUrl = 'http://127.0.0.1:8000';

export type TodoSortColumn = 'created_at' | 'updated_at' | 'due_at' | 'title' | 'status' | 'priority';
export type TodoSortDirection = 'asc' | 'desc';
export interface TodoSortBy {
  column: TodoSortColumn;
  /** Omitted means "use the column's own sensible default direction",
   * matching the backend's `sort_direction`-optional contract. */
  direction?: TodoSortDirection;
}
export interface TodoWorkspacePageOptions {
  query?: string;
  statuses?: string[];
  limit?: number;
  cursor?: string;
}
/** `listTodoItems` is cursor-paginated and only ever sorts by a single
 * monotonic column; it is intentionally not widened alongside the
 * `/workspace` endpoint's flexible sort (see plan-sanctioned deferrals). */
export type TodoItemsSortBy = 'created_at' | 'updated_at';

export function configureApiBaseUrl(baseUrl: string): void {
  apiBaseUrl = baseUrl.replace(/\/$/, '');
  setAgentTaskApiBaseUrl(new URL(apiBaseUrl).port ? Number(new URL(apiBaseUrl).port) : 80);
}

export function getApiBaseUrl(): string {
  return apiBaseUrl;
}

export interface ReasoningModel {
  id: string;
  name: string;
  display_name: string;
  provider: string;
  category: 'local' | 'api' | 'custom';
  is_api_model: boolean;
  description?: string;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function hydrateBasilBoard(): Promise<BasilBoardHydration> {
  return requestJson<BasilBoardHydration>('/api/v1/basil-board/hydrate');
}

export function getBoardInquiry(inquiryId: string): Promise<BoardInquiryDetail> {
  return requestJson<BoardInquiryDetail>(`/api/v1/basil-board/inquiries/${inquiryId}`);
}

export function hydrateTodoWorkspace(
  sortBy: TodoSortBy = { column: 'created_at' },
  options: TodoWorkspacePageOptions = {},
): Promise<TodoWorkspaceHydration> {
  const query = new URLSearchParams({
    sort_by: sortBy.column,
    limit: String(options.limit ?? 50),
  });
  if (sortBy.direction) query.set('sort_direction', sortBy.direction);
  if (options.query) query.set('query', options.query);
  options.statuses?.forEach((status) => query.append('status', status));
  if (options.cursor) query.set('cursor', options.cursor);
  return requestJson<TodoWorkspaceHydration>(`/api/v1/todos/workspace?${query.toString()}`);
}

export function listTodoItems(
  status?: string,
  sortBy: TodoItemsSortBy = 'created_at',
): Promise<{ items: TodoItemDetail[]; next_cursor: string | null }> {
  const query = new URLSearchParams({ sort_by: sortBy });
  if (status) query.set('status', status);
  return requestJson(`/api/v1/todos/items?${query.toString()}`);
}

export function getTodoAgentStatuses(todoIds: string[]): Promise<Record<string, unknown | null>> {
  if (todoIds.length === 0) return Promise.resolve({});
  return requestJson(`/api/v1/todos/agent-status?ids=${encodeURIComponent(todoIds.join(','))}`);
}

export function getConversationAgentStatuses(conversationIds: string[]): Promise<Record<string, unknown | null>> {
  if (conversationIds.length === 0) return Promise.resolve({});
  return requestJson(`/conversation/agent-status?ids=${encodeURIComponent(conversationIds.join(','))}`);
}

export function getTodoItem(todoId: string): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}`);
}

export function createTodoItem(body: {
  title: string;
  description?: string;
  notes?: string;
  responsibility?: string;
  priority?: string;
  due_at?: string | null;
  idempotency_key: string;
}): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>('/api/v1/todos/items', { method: 'POST', body: JSON.stringify(body) });
}

export function updateTodoItem(
  todoId: string,
  body: { expected_revision: number } & Record<string, unknown>,
): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function deleteTodoItem(todoId: string, expectedRevision: number): Promise<{ id: string }> {
  return requestJson<{ id: string }>(`/api/v1/todos/items/${encodeURIComponent(todoId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function replaceTodoNotes(todoId: string, notes: string, expectedRevision: number): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/notes`, {
    method: 'PUT',
    body: JSON.stringify({ notes, expected_revision: expectedRevision }),
  });
}

export function addTodoReference(todoId: string, path: string, expectedRevision: number): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/references`, {
    method: 'POST',
    body: JSON.stringify({ path, expected_revision: expectedRevision }),
  });
}

export function removeTodoReference(
  todoId: string,
  referenceId: string,
  expectedRevision: number,
): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(
    `/api/v1/todos/items/${encodeURIComponent(todoId)}/references/${encodeURIComponent(referenceId)}`,
    {
      method: 'DELETE',
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  );
}

export function acceptTodoCandidate(todoId: string, expectedRevision: number): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/accept`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function dismissTodoCandidate(todoId: string, expectedRevision: number): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/dismiss`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function completeTodoItem(todoId: string, expectedRevision: number): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/complete`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function reopenTodoItem(todoId: string, expectedRevision: number): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/reopen`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function cancelTodoItem(todoId: string, expectedRevision: number): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function launchTodoWorker(todoId: string, expectedRevision: number): Promise<TodoWorkerLaunchResponse> {
  return requestJson<TodoWorkerLaunchResponse>(`/api/v1/todos/items/${encodeURIComponent(todoId)}/workers`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function promoteMeetingProposalToTodo(body: {
  meeting_id: string;
  filename: string;
  proposal_id: string;
  source_task: string;
  suggested_agent_task: string;
  why_basil_can_help?: string;
  source_context?: string | null;
}): Promise<TodoItemDetail> {
  return requestJson<TodoItemDetail>('/api/v1/todos/meeting-proposals/promote', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export interface SubmitHomeTurnPayload {
  content: string;
  displayMarkdown?: string;
  referencePaths?: string[];
  modelId?: string;
}

export function submitHomeTurn(payload: SubmitHomeTurnPayload): Promise<HomeTurnResponse> {
  return requestJson<HomeTurnResponse>('/api/v1/basil-board/home/turn', {
    method: 'POST',
    body: JSON.stringify({
      content: payload.content,
      display_prompt_markdown: payload.displayMarkdown ?? undefined,
      reference_paths: payload.referencePaths ?? [],
      model_id: payload.modelId ?? undefined,
    }),
  });
}

export function reconcileHomeTurn(messageId: string): Promise<HomeTurnResponse> {
  return requestJson<HomeTurnResponse>(`/api/v1/basil-board/home/turns/${messageId}`);
}

export function getReasoningModels(): Promise<{
  models: ReasoningModel[];
  current_model: string;
  api_models_enabled: boolean;
}> {
  return requestJson('/settings/api_models/reasoning');
}

export interface ConversationPageResponse {
  conversations: ConversationListItem[];
  has_more: boolean;
  next_cursor?: string | null;
}

export interface ListConversationPageOptions {
  query?: string;
  cursor?: string;
  limit?: number;
}

export function listConversationPage(
  options: ListConversationPageOptions = {},
): Promise<ConversationPageResponse> {
  const params = new URLSearchParams({ limit: String(options.limit ?? 30) });
  const query = options.query?.trim();
  if (query) params.set('query', query);
  if (options.cursor) params.set('cursor', options.cursor);
  return requestJson<ConversationPageResponse>(`/conversation/page?${params.toString()}`);
}

export interface ConversationHistoryResponse {
  conversation_id: string;
  messages: ConversationMessageItem[];
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export function getConversationMessages(conversationId: string): Promise<ConversationHistoryResponse> {
  return requestJson<ConversationHistoryResponse>(`/conversation/${encodeURIComponent(conversationId)}`);
}

export function getConversationAgentTaskDetail(agentTaskId: string): Promise<AgentTaskDetail> {
  return requestJson<AgentTaskDetail>(`/api/v1/agent-tasks/${encodeURIComponent(agentTaskId)}`);
}

export function deleteConversation(conversationId: string): Promise<{ status: string; message: string }> {
  return requestJson<{ status: string; message: string }>(
    `/conversation/${encodeURIComponent(conversationId)}`,
    { method: 'DELETE' },
  );
}

export function listMeetings(): Promise<MeetingListItem[]> {
  return requestJson<MeetingListItem[]>('/meetings');
}

export function websocketUrl(): string {
  const wsBase = apiBaseUrl.replace(/^http/, 'ws');
  return `${wsBase}/ws`;
}
