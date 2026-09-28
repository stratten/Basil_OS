export type SetupAssistantPhase =
  | 'permission_preflight'
  | 'setup_interview'
  | 'deterministic_discovery'
  | 'agent_synthesis'
  | 'recommendation_review'
  | 'model_setup'
  | 'task_offers'
  | 'completion'

export type SetupTechnicalDepth = 'plain' | 'practical' | 'technical'

export type SetupAgentModelAccessMode = 'local' | 'provider_key' | 'basil_cloud'

export type SetupCalibrationEventKind =
  | 'continue'
  | 'confused'
  | 'more_detail'
  | 'prefer_local'
  | 'manual_model_choice'

export type SetupApprovalState = 'pending' | 'approved' | 'skipped' | 'deferred' | 'applied' | 'failed'

export type SetupPrivacyImpact =
  | 'none'
  | 'local_only'
  | 'reads_local_data'
  | 'uses_cloud_model'
  | 'controls_applications'
  | 'creates_external_draft'
  | 'modifies_settings'
  | 'launches_real_task'
  | 'authenticates_service'

export type SetupActionKind =
  | 'save_profile'
  | 'save_writing_samples'
  | 'update_settings'
  | 'start_model_downloads'
  | 'start_connection_auth'
  | 'refresh_connection_tools'
  | 'launch_agent_task'
  | 'launch_assistant_session'
  | 'run_approved_action_sequence'
  | 'open_system_settings'
  | 'defer_recommendation'
  | 'no_mutation'

export interface SetupDiscoveryFact {
  id: string
  source: string
  kind: string
  value: string
  confidence: number
  collected_at: string
  requires_permission?: string | null
  user_visible_summary: string
  metadata: Record<string, string>
}

export interface SetupDiscoveryResponse {
  facts: SetupDiscoveryFact[]
  collected_at: string
}

export interface SetupAction {
  id: string
  kind: SetupActionKind
  payload: Record<string, unknown>
  requires_explicit_approval: boolean
  mutates_external_state: boolean
}

export interface SetupActionSequenceValidationResponse {
  actions: SetupAction[]
}

export type SetupExecutionStatus = 'applied' | 'executed' | 'failed' | 'skipped'

export interface SetupActionExecutionItem {
  id: string
  kind: string
  status: SetupExecutionStatus
  message: string
  result_payload: Record<string, unknown>
}

export interface SetupActionExecutionResponse {
  results: SetupActionExecutionItem[]
}

export interface SetupModelDownloadStatusItem {
  id: string
  model: string
  status: string
  progress: number
  timestamp?: number
  error?: string | null
}

export interface SetupModelDownloadStatusResponse {
  tasks: SetupModelDownloadStatusItem[]
}

export interface SetupAgentModelAccess {
  mode: SetupAgentModelAccessMode
  local_model_id?: string | null
  provider?: string | null
  model_id?: string | null
  resolved: boolean
}

export interface SetupAgentModelAccessOption {
  mode: SetupAgentModelAccessMode
  available: boolean
  unavailable_reason?: string | null
  local_model_id?: string | null
  provider?: string | null
  model_id?: string | null
  display_name?: string | null
  requires_provider_key_input: boolean
  provider_models?: SetupAgentProviderModelChoice[]
}

export interface SetupAgentProviderModelChoice {
  provider: string
  model_id: string
  display_name: string
  recommended: boolean
}

export interface SetupAgentModelAccessOptionsResponse {
  options: SetupAgentModelAccessOption[]
}

export interface SetupAgentModelAccessSelectRequest {
  mode: SetupAgentModelAccessMode
  local_model_id?: string | null
  provider?: string | null
  model_id?: string | null
  provider_api_key?: string | null
}

export interface SetupAgentModelAccessSelectResponse {
  access: SetupAgentModelAccess
  model_metadata: SetupAgentModelMetadata
}

export interface SetupCalibrationEvent {
  id: string
  kind: SetupCalibrationEventKind
  user_visible_label: string
  inferred_technical_depth?: SetupTechnicalDepth | null
  created_at: string
}

export type SetupAgentStatus = 'ready' | 'onboarding_model_unavailable' | 'validation_failed'

export type SetupAgentIntent =
  | 'answer'
  | 'clarify'
  | 'propose'
  | 'execute_approved_tool_calls'
  | 'validation_failed'

export type SetupToolApprovalState =
  | 'proposed'
  | 'approving'
  | 'approved'
  | 'executing'
  | 'skipped'
  | 'deferred'
  | 'executed'
  | 'failed'

export type SetupSessionGoalKind =
  | 'models_prepared'
  | 'profile_reviewed'
  | 'writing_samples_reviewed'
  | 'connections_reviewed'
  | 'dill_introduced'
  | 'paprika_introduced'
  | 'setup_completed'

export type SetupGoalStatus =
  | 'not_started'
  | 'in_progress'
  | 'blocked'
  | 'ready_for_review'
  | 'satisfied'
  | 'deferred'

export type SetupAgendaItemKind =
  | 'ask_question'
  | 'run_discovery'
  | 'review_proposals'
  | 'execute_approved'
  | 'explain_blocker'
  | 'introduce_capability'
  | 'finish_setup'

export type SetupUiSectionKind =
  | 'conversation'
  | 'discovery'
  | 'proposals'
  | 'models'
  | 'connections'
  | 'tasks'
  | 'completion'

export type SetupOrientationTone =
  | 'email'
  | 'profile'
  | 'privacy'
  | 'tools'
  | 'models'
  | 'connections'
  | 'ready'

export type SetupArtifactKind =
  | 'model_choice_review'
  | 'task_offer_gallery'
  | 'writing_sample_review'
  | 'connection_picker'
  | 'profile_review'
  | 'settings_review'

export type SetupAgentEventKind =
  | 'observation_added'
  | 'progress_narration'
  | 'chips_set'
  | 'message_started'
  | 'message_delta'
  | 'message_completed'
  | 'inline_receipt_added'
  | 'inline_email_context'
  | 'artifact_opened'
  | 'artifact_row_added'
  | 'artifact_closed'
  | 'proposal_status_changed'
  | 'wrap_up_proposed'
  | 'agenda_proposed'
  | 'agenda_item_marked'
  | 'agenda_confirmation_requested'
  | 'setup_visual_shown'
  | 'turn_started'
  | 'turn_complete'
  | 'error'

export interface SetupInlineEmailContext {
  email_id: string
  subject: string
  sender_name: string
  sender_address: string
  received_at?: string | null
  body_excerpt: string
  excerpt_truncated: boolean
  client_name: string
  source: 'selected_in_outlook' | 'most_recent_received' | string
}

// One inline visual the setup agent surfaced via show_setup_visual.
// Mirror of the backend SetupInlineVisual pydantic model in
// backend/src/api/routes/setup_assistant/models.py. The bridge SSE
// reducer normalizes the snake_case wire payload into this shape
// and attaches it to the most recent Basil message so the image
// renders chronologically beneath whatever the agent just said.
//
// `web_path` and `secondary_web_path` (when present) point at PNGs
// staged into public/images/setup/ by build-setup-assistant-assets.sh
// from the BasilClient OnboardingWebAssets bundle. `kind` controls
// frontend sizing/framing: 'screenshot' = full-bleed; 'icon' = small,
// inline-ish; 'icon_pair' = paired small icons; 'bubble_sequence' =
// web-rendered status bubbles; 'composite' = side-by-side screenshots
// when secondary_web_path is set.
export type SetupInlineVisualKind =
  | 'screenshot'
  | 'icon'
  | 'icon_pair'
  | 'bubble_sequence'
  | 'composite'

export interface SetupInlineVisual {
  id: string
  visualId: string
  webPath: string
  secondaryWebPath?: string | null
  caption: string
  alt: string
  secondaryAlt?: string | null
  kind: SetupInlineVisualKind
  relatedAgendaItemId?: string | null
  captionOverride?: string | null
}

export interface SetupWrapUpProposal {
  recap: string
  recommended_next_steps: SetupSuggestionChip[]
  optional_breadth?: string | null
}

export interface SetupSessionGoal {
  id: SetupSessionGoalKind
  status: SetupGoalStatus
  user_visible_label: string
  user_visible_summary: string
  blocker?: string | null
  related_item_ids: string[]
}

export interface SetupAgentAgendaItem {
  id: string
  kind: SetupAgendaItemKind
  goal_id?: SetupSessionGoalKind | null
  title: string
  rationale: string
  cta_label?: string | null
  target_phase?: SetupAssistantPhase | null
  required_discovery_sources: string[]
  related_item_ids: string[]
  payload: Record<string, unknown>
}

export interface SetupUiSection {
  id: string
  kind: SetupUiSectionKind
  title: string
  description?: string | null
  item_ids: string[]
}

export interface SetupRecommendation {
  id: string
  category: string
  title: string
  rationale: string
  evidence_fact_ids: string[]
  confidence: number
  proposed_action: SetupAction
  privacy_impact: SetupPrivacyImpact
  approval_state: SetupApprovalState
}

export interface SetupProfileSuggestion {
  id: string
  field: string
  suggested_value: string
  source_summary: string
  confidence: number
  is_editable: boolean
  approval_state: SetupApprovalState
}

export interface SetupModelChoice {
  id: string
  model_id: string
  display_name: string
  capability: string
  download_size_description?: string | null
  is_already_installed: boolean
  rationale: string
  approval_state: SetupApprovalState
}

export interface SetupTaskOffer {
  id: string
  title: string
  prompt: string
  required_permissions: string[]
  data_scope: string
  expected_output: string
  mutates_external_state: boolean
  privacy_impact: SetupPrivacyImpact
  approval_state: SetupApprovalState
  model_id?: string
}

export interface SetupToolDefinition {
  name: string
  description: string
  input_schema: Record<string, unknown>
  requires_explicit_approval: boolean
  privacy_impact: SetupPrivacyImpact
  required_permissions: string[]
  bridge_action?: string | null
}

export interface SetupToolCall {
  id: string
  tool_name: string
  payload: Record<string, unknown>
  approval_state: SetupToolApprovalState
  user_visible_summary: string
  privacy_impact: SetupPrivacyImpact
  mutates_external_state: boolean
  required_permissions: string[]
}

export interface SetupOrientationObservation {
  id: string
  label: string
  title: string
  detail: string
  tone: SetupOrientationTone
}

export interface SetupSuggestionChip {
  id: string
  label: string
  message: string
  preliminaryStatusMessage?: string | null
}

export interface SetupAppearanceChangeColorRow {
  kind: 'color'
  label: string
  oldColor: string
  newColor: string
}

export interface SetupAppearanceChangeFontRow {
  kind: 'font'
  label: string
  oldFont: string
  newFont: string
}

export type SetupAppearanceChangeRow = SetupAppearanceChangeColorRow | SetupAppearanceChangeFontRow

export interface SetupAppearanceChangeContrastWarning {
  ratio: number
  requiredRatio: number
}

export interface SetupAppearanceChangeSummary {
  rows: SetupAppearanceChangeRow[]
  contrastWarning: SetupAppearanceChangeContrastWarning | null
}

export interface SetupConsentReceipt {
  id: string
  proposal_id: string
  title: string
  rationale: string
  tool_call: SetupToolCall
  approval_state: SetupToolApprovalState
  ui_status_message?: string | null
  ui_error_message?: string | null
  appearance_change?: SetupAppearanceChangeSummary | null
}

export interface SetupArtifactRow {
  id: string
  payload: Record<string, unknown>
  receipt?: SetupConsentReceipt | null
}

export interface SetupArtifact {
  id: string
  kind: SetupArtifactKind
  title: string
  payload: Record<string, unknown>
  rows: SetupArtifactRow[]
  is_open: boolean
}

export interface SetupAgentEvent {
  kind: SetupAgentEventKind
  payload: Record<string, unknown>
  created_at: string
}

export interface SetupToolCallValidationResponse {
  tool_calls: SetupToolCall[]
}

export interface SetupWritingSampleCandidate {
  id: string
  content_excerpt: string
  full_content?: string | null
  source_app: string
  source_type: string
  context_type: string
  recipient?: string | null
  subject?: string | null
  date?: string | null
  rationale: string
  approval_state: SetupApprovalState
}

export interface SetupStateUpdateProposal {
  id: string
  target: string
  payload: Record<string, unknown>
  user_visible_summary: string
  approval_state: SetupApprovalState
}

export interface SetupTechnicalDepthProposal {
  suggested_depth: SetupTechnicalDepth
  rationale: string
  source_event_id?: string | null
}

export interface SetupNextStepProposal {
  phase: SetupAssistantPhase
  rationale: string
  requires_user_confirmation: boolean
}

export interface SetupAgentContractResponse {
  system_prompt: string
  required_output_schema: Record<string, unknown>
  validation_rules: string[]
}

export interface SetupAgentInput {
  phase: SetupAssistantPhase
  interview_answers: unknown[]
  discovery_facts: SetupDiscoveryFact[]
  allowed_action_kinds: SetupActionKind[]
  user_visible_guardrails: string[]
  technical_depth: SetupTechnicalDepth
  current_step_context: Record<string, unknown>
  session_goals: SetupSessionGoal[]
  agenda_items: SetupAgentAgendaItem[]
  execution_outcomes: Record<string, unknown>[]
}

export interface SetupAgentOutput {
  recommendations: SetupRecommendation[]
  profile_suggestions: SetupProfileSuggestion[]
  writing_sample_candidates: SetupWritingSampleCandidate[]
  model_choices: SetupModelChoice[]
  task_offers: SetupTaskOffer[]
  summary: string
  state_updates: SetupStateUpdateProposal[]
  tool_calls: SetupToolCall[]
  clarifying_questions: string[]
  technical_depth_proposal?: SetupTechnicalDepthProposal | null
  next_step_proposal?: SetupNextStepProposal | null
  session_goals: SetupSessionGoal[]
  agenda_items: SetupAgentAgendaItem[]
  primary_agenda_item_id?: string | null
  ui_sections: SetupUiSection[]
  suggestion_chips: SetupSuggestionChip[]
  inline_receipts: SetupConsentReceipt[]
  artifacts: SetupArtifact[]
}

export interface SetupAgentChatMessage {
  id: string
  role: 'basil' | 'user' | 'system'
  content: string
  created_at: string
}

export interface SetupAgentModelMetadata {
  provider: string
  model_id: string
  display_name: string
  openrouter_model_id?: string | null
  usage_scope: string
  used_by_setup_agent: boolean
  override_model_id?: string | null
}

export interface SetupAgentRequest {
  latest_message: string
  phase: SetupAssistantPhase
  technical_depth: SetupTechnicalDepth
  interview_answers: unknown[]
  discovery_facts: SetupDiscoveryFact[]
  chat_history: SetupAgentChatMessage[]
  existing_recommendations: SetupRecommendation[]
  existing_profile_suggestions: SetupProfileSuggestion[]
  existing_writing_sample_candidates: SetupWritingSampleCandidate[]
  existing_model_choices: SetupModelChoice[]
  existing_task_offers: SetupTaskOffer[]
  approved_tool_calls: SetupToolCall[]
  setup_agent_model_access: SetupAgentModelAccess
  calibration_events: SetupCalibrationEvent[]
  current_step_context: Record<string, unknown>
  setup_agent_model_override_id?: string | null
  // session_goals carries the session agenda round-trip on every turn.
  // The backend route models this as List[Dict[str, Any]] so the
  // frontend can send arbitrary structured agenda state without a
  // tightly-coupled schema; the legacy SetupSessionGoal interface
  // above is from an earlier never-shipped design and is unused.
  session_goals: Record<string, unknown>[]
  agenda_items: Record<string, unknown>[]
  execution_outcomes: Record<string, unknown>[]
}

export interface SetupAgentResponse {
  status: SetupAgentStatus
  intent: SetupAgentIntent
  assistant_message: string
  output: SetupAgentOutput
  model_metadata?: SetupAgentModelMetadata | null
  available_tools: SetupToolDefinition[]
  error_message?: string | null
}

export interface SetupAgentValidationResponse {
  valid: boolean
  output: SetupAgentOutput
}

export interface SetupAssistantCompletionRequest {
  configured: string[]
  skipped: string[]
  deferred: string[]
  // session_goals carries the final agenda snapshot at completion
  // time. Loose-typed to match the backend's List[Dict[str, Any]]
  // shape — the legacy SetupSessionGoal interface above is from an
  // earlier never-shipped design and is unused.
  session_goals?: Record<string, unknown>[]
  execution_outcomes?: Record<string, unknown>[]
  blockers?: Record<string, unknown>[]
}

export interface BasilMessage {
  id: string
  role: 'basil' | 'user' | 'system'
  content: string
  createdAt: string
}

