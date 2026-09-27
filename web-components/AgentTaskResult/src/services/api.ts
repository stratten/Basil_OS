import type {
  AgentTaskListItem,
  AgentTaskDetail,
  CheckpointField,
  ScheduledAgentTask,
  ScheduledAgentTaskRun,
} from '../types';

let baseUrl = '';

export function setBaseUrl(port: number) {
  baseUrl = `http://localhost:${port}`;
}

export function isApiReady(): boolean {
  return baseUrl.length > 0;
}

export function getBaseUrl(): string {
  return baseUrl;
}

export interface TodoOriginSource {
  source_kind: string;
  source_id: string;
  source_locator: Record<string, unknown>;
}

export interface TodoOriginDetail {
  id: string;
  sources: TodoOriginSource[];
}

export function getTodoOriginDetail(todoId: string): Promise<TodoOriginDetail> {
  return request('GET', `/api/v1/todos/items/${encodeURIComponent(todoId)}`);
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function messageFromErrorPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const record = payload as Record<string, unknown>;
  if (typeof record.message === 'string' && record.message.trim()) {
    return record.message.trim();
  }
  const detail = record.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }
  if (detail && typeof detail === 'object') {
    const detailRecord = detail as Record<string, unknown>;
    if (typeof detailRecord.message === 'string' && detailRecord.message.trim()) {
      return detailRecord.message.trim();
    }
    if (typeof detailRecord.error === 'string' && detailRecord.error.trim()) {
      return detailRecord.error.trim();
    }
  }
  return null;
}

async function responseErrorMessage(method: string, path: string, resp: Response): Promise<string> {
  const fallback = `API ${method} ${path} failed: ${resp.status}`;
  const responseText = await resp.text();
  if (!responseText.trim()) return fallback;
  try {
    const parsed = JSON.parse(responseText) as unknown;
    const parsedMessage = messageFromErrorPayload(parsed);
    return parsedMessage ? `${parsedMessage} (${resp.status})` : fallback;
  } catch {
    return `${responseText.trim()} (${resp.status})`;
  }
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (!baseUrl) {
    throw new Error(`API ${method} ${path} requested before host initialization`);
  }

  let resp: Response;
  try {
    resp = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    await delay(600);
    resp = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  if (!resp.ok) {
    throw new Error(await responseErrorMessage(method, path, resp));
  }
  return resp.json();
}

// History
type AgentTaskListResponse = {
  agentTasks: AgentTaskListItem[];
  total_count: number;
  has_more: boolean;
};

export async function listAgentTasks(
  limit = 50,
  offset = 0,
  status?: string
): Promise<AgentTaskListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) params.set('status', status);
  return request('GET', `/api/v1/agent-tasks/history?${params}`);
}

export async function searchAgentTasks(
  query: string,
  limit = 50,
  offset = 0
): Promise<AgentTaskListResponse> {
  const params = new URLSearchParams({ query, limit: String(limit), offset: String(offset) });
  return request('GET', `/api/v1/agent-tasks/agent-task-history/search?${params}`);
}

export async function getAgentTaskDetail(agentTaskId: string): Promise<AgentTaskDetail> {
  return request('GET', `/api/v1/agent-tasks/${agentTaskId}`);
}

export interface ArtifactRevisionItem {
  revision: number;
  display_name: string;
  content_kind: 'markdown' | 'html' | 'text' | 'code' | 'json' | 'yaml' | 'xml';
  byte_count: number;
  created_at: string;
}

export async function listArtifactRevisions(
  agentTaskId: string,
  artifactId: string
): Promise<{ revisions: ArtifactRevisionItem[] }> {
  return request(
    'GET',
    `/api/v1/agent-tasks/${encodeURIComponent(agentTaskId)}/artifacts/${encodeURIComponent(artifactId)}/revisions`
  );
}

export interface ArtifactRevisionContent extends ArtifactRevisionItem {
  content: string;
  content_sha256: string;
}

export async function getArtifactRevision(
  agentTaskId: string,
  artifactId: string,
  revision: number
): Promise<ArtifactRevisionContent> {
  return request(
    'GET',
    `/api/v1/agent-tasks/${encodeURIComponent(agentTaskId)}/artifacts/${encodeURIComponent(artifactId)}/revisions/${revision}`
  );
}

export async function deleteAgentTask(agentTaskId: string): Promise<{ success: boolean }> {
  return request('DELETE', `/api/v1/agent-tasks/${agentTaskId}?cascade=true`);
}

// Approval
export async function evaluateApproval(
  command: string,
  context?: Record<string, unknown>
): Promise<{
  needs_approval: boolean;
  reason: string;
  risk_level: string;
  is_blocked: boolean;
  block_reason?: string;
}> {
  return request('POST', '/api/v1/agent-tasks/approval/evaluate', { command, context });
}

export interface PendingExecutionApproval {
  approval_id: string;
  agent_task_id: string;
  command: string;
  reason: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  generalized_pattern: string;
  execution_type?: 'shell' | 'applescript' | 'browser_foreground_control';
  script_content?: string | null;
  revision: number;
  context?: Record<string, unknown>;
  risk_metadata?: Record<string, unknown> | null;
}

export interface PendingExecutionApprovalSet {
  approvals: PendingExecutionApproval[];
  orphaned_approval_ids: string[];
}

export async function getPendingExecutionApprovals(
  agentTaskId: string
): Promise<PendingExecutionApprovalSet> {
  return request('GET', `/api/v1/agent-tasks/${agentTaskId}/execution-approvals/pending`);
}

export async function recoverOrphanedExecutionApprovals(
  agentTaskId: string,
  approvalIds: string[],
): Promise<{ cancelled_approval_ids: string[] }> {
  return request(
    'POST',
    `/api/v1/agent-tasks/${agentTaskId}/execution-approvals/recover`,
    { approval_ids: approvalIds },
  );
}

export async function submitApprovalDecision(params: {
  approval_id: string;
  command: string;
  approved: boolean;
  remember_choice: boolean;
  pattern_type?: string;
  description?: string;
  agent_task_id?: string;
  expected_revision?: number;
}): Promise<{ success: boolean; message: string }> {
  return request('POST', '/api/v1/agent-tasks/approval/decide', params);
}

export async function submitBrowserSensitiveFillApproval(params: {
  approval_id: string;
  approved: boolean;
  remember_domain: boolean;
  sensitive_value?: string;
}): Promise<{ success: boolean; message: string }> {
  return request('POST', '/settings/browser-automation/sensitive-value/approve', params);
}

export async function submitProviderPermissionDecision(params: {
  agent_task_id: string;
  interaction_id: string;
  outcome?: 'selected' | 'cancel';
  selected_option_id?: string;
}): Promise<{ success: boolean; message: string }> {
  return request(
    'POST',
    `/api/v1/agent-tasks/${params.agent_task_id}/provider-interactions/${params.interaction_id}/permission-decision`,
    {
      outcome: params.outcome ?? 'selected',
      selected_option_id: params.selected_option_id,
    }
  );
}

// Checkpoint / Sessions
export async function getCheckpointStatus(
  agentTaskId: string
): Promise<{ agent_task_id: string; has_checkpoint: boolean; can_resume: boolean; message: string }> {
  return request('GET', `/api/v1/agent-tasks/sessions/${agentTaskId}/checkpoint-status`);
}

export async function continueSession(
  agentTaskId: string,
  userInput: string,
  metadata?: Record<string, unknown>
): Promise<{ success: boolean; message: string; result?: string }> {
  return request('POST', `/api/v1/agent-tasks/sessions/${agentTaskId}/continue`, {
    agent_task_id: agentTaskId,
    user_input: userInput,
    metadata,
  });
}

export async function addClarification(
  agentTaskId: string,
  clarificationText: string
): Promise<{ success: boolean; agent_task_id: string; message: string; error?: string }> {
  return request('POST', `/api/v1/agent-tasks/${agentTaskId}/clarifications`, {
    agent_task_id: agentTaskId,
    clarification_text: clarificationText,
  });
}

export async function respondToProviderInteraction(
  agentTaskId: string,
  interactionId: string,
  outcome: 'accept' | 'decline' | 'cancel',
  values?: Record<string, string>
): Promise<{ success: boolean; message: string }> {
  return request(
    'POST',
    `/api/v1/agent-tasks/${agentTaskId}/provider-interactions/${interactionId}/respond`,
    { outcome, values }
  );
}

export interface PendingProviderInteraction {
  id: string;
  message: string;
  fields: CheckpointField[];
}

export async function getPendingProviderInteraction(
  agentTaskId: string
): Promise<{ interaction: PendingProviderInteraction | null }> {
  return request('GET', `/api/v1/agent-tasks/${agentTaskId}/provider-interactions/pending`);
}

export interface CancelSessionResponse {
  success: boolean;
  message: string;
  finalized_via_agent: boolean;
  agent_task_id: string;
}

export async function cancelSession(
  agentTaskId: string,
  _reason?: string
): Promise<CancelSessionResponse> {
  return request('POST', `/api/v1/agent-tasks/sessions/${agentTaskId}/cancel`, {
    reason: 'User requested cancellation',
  });
}

// Reasoning models for model selector
export interface ReasoningModel {
  id: string;
  name: string;
  display_name: string;
  provider: string;
  category: 'local' | 'api' | 'custom';
  is_api_model: boolean;
  description?: string;
}

export async function getReasoningModels(): Promise<{
  models: ReasoningModel[];
  current_model: string;
  api_models_enabled: boolean;
}> {
  return request('GET', '/settings/api_models/reasoning');
}

// Text follow-up / process agent task
export async function processAgentTask(params: {
  agent_task: string;
  display_prompt_markdown?: string;
  agent_task_id: string;
  root_task_id?: string;
  previous_task_id?: string;
  reference_paths?: string[];
  model_id?: string;
  local_preview_feedback?: {
    source_artifact_id: string;
    mode: 'static' | 'devServer';
    preview_url: string;
    location_status: 'current' | 'fallback';
    screenshot_path?: string;
    console_evidence?: string;
    session_id?: string;
    session_status?: 'starting' | 'running' | 'stopped' | 'error' | 'denied';
  };
}): Promise<unknown> {
  return request('POST', '/api/v1/agent-tasks/process', params);
}

// Retry
export async function retryAgentTask(
  agentTaskId: string,
  modelId?: string
): Promise<{ success: boolean; agent_task_id: string }> {
  return request('POST', `/api/v1/agent-tasks/${agentTaskId}/retry`, { model_id: modelId });
}

export interface SaveAgentTaskAsSkillResponse {
  slug?: string | null;
  title: string;
  body: string;
  when_to_use: string;
  triggers: string[];
  saved: boolean;
}

export async function saveAgentTaskAsSkill(
  agentTaskId: string,
  payload: {
    title?: string;
    body?: string;
    when_to_use?: string;
    triggers?: string[];
    preview_only?: boolean;
  }
): Promise<SaveAgentTaskAsSkillResponse> {
  return request('POST', `/api/v1/agent-tasks/${agentTaskId}/save-as-skill`, payload);
}

export async function submitAgentTaskFeedback(
  agentTaskId: string,
  payload: { user_rating: -1 | 0 | 1; user_feedback?: string }
): Promise<{ agent_task_id: string; user_rating: number; user_feedback?: string }> {
  return request('POST', `/api/v1/agent-tasks/${agentTaskId}/feedback`, payload);
}

// Scheduled agent tasks
export async function listScheduledAgentTasks(includeInactive = true): Promise<{ agent_tasks: ScheduledAgentTask[] }> {
  const params = new URLSearchParams({ include_inactive: includeInactive ? 'true' : 'false' });
  return request('GET', `/api/v1/agent-task-schedules?${params}`);
}

export async function getScheduledAgentTask(scheduledAgentTaskId: string): Promise<ScheduledAgentTask> {
  return request('GET', `/api/v1/agent-task-schedules/${scheduledAgentTaskId}`);
}

export async function createScheduledAgentTask(payload: {
  title: string;
  agent_task_text: string;
  schedule_type: string;
  schedule_config: Record<string, unknown>;
  timezone: string;
  source_type?: string;
  is_active?: boolean;
  // Optional list of absolute filesystem paths to attach as context
  // for every scheduled run. Omit to create a schedule with no
  // attachments; otherwise the backend serializes the list and
  // forwards it into process_agentTask_direct(reference_paths=...).
  reference_paths?: string[];
}): Promise<ScheduledAgentTask> {
  return request('POST', '/api/v1/agent-task-schedules', payload);
}

export async function updateScheduledAgentTask(
  scheduledAgentTaskId: string,
  payload: Partial<{
    title: string;
    agent_task_text: string;
    schedule_type: string;
    schedule_config: Record<string, unknown>;
    timezone: string;
    is_active: boolean;
    // Replaces the stored attachment list wholesale. Send an empty
    // array to clear all attachments; omit the field entirely to
    // leave the existing list unchanged.
    reference_paths: string[];
  }>
): Promise<ScheduledAgentTask> {
  return request('PATCH', `/api/v1/agent-task-schedules/${scheduledAgentTaskId}`, payload);
}

export async function deleteScheduledAgentTask(scheduledAgentTaskId: string): Promise<{ success: boolean; message: string }> {
  return request('DELETE', `/api/v1/agent-task-schedules/${scheduledAgentTaskId}`);
}

export async function runScheduledAgentTaskNow(
  scheduledAgentTaskId: string
): Promise<{ success: boolean; run_id?: string; error?: string }> {
  return request('POST', `/api/v1/agent-task-schedules/${scheduledAgentTaskId}/run-now`);
}

export async function listScheduledAgentTaskRuns(
  scheduledAgentTaskId: string,
  limit = 100
): Promise<ScheduledAgentTaskRun[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  return request('GET', `/api/v1/agent-task-schedules/${scheduledAgentTaskId}/runs?${params}`);
}

export interface ScheduleInterpretationResponse {
  success: boolean;
  title?: string;
  agent_task_text?: string;
  schedule_type?: string;
  schedule_config?: Record<string, unknown>;
  timezone?: string;
  source_type: string;
  is_active: boolean;
  needs_user_confirmation: boolean;
  clarification_question?: string | null;
  context_id?: string | null;
  error?: string | null;
}

/**
 * Send a natural-language scheduling prompt to the backend interpreter.
 *
 * `userTimezone` is intentionally REQUIRED on the opts argument: the form
 * always has a current timezone in scope (defaulted to the browser-detected
 * IANA zone), and forcing every call site to pass it prevents the silent
 * "no timezone, server falls back to UTC, LLM asks for clarification"
 * round-trip that used to happen when the field was omitted.
 */
export async function interpretScheduledAgentTaskPrompt(
  prompt: string,
  opts: { contextId?: string; userTimezone: string }
): Promise<ScheduleInterpretationResponse> {
  return request('POST', '/api/v1/agent-task-schedules/interpret', {
    prompt,
    context_id: opts.contextId ?? null,
    user_timezone: opts.userTimezone,
  });
}
