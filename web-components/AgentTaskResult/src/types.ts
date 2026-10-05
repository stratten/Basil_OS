import type {
  AgentTaskArtifactHttpResponse,
  AgentTaskArtifactPresentation,
  AgentTaskPresentationSummary,
  AgentTaskPresentationSummaryHttpResponse,
  DelegatedProviderReportCard,
} from './artifacts/artifactContract';
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

// Agent lifecycle states
export type AgentStatus =
  | 'capturing'
  | 'routing'
  | 'processing'
  | 'awaitingInput'
  | 'completed'
  | 'failed';

export type ResultSeverity = 'success' | 'warning' | 'error' | 'neutral';

// Bubble animation modes
export type BubbleMode = 'ambient' | 'audioResponsive' | 'processing';

// A single progress step within a workflow
export interface ProgressStep {
  id?: string;
  step: string;
  isActive: boolean;
  isComplete: boolean;
}

export type StepDetailKind =
  | 'tool_input'
  | 'tool_result'
  | 'thinking'
  | 'step_note'
  | 'step_complete'
  | 'artifact'
  | 'error'
  | 'retry'
  | 'final_summary';

export interface StepDetailEntry {
  id: string;
  type?: 'thinking' | 'step' | 'tool_start' | 'tool_complete' | 'artifact';
  timestamp: string;
  content: string;
  step_id?: string;
  correlation_id?: string;
  detail_kind: StepDetailKind | string;
  summary: string;
  body: string;
  metadata?: Record<string, unknown>;
  artifact?: AgentTaskArtifactPresentation;
  streaming?: boolean;
}

export interface ProgressMetadata extends Record<string, unknown> {
  progress_phase?: string;
  progress_current?: number;
  progress_total?: number;
  progress_step?: string;
  progress_status?: string;
}

// Unified execution timeline entry (thinking + steps interleaved chronologically)
export interface TimelineEntry extends Partial<StepDetailEntry> {
  type: 'thinking' | 'step' | 'tool_start' | 'tool_complete' | 'artifact';
  timestamp: string;
  content: string;
  iteration?: number;
  metadata?: ProgressMetadata;
}

export interface DetailSelection {
  ownerTaskId: string;
  detailId: string;
}

// A todo within a workflow plan
export interface WorkflowTodo {
  id: string;
  title: string;
  description: string;
  steps: WorkflowStep[];
}

export interface WorkflowStep {
  id: string;
  description: string;
  planned_service?: string;
  planned_method?: string;
  status?: string;
  result_summary?: string;
}

export interface WorkflowPlan {
  todos: WorkflowTodo[];
}

// Structured file reference from an AgentTask result
export interface StructuredFile {
  name: string;
  path: string;
  operation?: string;
  sourcePath?: string;
  kind?: 'file' | 'directory';
  artifact?: AgentTaskArtifactHttpResponse | null;
}

// A single thinking segment (one iteration of model reasoning)
export interface ThinkingSegment {
  iteration: number;
  text: string;
  isComplete: boolean;
  recordedAt?: string;
}

export interface PersistedThinkingSegment {
  iteration: number;
  text: string;
  is_complete: boolean;
  recorded_at?: string;
}

export function normalizePersistedThinkingSegments(
  segments?: PersistedThinkingSegment[],
): ThinkingSegment[] {
  return (segments || []).map(segment => ({
    iteration: segment.iteration,
    text: segment.text,
    isComplete: segment.is_complete,
    ...(typeof segment.recorded_at === 'string' && segment.recorded_at ? { recordedAt: segment.recorded_at } : {}),
  }));
}

// AgentTask history item (inline, within the result conversation)
export interface AgentTaskHistoryItem {
  id: string;
  agentTaskText: string;
  displayPromptMarkdown?: string;
  originType?: string;
  originId?: string;
  result: string;
  files: StructuredFile[];
  reference_paths: string[];
  timestamp: string;
  thinkingSegments?: ThinkingSegment[];
  executionSteps?: ProgressStep[];
  executionTimeline?: TimelineEntry[];
  stepDetails?: StepDetailEntry[];
  errorMessage?: string;
  outcome?: string;
  resultSeverity?: ResultSeverity;
  status?: AgentStatus | string;
}

// A conversation turn for thread-style rendering
export interface ConversationTurn {
  id: string;
  agentTaskText: string;
  result?: string;
  files: StructuredFile[];
  referencePaths: string[];
  timestamp: string;
  status: AgentStatus | string;
  thinkingSegments: ThinkingSegment[];
  executionSteps: ProgressStep[];
  executionTimeline: TimelineEntry[];
  stepDetails: StepDetailEntry[];
  errorMessage?: string;
  isActive: boolean;
  outcome?: string;
  resultSeverity?: ResultSeverity;
}

// Shared display surface — everything ResultContent / App.tsx reads.
// AgentState extends this; historical agent tasks satisfy it via a mapper.
export interface DisplayableAgentTask {
  agentTaskId: string;
  rootTaskId?: string;
  previousTaskId?: string;
  // The currently displayed/interactive turn within a root-owned chain.
  // `agentTaskId` remains the root store key for live follow-up chains.
  currentTurnTaskId?: string;
  timestamp?: string;
  // Provenance: which application surface created this task (mirrors the
  // backend's `origin_type`/`origin_id` columns). Undefined means directly
  // user-initiated, or not yet resolved for a live task.
  originType?: string;
  originId?: string;
  originalPrompt: string;
  displayPromptMarkdown?: string;
  taskTitle?: string;
  status: AgentStatus | string;
  result: string;
  errorMessage?: string;
  outcome?: string;
  resultSeverity?: ResultSeverity;
  verificationStatus?: 'pending' | 'resolved';
  presentationSummary?: AgentTaskPresentationSummary;
  delegatedProviderReportCards: DelegatedProviderReportCard[];
  structuredFiles: StructuredFile[];
  referencePaths: string[];
  agentTaskHistory: AgentTaskHistoryItem[];
  progressSteps: ProgressStep[];
  executionTimeline: TimelineEntry[];
  stepDetails: StepDetailEntry[];
  currentStep?: string;
  currentActivityPhase?: string;
  workflowPlan?: WorkflowPlan;
  showWorkflowPlan: boolean;
  isStreaming: boolean;
  isCanceling?: boolean;
  isCanceled?: boolean;
  cancellationError?: string;
  checkpointAvailable: boolean;
  thinking?: string;
  thinkingComplete?: boolean;
  thinkingSegments: ThinkingSegment[];
  // Set only when the preferred reasoning model was unreachable before any
  // step succeeded and this task automatically substituted the
  // user-designated local fallback model (see reasoning_fallback_model_used
  // on the backend AgentTaskDetailResponse/AgentTaskChainItem).
  reasoningFallbackModelUsed?: string;
  // The model_id captured in accumulated_artifacts at submission time for
  // this attempt (see model_id on the backend
  // AgentTaskDetailResponse/AgentTaskChainItem). Undefined means the
  // attempt used the ambient system default rather than an explicit
  // override. Read-only; the retry model selector and TextFollowUp use it
  // only as the initial fallback default.
  originalModelId?: string;
  // The model the user has most recently chosen for this task's next retry
  // or follow-up (set by the retry model selector in ResultContent and by
  // TextFollowUp's own model picker). Sticky across both surfaces so a
  // choice made in one carries into the other.
  selectedModelId?: string;
}

// Agent state tracked in the store
export interface AgentState extends DisplayableAgentTask {
  status: AgentStatus;
  hasUnreadResult: boolean;
  timestamp: string;
  /**
   * The retry request has been accepted locally, but a stale durable read may
   * still report the preceding failed attempt. Hydration must preserve the
   * optimistic in-flight state until the retry fails or live/durable
   * in-flight evidence confirms the new attempt.
   */
  isRetryPending?: boolean;

  // Approval state
  approvalRequests: ExecutionApprovalRequest[];
  showApprovalPrompt: boolean;
  rememberApprovalChoice: boolean;
  seenApprovalIds: string[];

  // Checkpoint state
  currentCheckpoint?: CheckpointData;
  showCheckpointPrompt: boolean;
  inlineCheckpoint?: CheckpointData;
}

// Command approval
export interface BrowserSensitiveApprovalMetadata {
  domain?: string;
  url?: string;
  browser?: string;
  field_label?: string;
  field_type?: string;
  selector_redacted?: string;
  value_source?: 'agent_argument' | 'user_entry' | string;
  will_remember_domain_allowed?: boolean;
}

export interface ProviderPermissionApprovalMetadata {
  interaction_id: string;
  provider_run_id: string;
  agent_task_id: string;
  subject: Record<string, unknown> | null;
  allow_option_id: string | null;
  reject_option_id: string;
}

export interface CommandInputMetadata {
  request_id: string;
  agent_task_id: string;
  prompt: string;
  secret: boolean;
  command?: string;
  created_at?: number;
  expires_at?: number;
}

export interface ExecutionApprovalRequest {
  approval_id: string;
  agent_task_id: string;
  command: string;
  reason: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  generalized_pattern?: string;
  risk_metadata?: Record<string, unknown>;
  script_content?: string;
  execution_type?: 'shell' | 'applescript' | 'browser_foreground_control' | 'browser_sensitive_fill' | 'provider_permission' | 'command_input';
  browser_metadata?: BrowserSensitiveApprovalMetadata;
  provider_permission?: ProviderPermissionApprovalMetadata;
  command_input?: CommandInputMetadata;
  revision?: number;
}

// Checkpoint

// A single selectable option for a `choice` checkpoint. The backend emits
// options either as plain strings or (potentially, in the future) as richer
// objects; websocketHandlers.normalizeCheckpointPayload normalizes both forms
// into this shape so the UI has a durable model to render selectable cards.
export interface CheckpointOption {
  id: string;
  label: string;
  value: string;
  description?: string;
  variant?: 'default' | 'primary' | 'warning' | 'danger';
}

export interface BrowserPermissionRepairMetadata {
  source: 'browser_permission_repair';
  permission_kind?: string;
  browser?: string;
  action?: string;
  next_actions?: string[];
  allow_foreground_option?: boolean;
  raw_error?: string;
  context_summary?: string;
}

export interface ProviderUserInputMetadata {
  source: 'provider_user_input';
  provider_run_id?: string;
}

export interface ProviderTargetAuthorizationMetadata {
  source: 'provider_target_authorization';
  authorization_id: string;
  cancel_value: string;
}

// One field of a multi-field provider elicitation form (Package 4A). Mirrors
// the backend's flattened `elicitation/create` JSON Schema: a plain text
// field, or a single-select field with `options` drawn from a string enum.
export interface CheckpointField {
  name: string;
  label: string;
  kind: 'text' | 'choice';
  required: boolean;
  default_value?: string;
  options?: CheckpointOption[];
}

export interface CheckpointData {
  checkpoint_id: string;
  session_agent_task_id?: string;
  prompt: string;
  input_type: 'confirmation' | 'data' | 'file' | 'review' | 'choice' | 'provider_form';
  options?: CheckpointOption[];
  allow_multiple?: boolean;
  value_kind?: 'numeric';
  fields?: CheckpointField[];
  default_value?: string;
  metadata?: Record<string, unknown> | BrowserPermissionRepairMetadata | ProviderUserInputMetadata | ProviderTargetAuthorizationMetadata;
}

// History list item (sidebar)
export interface AgentTaskListItem {
  id: string;
  original_prompt: string;
  title?: string;
  result_preview?: string;
  timestamp: string;
  status: string;
  outcome?: string;
  result_severity?: ResultSeverity;
  file_count: number;
  app_name?: string;
  follow_up_count: number;
  origin_type?: 'conversation' | 'scheduled_task' | string;
  origin_id?: string;
  is_scheduled_run?: boolean;
  scheduled_agent_task_id?: string;
  scheduled_agent_task_title?: string;
}

export interface ScheduledAgentTask {
  id: string;
  title: string;
  agent_task_text: string;
  schedule_type: 'one_time' | 'recurring' | string;
  schedule_config: Record<string, unknown>;
  timezone: string;
  is_active: boolean;
  source_type: 'manual' | 'smart' | string;
  // Absolute filesystem paths attached to the schedule. Forwarded into
  // process_agent_task_direct(reference_paths=...) at every scheduled run.
  // Always present on responses (defaults to []); optional on
  // create/update payloads where omission means "leave unchanged" and
  // an empty array means "clear all".
  reference_paths: string[];
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  created_at: string;
  updated_at: string;
  run_count: number;
  last_scheduled_for?: string | null;
}

export interface ScheduledAgentTaskRun {
  id: string;
  scheduled_agent_task_id: string;
  agent_task_id?: string | null;
  scheduled_for: string;
  started_at?: string | null;
  completed_at?: string | null;
  status: string;
  error_message?: string | null;
  created_at: string;
}

// Full AgentTask details (loaded on selection)
export interface AgentTaskDetail {
  id: string;
  original_prompt: string;
  transcribed_prompt: string;
  display_prompt_markdown?: string;
  title?: string;
  origin_type?: 'conversation' | 'scheduled_task' | string;
  origin_id?: string;
  timestamp: string;
  status: string;
  outcome?: string;
  result_severity?: ResultSeverity;
  result_message?: string;
  app_name?: string;
  window_title?: string;
  files: StructuredFile[];
  agent_task_presentation_summary?: AgentTaskPresentationSummaryHttpResponse | null;
  reference_paths: string[];
  root_task_id?: string;
  previous_task_id?: string;
  follow_ups: AgentTaskFollowUp[];
  error_message?: string;
  execution_timeline?: TimelineEntry[];
  thinking_history?: PersistedThinkingSegment[];
  checkpoint_data?: Record<string, unknown>;
  reasoning_fallback_model_used?: string;
  model_id?: string;
}

export interface AgentTaskFollowUp {
  id: string;
  original_prompt: string;
  display_prompt_markdown?: string;
  timestamp: string;
  status: string;
  outcome?: string;
  result_severity?: ResultSeverity;
  result_message?: string;
  files: StructuredFile[];
  agent_task_presentation_summary?: AgentTaskPresentationSummaryHttpResponse | null;
  reference_paths: string[];
  root_task_id?: string;
  previous_task_id?: string;
  chain_sequence_number: number;
  error_message?: string;
  execution_timeline?: TimelineEntry[];
  thinking_history?: PersistedThinkingSegment[];
  reasoning_fallback_model_used?: string;
  model_id?: string;
}

// Swift → JS messages
export interface InitMessage {
  wsUrl: string;
  port: number;
  theme: ThemeConfig;
  fonts: FontConfig;
  initiallyProcessing?: boolean;
  initialAgentTaskId?: string;
  initialAgentTask?: string;
  initialReferencePaths?: string[];
  initialSidebarExpanded?: boolean;
  dateDisplayStyle?: string;
  detachedRootTaskId?: string;
  embedded?: boolean;
}

export interface ValidationRunFocusRequest {
  requestId: string;
  runId?: string;
}

export interface ValidationRunFocusState {
  requestId: string;
  rootTaskId: string;
  runId: string;
  requestText: string;
  resultText: string;
  documentPaths: string[];
  artifactIds: string[];
  previewArtifactId: string | null;
  isOverviewOpen: boolean;
}

export interface RegisterNewAgentMessage {
  agentTaskId: string;
  rootTaskId?: string;
  previousTaskId?: string;
  referencePaths?: string[];
}

export interface FilePreviewInitMessage {
  path: string;
  /** Backend HTTP port, present whenever the host has a running backend. Passed to `setBaseUrl` so this window can call the managed-history API directly, the same way LocalWebPreviewApp already does. */
  port?: number;
  /** Present when this window was opened from a specific agent task's artifact list; used to pre-select that run's version and as restore provenance. */
  agentTaskId?: string;
  /** Present when this window was opened from the run detail tray; required to enable the restore button. */
  rootTaskId?: string;
  theme?: ThemeConfig;
  fonts?: FontConfig;
}

export interface CaptureStateMessage {
  type: 'followUp' | 'newAgentTask' | 'refinement';
  isCapturing: boolean;
  wordsDetected: string;
  audioLevel: number;
  silenceProgress: number;
}

// JS → Swift messages
export type SwiftMessage =
  | { type: 'resultWidgetReady' }
  | { type: 'closeWidget' }
  | { type: 'minimizeWidget' }
  | { type: 'widgetHeaderHeight'; height: number }
  | { type: 'cancelRunningAgentTask'; agentTaskId: string }
  | { type: 'reportAgentTaskCancellationStage'; agentTaskId: string; stage: string }
  | {
      type: 'requestResize';
      width: number;
      height: number;
      resizeIntent?: 'content' | 'collapsed' | 'expanded' | 'layout';
      minimumWidth?: number;
    }
  | { type: 'startFollowUpCapture'; rootTaskId: string; previousTaskId?: string }
  | { type: 'stopFollowUpCapture' }
  | { type: 'cancelFollowUpCapture' }
  | { type: 'startNewAgentTaskCapture'; preGeneratedId: string }
  | { type: 'stopNewAgentTaskCapture' }
  | { type: 'cancelNewAgentTaskCapture' }
  | { type: 'startRefinementRecording' }
  | { type: 'stopRefinementRecording' }
  | { type: 'copyToClipboard'; text: string }
  | { type: 'copyRichTextToClipboard'; text: string }
  | { type: 'openFile'; path: string }
  | { type: 'previewFile'; requestId: string; path: string }
  | { type: 'checkFilePreviewAvailability'; requestId: string; paths: string[] }
  | { type: 'openFilePreviewWindow'; path: string; agentTaskId?: string; rootTaskId?: string }
  | {
      type: 'openLocalWebPreview';
      mode: 'static' | 'devServer';
      targetUrl: string;
      artifactId: string;
      agentTaskId: string;
      rootTaskId?: string;
      canonicalPath?: string;
      sessionId?: string;
      displayName?: string;
    }
  | { type: 'openContainingFolder'; path: string }
  | { type: 'filePreviewChromeHeight'; height: number }
  | {
      type: 'setInlineNativePreviewFrame';
      requestId: string;
      frame: {
        left: number;
        top: number;
        width: number;
        height: number;
        viewportWidth: number;
        viewportHeight: number;
      };
    }
  | { type: 'hideInlineNativePreview'; requestId: string }
  | { type: 'clearInlineNativePreview'; requestId: string }
  | { type: 'clearFilePreview'; requestId: string }
  | { type: 'openExternalUrl'; url: string }
  | { type: 'openDetachedAgentTask'; rootTaskId: string }
  | { type: 'openAgentTaskOrigin'; originType: string; originId: string }
  | { type: 'pickFiles' }
  | {
      type: 'agentStatusChanged';
      isProcessing: boolean;
      hasResult: boolean;
      isTerminal: boolean;
      // Identifier of the row currently focused in the React sidebar.
      // Read by the Swift hotkey handler to decide whether to start a
      // follow-up against the focused row vs. spawn a new capture
      // widget. `null` when nothing is focused (e.g., empty sidebar).
      agentTaskId?: string | null;
      // True iff the focused row is in a state that can accept a
      // follow-up: completed/failed regular agents qualify; processing
      // agents and scheduled-run detail views do not. Read by the
      // Swift hotkey handler in tandem with `agentTaskId`.
      supportsFollowUp?: boolean;
    }
  | {
      type: 'validationRunFocused';
      requestId: string;
      rootTaskId: string;
      runId: string;
      requestText: string;
      resultText: string;
      documentPaths: string[];
      artifactIds: string[];
      previewArtifactId: string | null;
      isOverviewOpen: boolean;
    };

// WebSocket event types from the backend
export type WSEventType =
  | 'agent_task_progress'
  | 'agent_task_result'
  | 'agent_task_streaming'
  | 'agent_task_streaming_complete'
  | 'agent_task_canceled'
  | 'agent_task_capture_started'
  | 'agent_task_capture_complete'
  | 'agent_task_word_detected'
  | 'agent_task_silence_progress'
  | 'agent_task_outcome_update'
  | 'step_progress_update'
  | 'dynamic_step_added'
  | 'dynamic_step_updated'
  | 'agent_task_step_detail'
  | 'agent_progress_update'
  | 'collaborative_checkpoint_request'
  | 'checkpoint_waiting'
  | 'checkpoint_resumed'
  | 'session_context_info'
  | 'execution_approval_request'
  | 'agent_task_blocker_waiting'
  | 'agent_task_blocker_resolved'
  | 'agent_task_provisional_failed'
  | 'agent_task_origin'
  | 'delegated_provider_report_cards'
  | 'agent_task_artifact'
  | 'scheduled_agent_task_run_started'
  | 'scheduled_agent_task_run_completed'
  | 'scheduled_agent_task_missed';

export interface WSEvent {
  event_type: WSEventType;
  agent_task_id?: string;
  [key: string]: unknown;
}
