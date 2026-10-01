export type HomeTimelineItem =
  | {
      kind: 'user_message';
      messageId: string;
      content: string;
      displayMarkdown?: string;
      referencePaths?: string[];
      createdAt: string;
    }
  | { kind: 'conversation_answer'; messageId: string; inReplyTo: string; content: string; createdAt: string }
  | {
      kind: 'agent_task';
      messageId: string;
      inReplyTo: string;
      agentTaskId: string;
      state: 'queued' | 'running' | 'completed' | 'failed' | 'canceled';
      result?: string;
      outcome?: string;
      createdAt: string;
    };

export type BasilBoardTabDetachBehavior = 'useBoardWindow' | 'useNativeWindow' | 'none';

export interface BasilBoardTab {
  id: string;
  title: string;
  icon_key?: string | null;
  position: number;
  tab_kind: 'home' | 'capability' | 'system_embed' | 'agent_report';
  status: 'active' | 'archived';
  configuration: Record<string, unknown>;
}

export interface BoardInquirySummary {
  id: string;
  promptText: string;
  displayMarkdown?: string | null;
  referencePaths: string[];
  routeKind?: 'conversation' | 'agent_task' | null;
  routeReason?: string | null;
  routeConfidence?: number | null;
  state: 'routing' | 'running' | 'completed' | 'failed' | 'canceled';
  conversationId?: string | null;
  agentTaskId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface BoardInquiryDetail extends BoardInquirySummary {
  timeline: HomeTimelineItem[];
}

export interface BasilBoardHydration {
  tabs: BasilBoardTab[];
  recent_inquiries: BoardInquirySummary[];
  supported_tab_kinds: string[];
  supported_renderer_kinds: string[];
}

export interface HomeTurnResponse {
  inquiry_id: string;
  user_message_id: string;
  route_kind: 'conversation' | 'agent_task';
  route_reason: string;
  route_confidence?: number | null;
  state: 'routing' | 'running' | 'completed' | 'failed' | 'canceled';
  assistant_message_id?: string | null;
  agent_task_id?: string | null;
  assistant_content?: string | null;
}

export interface AgentOriginStatusSummary {
  agent_task_id: string;
  status: string;
  result_severity?: string | null;
  is_active: boolean;
  updated_at: string;
}

export interface ConversationListItem {
  id: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview?: string | null;
  agent_status?: AgentOriginStatusSummary | null;
}

export interface ConversationFileReference {
  filename: string;
  path: string;
  file_type: string;
  file_size: number;
}

export interface ConversationMessageItem {
  id: string;
  role: string;
  content: string;
  timestamp: string;
  model_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface ConversationSubmission {
  requestId: string;
  messageId: string;
  content: string;
  displayMarkdown: string;
  conversationId?: string;
  modelId?: string;
  filePaths: string[];
  delegationOptOut: boolean;
  source: 'composer' | 'voice';
}

export type TodoStatus = 'candidate' | 'open' | 'in_progress' | 'ready_for_review' | 'completed' | 'dismissed' | 'canceled';
export type TodoResponsibility = 'user' | 'agent' | 'shared' | 'unspecified';
export type TodoPriority = 'low' | 'normal' | 'high';

export interface TodoAttention {
  needs_attention: boolean;
  reason?: string | null;
}

export interface TodoItemSummary {
  id: string;
  title: string;
  status: TodoStatus;
  responsibility: TodoResponsibility;
  priority: TodoPriority;
  due_at?: string | null;
  completed_at?: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  attention: TodoAttention;
  agent_status?: AgentOriginStatusSummary | null;
}

export interface TodoSource {
  id: string;
  todo_id: string;
  source_kind: string;
  source_id: string;
  source_locator: Record<string, unknown>;
  source_excerpt: string;
  created_by_kind: 'user' | 'agent' | 'system';
  created_at: string;
}

export interface TodoReference {
  id: string;
  todo_id: string;
  path: string;
  created_by_kind: 'user' | 'agent' | 'system';
  created_by_id?: string | null;
  created_at: string;
}

export interface TodoWorkAttempt {
  agent_task_id: string;
  title?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  result_summary?: string | null;
  outcome?: string | null;
  result_severity?: string | null;
  attention: boolean;
}

export interface TodoItemDetail extends TodoItemSummary {
  description: string;
  notes: string;
  idempotency_key?: string | null;
  created_by_kind: 'user' | 'agent' | 'system';
  created_by_id?: string | null;
  sources: TodoSource[];
  references: TodoReference[];
  worker_attempts: TodoWorkAttempt[];
}

export interface TodoWorkerLaunchResponse {
  item: TodoItemDetail;
  agent_task_id: string;
}

export interface TodoWorkspaceHydration {
  items: TodoItemSummary[];
  next_cursor?: string | null;
  has_more: boolean;
  counts_by_status: Record<string, number>;
}

export interface TodoConflictResponse {
  detail: string;
  item: TodoItemDetail;
}

export interface TodoWorkspaceMessage {
  workspaceId: string;
  requestId: string;
  message: string;
  selectedTodoIds: string[];
  referencePaths: string[];
  transcript: Array<{ role: 'user' | 'assistant'; content: string }>;
  modelId?: string;
}

export interface TodoWorkspaceAcceptedEvent {
  event_type: 'todo_workspace_accepted';
  workspace_id: string;
  request_id: string;
  agent_task_id: string;
}

export interface TodoWorkspaceResultEvent {
  event_type: 'todo_workspace_result';
  workspace_id: string;
  request_id: string;
  agent_task_id: string;
  status: string;
  summary: string;
  selected_todo_ids: string[];
}

export interface TodoWorkspaceErrorEvent {
  event_type: 'todo_workspace_error';
  workspace_id: string;
  request_id: string;
  message: string;
}

export type ConversationConnectionState = 'connecting' | 'open' | 'closed';
import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme';
export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string;
  primary: string;
  secondary: string;
  textPrimary: string;
};
export type FontConfig = SharedFontConfig & {
  fontFamily: string;
  fontFamilyMedium: string;
  fontFamilyBold: string;
};

export interface MeetingListItem {
  id: string;
  name: string;
  start_time: string;
  end_time?: string | null;
  duration_seconds?: number | null;
  participants?: string[];
}

export interface BasilBoardInitPayload {
  apiBaseUrl: string;
  theme: ThemeConfig;
  fonts: FontConfig;
  detachedTabId?: string;
  initialConversationId?: string;
  conversationPresentation?: 'global' | 'thread';
}

export type BasilBoardVoiceCaptureState = 'idle' | 'starting' | 'recording' | 'processing' | 'error';
export type HomeVoiceCaptureState = BasilBoardVoiceCaptureState;
export type ConversationVoiceCaptureState = BasilBoardVoiceCaptureState;

export interface VoiceCaptureStatePayload {
  state: BasilBoardVoiceCaptureState;
  level?: number;
  error?: string;
}

export interface VoiceCaptureFinishedPayload {
  transcription?: string;
  error?: string;
}

export type HomeVoiceCaptureStatePayload = VoiceCaptureStatePayload;
export type HomeVoiceCaptureFinishedPayload = VoiceCaptureFinishedPayload;
export type ConversationVoiceCaptureStatePayload = VoiceCaptureStatePayload;
export type ConversationVoiceCaptureFinishedPayload = VoiceCaptureFinishedPayload;

export interface AgentTaskWidgetLaunchPayload {
  agentTaskId: string;
}

export interface WidgetLaunchFailedPayload {
  reason: string;
  message: string;
}

export interface DetachedTabsChangedPayload {
  detachedTabIds: string[];
}

export interface AgentTaskOriginNavigationPayload {
  originType: 'todo' | 'todo_workspace' | 'scheduled_task' | 'meeting' | 'conversation';
  originId: string;
}

export type BoardAgentTasksAvailability = 'embedded' | 'separate_window';

export interface BoardAgentTasksAvailabilityPayload {
  availability: BoardAgentTasksAvailability;
}

export type BoardMeetingsAvailability = 'embedded' | 'separate_window';

export interface BoardMeetingsAvailabilityPayload {
  availability: BoardMeetingsAvailability;
}

export type BoardConversationAvailability = 'available' | 'unavailable';

export interface BoardConversationAvailabilityPayload {
  availability: BoardConversationAvailability;
}

/**
 * Ids of conversations currently open in their own detached window. Mirrors
 * `DetachedTabsChangedPayload`, but scoped per-conversation (rather than
 * per-Board-tab) so the Chats tab can keep browsing other conversations
 * while showing a "this conversation is open in a separate window"
 * placeholder only for the specific conversation that is detached.
 */
export interface DetachedConversationsChangedPayload {
  conversationIds: string[];
}

export type ConversationAgentActivityLifecycle =
  | 'capturing'
  | 'routing'
  | 'routed'
  | 'processing'
  | 'awaiting_provider_delegation'
  | 'awaiting_delegated_agents'
  | 'awaiting_user_input'
  | 'waiting_user_input'
  | 'needs_clarification'
  | 'clarification_added'
  | 'completed'
  | 'failed'
  | 'canceled';

export type ConversationAgentActivityArtifactKind = 'file' | 'directory' | 'unknown';
export type ConversationAgentActivityArtifactLifecycle = 'discovered' | 'ready' | 'verified' | 'failed' | 'unavailable';
export type ConversationAgentActivityArtifactVerificationStatus = 'not_applicable' | 'pending' | 'verified' | 'failed' | 'unknown';
export type ConversationAgentActivityVerificationStatus = 'pending' | 'resolved' | 'unknown';

export interface ConversationAgentActivityWorkflow {
  completed_steps?: number;
  total_steps?: number;
}

export interface ConversationAgentActivityArtifact {
  artifact_id: string;
  display_name: string;
  artifact_kind: ConversationAgentActivityArtifactKind;
  lifecycle: ConversationAgentActivityArtifactLifecycle;
  verification: {
    status: ConversationAgentActivityArtifactVerificationStatus;
  };
}

export interface ConversationAgentActivitySummary {
  agent_task_id: string;
  lifecycle: ConversationAgentActivityLifecycle;
  latest_activity?: string;
  workflow: ConversationAgentActivityWorkflow;
  artifacts: ConversationAgentActivityArtifact[];
  artifact_count: number;
  verification_status: ConversationAgentActivityVerificationStatus;
  requires_user_attention: boolean;
}

export interface WSEvent {
  event_type?: string;
  agent_task_id?: string;
  root_task_id?: string;
  success?: boolean;
  status?: string;
  step?: string;
  details?: string;
  description?: string;
  completion_message?: string;
  result?: string;
  error?: string;
  outcome?: string;
  message?: string;
  message_id?: string;
  message_type?: string;
  conversation_id?: string;
  request_id?: string;
  model_id?: string;
  token?: string;
  chunk_id?: number;
  is_final?: boolean;
  canceled?: boolean;
  attempt_count?: number;
  placeholder_message_id?: string;
  lifecycle?: string;
  status_text?: string;
  terminal_outcome?: string;
  deep_link_id?: string;
  agent_status?: string;
  narration_state?: string;
  requires_user_attention?: boolean;
  attention_id?: string;
  summary?: ConversationAgentActivitySummary;
  timeline_entry?: Record<string, unknown>;
  agent_task_artifact?: Record<string, unknown>;
}
