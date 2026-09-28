"""Pydantic contracts for the Basil setup assistant API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SetupAssistantPhase(str, Enum):
    permission_preflight = "permission_preflight"
    setup_interview = "setup_interview"
    deterministic_discovery = "deterministic_discovery"
    agent_synthesis = "agent_synthesis"
    recommendation_review = "recommendation_review"
    model_setup = "model_setup"
    task_offers = "task_offers"
    completion = "completion"


class SetupPermissionKind(str, Enum):
    microphone = "microphone"
    accessibility = "accessibility"
    input_monitoring = "input_monitoring"
    apple_events = "apple_events"
    screen_recording = "screen_recording"


class SetupDiscoverySource(str, Enum):
    permissions = "permissions"
    basil_settings = "basil_settings"
    model_status = "model_status"
    user_profile = "user_profile"
    writing_samples = "writing_samples"
    email_clients = "email_clients"
    installed_applications = "installed_applications"
    activity_capture = "activity_capture"
    agent_task_history = "agent_task_history"
    connections = "connections"
    runtime_operations = "runtime_operations"


class SetupDiscoveryFactKind(str, Enum):
    permission_status = "permission_status"
    current_setting = "current_setting"
    available_model = "available_model"
    profile_field = "profile_field"
    writing_sample_summary = "writing_sample_summary"
    detected_application = "detected_application"
    detected_email_client = "detected_email_client"
    detected_connection = "detected_connection"
    usage_signal = "usage_signal"
    capability_available = "capability_available"
    operation_status = "operation_status"


class SetupRecommendationCategory(str, Enum):
    profile = "profile"
    writing_style = "writing_style"
    model = "model"
    permission = "permission"
    activity_capture = "activity_capture"
    assistant_session = "assistant_session"
    agent_task = "agent_task"
    task_offer = "task_offer"
    connection = "connection"
    basil_guidance = "basil_guidance"


class SetupApprovalState(str, Enum):
    pending = "pending"
    approved = "approved"
    skipped = "skipped"
    deferred = "deferred"
    applied = "applied"
    failed = "failed"


class SetupPrivacyImpact(str, Enum):
    none = "none"
    local_only = "local_only"
    reads_local_data = "reads_local_data"
    uses_cloud_model = "uses_cloud_model"
    controls_applications = "controls_applications"
    creates_external_draft = "creates_external_draft"
    modifies_settings = "modifies_settings"
    launches_real_task = "launches_real_task"
    authenticates_service = "authenticates_service"


class SetupActionKind(str, Enum):
    save_profile = "save_profile"
    save_writing_samples = "save_writing_samples"
    update_settings = "update_settings"
    start_model_downloads = "start_model_downloads"
    start_connection_auth = "start_connection_auth"
    refresh_connection_tools = "refresh_connection_tools"
    launch_agent_task = "launch_agent_task"
    launch_assistant_session = "launch_assistant_session"
    run_approved_action_sequence = "run_approved_action_sequence"
    open_system_settings = "open_system_settings"
    defer_recommendation = "defer_recommendation"
    no_mutation = "no_mutation"


class SetupTechnicalDepth(str, Enum):
    plain = "plain"
    practical = "practical"
    technical = "technical"


class SetupAgentModelAccessMode(str, Enum):
    local = "local"
    provider_key = "provider_key"
    basil_cloud = "basil_cloud"


class SetupCalibrationEventKind(str, Enum):
    continue_forward = "continue"
    confused = "confused"
    more_detail = "more_detail"
    prefer_local = "prefer_local"
    manual_model_choice = "manual_model_choice"


class SetupAgentStatus(str, Enum):
    ready = "ready"
    onboarding_model_unavailable = "onboarding_model_unavailable"
    validation_failed = "validation_failed"


class SetupAgentIntent(str, Enum):
    answer = "answer"
    clarify = "clarify"
    propose = "propose"
    execute_approved_tool_calls = "execute_approved_tool_calls"
    validation_failed = "validation_failed"


class SetupAgentMessageRole(str, Enum):
    user = "user"
    basil = "basil"
    system = "system"


class SetupToolApprovalState(str, Enum):
    proposed = "proposed"
    approved = "approved"
    skipped = "skipped"
    deferred = "deferred"
    executed = "executed"
    failed = "failed"


class SetupUiSectionKind(str, Enum):
    conversation = "conversation"
    discovery = "discovery"
    proposals = "proposals"
    models = "models"
    connections = "connections"
    tasks = "tasks"
    completion = "completion"


class SetupOrientationTone(str, Enum):
    email = "email"
    profile = "profile"
    privacy = "privacy"
    tools = "tools"
    models = "models"
    connections = "connections"
    ready = "ready"


class SetupArtifactKind(str, Enum):
    model_choice_review = "model_choice_review"
    task_offer_gallery = "task_offer_gallery"
    writing_sample_review = "writing_sample_review"
    connection_picker = "connection_picker"
    profile_review = "profile_review"
    settings_review = "settings_review"


class SetupAgentEventKind(str, Enum):
    observation_added = "observation_added"
    progress_narration = "progress_narration"
    chips_set = "chips_set"
    message_started = "message_started"
    message_delta = "message_delta"
    message_completed = "message_completed"
    inline_receipt_added = "inline_receipt_added"
    inline_email_context = "inline_email_context"
    artifact_opened = "artifact_opened"
    artifact_row_added = "artifact_row_added"
    artifact_closed = "artifact_closed"
    proposal_status_changed = "proposal_status_changed"
    wrap_up_proposed = "wrap_up_proposed"
    agenda_proposed = "agenda_proposed"
    agenda_item_marked = "agenda_item_marked"
    agenda_confirmation_requested = "agenda_confirmation_requested"
    setup_visual_shown = "setup_visual_shown"
    turn_started = "turn_started"
    turn_complete = "turn_complete"
    error = "error"


class SetupSessionAgendaItemKind(str, Enum):
    action = "action"
    demo = "demo"
    literacy = "literacy"
    conversational = "conversational"


class SetupSessionAgendaItemStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    skipped = "skipped"
    deferred = "deferred"


class SetupSessionAgendaItemSource(str, Enum):
    catalog = "catalog"
    agent = "agent"


class SetupDiscoveryFact(BaseModel):
    id: str = Field(min_length=1)
    source: SetupDiscoverySource
    kind: SetupDiscoveryFactKind
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    requires_permission: Optional[SetupPermissionKind] = None
    user_visible_summary: str = Field(min_length=1)
    metadata: Dict[str, str] = Field(default_factory=dict)


class SetupInterviewAnswer(BaseModel):
    id: str = Field(min_length=1)
    question_kind: str = Field(min_length=1)
    selected_option_ids: List[str] = Field(default_factory=list)
    freeform_text: Optional[str] = None
    answered_at: datetime = Field(default_factory=datetime.utcnow)


class SetupActionAuditMetadata(BaseModel):
    source_recommendation_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    user_visible_summary: str = ""
    data_scope: str = ""
    privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none
    mutates_external_state: bool = False


class SetupAction(BaseModel):
    id: str = Field(min_length=1)
    kind: SetupActionKind
    payload: Dict[str, Any] = Field(default_factory=dict)
    requires_explicit_approval: bool = True
    mutates_external_state: bool = False
    audit_metadata: Optional[SetupActionAuditMetadata] = None

    @field_validator("requires_explicit_approval")
    @classmethod
    def validate_executable_actions_require_approval(
        cls,
        requires_explicit_approval: bool,
        info: Any,
    ) -> bool:
        data = info.data
        kind = data.get("kind")
        if kind and kind != SetupActionKind.no_mutation and not requires_explicit_approval:
            raise ValueError("All mutating or executable setup actions require explicit approval.")
        return requires_explicit_approval


class SetupAgentChatMessage(BaseModel):
    id: str = Field(min_length=1)
    role: SetupAgentMessageRole
    content: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SetupAgentModelMetadata(BaseModel):
    provider: str = "proxy"
    model_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    openrouter_model_id: Optional[str] = None
    usage_scope: str = "onboarding"
    used_by_setup_agent: bool = True
    override_model_id: Optional[str] = None
    access_mode: SetupAgentModelAccessMode = SetupAgentModelAccessMode.local


class SetupAgentModelAccess(BaseModel):
    """A backend-confirmed setup-agent model route."""

    mode: SetupAgentModelAccessMode
    local_model_id: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    resolved: bool = False


class SetupAgentProviderModelChoice(BaseModel):
    """A reasoning model the provider-key route can run the Setup Assistant on."""

    provider: str
    model_id: str
    display_name: str
    recommended: bool = False


class SetupAgentModelAccessOption(BaseModel):
    """One selectable route surfaced by the model-access endpoint."""

    mode: SetupAgentModelAccessMode
    available: bool
    unavailable_reason: Optional[str] = None
    local_model_id: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    display_name: Optional[str] = None
    requires_provider_key_input: bool = False
    provider_models: List[SetupAgentProviderModelChoice] = Field(default_factory=list)


class SetupAgentModelAccessOptionsResponse(BaseModel):
    options: List[SetupAgentModelAccessOption]


class SetupAgentModelAccessSelectRequest(BaseModel):
    mode: SetupAgentModelAccessMode
    local_model_id: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    provider_api_key: Optional[str] = None


class SetupAgentModelAccessSelectResponse(BaseModel):
    access: SetupAgentModelAccess
    model_metadata: SetupAgentModelMetadata


class SetupCalibrationEvent(BaseModel):
    id: str = Field(min_length=1)
    kind: SetupCalibrationEventKind
    user_visible_label: str = Field(min_length=1)
    inferred_technical_depth: Optional[SetupTechnicalDepth] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SetupToolDefinition(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    requires_explicit_approval: bool = True
    privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none
    required_permissions: List[SetupPermissionKind] = Field(default_factory=list)
    bridge_action: Optional[str] = None


class SetupToolCall(BaseModel):
    id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    approval_state: SetupToolApprovalState = SetupToolApprovalState.proposed
    user_visible_summary: str = Field(min_length=1)
    privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none
    mutates_external_state: bool = False
    required_permissions: List[SetupPermissionKind] = Field(default_factory=list)


class SetupOrientationObservation(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    tone: SetupOrientationTone = SetupOrientationTone.ready


class SetupSuggestionChip(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    message: str = Field(min_length=1)


class SetupConsentReceipt(BaseModel):
    id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    tool_call: SetupToolCall
    approval_state: SetupToolApprovalState = SetupToolApprovalState.proposed


class SetupArtifactRow(BaseModel):
    id: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    receipt: Optional[SetupConsentReceipt] = None


class SetupArtifact(BaseModel):
    id: str = Field(min_length=1)
    kind: SetupArtifactKind
    title: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    rows: List[SetupArtifactRow] = Field(default_factory=list)
    is_open: bool = True


class SetupSessionAgendaItem(BaseModel):
    """One entry in the setup-assistant session agenda.

    The frontend store holds an ordered list of these; the agent
    produces them via ``propose_session_agenda`` (full replacement)
    and edits per-item status via ``mark_agenda_item``. ``source``
    distinguishes catalog-seeded items from agent-authored additions
    so the UI can subtly mark provenance and future telemetry can
    measure catalog coverage.
    """

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    kind: SetupSessionAgendaItemKind
    source: SetupSessionAgendaItemSource = SetupSessionAgendaItemSource.agent
    status: SetupSessionAgendaItemStatus = SetupSessionAgendaItemStatus.pending
    completion_basis: Optional[str] = None


class SetupSessionAgendaProposal(BaseModel):
    """Wholesale replacement of the session agenda.

    Emitted via the ``agenda_proposed`` SSE event. The frontend
    reducer clears the prior agenda and adopts ``items`` in order.
    """

    items: List[SetupSessionAgendaItem] = Field(default_factory=list)


class SetupAgendaItemMark(BaseModel):
    """A status update for a single agenda item.

    Emitted via the ``agenda_item_marked`` SSE event. ``completion_basis``
    is captured for transcripts and debugging (e.g. ``"user confirmed via
    AgendaConfirmationCard"`` or ``"observed local reasoning model
    present"``); the UI does not rely on it for rendering.
    """

    id: str = Field(min_length=1)
    status: SetupSessionAgendaItemStatus
    completion_basis: Optional[str] = None


class SetupAgendaConfirmationRequest(BaseModel):
    """An inline "did this land?" check for an agenda item.

    Emitted via the ``agenda_confirmation_requested`` SSE event when
    the agent has covered a literacy or demo item where completion
    is not observable from any side-effect. ``id`` is the unique
    confirmation-card id; ``agenda_item_id`` references the item the
    confirmation is about. The frontend renders an inline card with
    Yes / Not quite / Skip affordances; the response is dispatched
    back as a user message so the agent can react.
    """

    id: str = Field(min_length=1)
    agenda_item_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


class SetupInlineVisual(BaseModel):
    """One inline visual the agent surfaced via ``show_setup_visual``.

    Emitted via the ``setup_visual_shown`` SSE event and attached to
    the most recent Basil message in the conversation. Fields mirror
    the ``SetupVisual`` dataclass entries from
    ``setup_visual_catalog.py`` but live here in the route layer so
    the frontend has a stable wire contract that doesn't reach into
    the agent-graph internals.

    ``id`` is the unique inline-card id (one per emission, generated
    server-side); ``visual_id`` is the catalog slug being shown so
    the frontend can dedupe repeated shows of the same asset. The
    optional ``caption_override`` lets the agent reframe a catalog
    caption for the moment without editing the catalog itself.
    """

    id: str = Field(min_length=1)
    visual_id: str = Field(min_length=1)
    web_path: str = Field(min_length=1)
    secondary_web_path: Optional[str] = None
    caption: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    secondary_alt: Optional[str] = None
    kind: Literal["screenshot", "icon", "icon_pair", "bubble_sequence", "composite"]
    related_agenda_item_id: Optional[str] = None
    caption_override: Optional[str] = None


class SetupAgentEvent(BaseModel):
    kind: SetupAgentEventKind
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SetupTechnicalDepthProposal(BaseModel):
    suggested_depth: SetupTechnicalDepth
    rationale: str = Field(min_length=1)
    source_event_id: Optional[str] = None


class SetupNextStepProposal(BaseModel):
    phase: SetupAssistantPhase
    rationale: str = Field(min_length=1)
    requires_user_confirmation: bool = True


class SetupUiSection(BaseModel):
    id: str = Field(min_length=1)
    kind: SetupUiSectionKind
    title: str = Field(min_length=1)
    description: Optional[str] = None
    item_ids: List[str] = Field(default_factory=list)


class SetupAgentInput(BaseModel):
    phase: SetupAssistantPhase
    interview_answers: List[SetupInterviewAnswer] = Field(default_factory=list)
    discovery_facts: List[SetupDiscoveryFact] = Field(default_factory=list)
    allowed_action_kinds: List[SetupActionKind] = Field(default_factory=list)
    user_visible_guardrails: List[str] = Field(default_factory=list)
    technical_depth: SetupTechnicalDepth = SetupTechnicalDepth.practical
    current_step_context: Dict[str, Any] = Field(default_factory=dict)
    session_goals: List[Dict[str, Any]] = Field(default_factory=list)
    agenda_items: List[Dict[str, Any]] = Field(default_factory=list)
    execution_outcomes: List[Dict[str, Any]] = Field(default_factory=list)


class SetupAgentOutput(BaseModel):
    summary: str = Field(min_length=1)
    tool_calls: List[SetupToolCall] = Field(default_factory=list)
    clarifying_questions: List[str] = Field(default_factory=list)
    technical_depth_proposal: Optional[SetupTechnicalDepthProposal] = None
    next_step_proposal: Optional[SetupNextStepProposal] = None
    ui_sections: List[SetupUiSection] = Field(default_factory=list)
    suggestion_chips: List[SetupSuggestionChip] = Field(default_factory=list)
    inline_receipts: List[SetupConsentReceipt] = Field(default_factory=list)
    artifacts: List[SetupArtifact] = Field(default_factory=list)
    agenda_proposal: Optional[SetupSessionAgendaProposal] = None
    agenda_updates: List[SetupAgendaItemMark] = Field(default_factory=list)
    agenda_confirmation_requests: List[SetupAgendaConfirmationRequest] = Field(default_factory=list)
    inline_visuals: List[SetupInlineVisual] = Field(default_factory=list)


class SetupAgentModelPost(BaseModel):
    """Strict envelope for model-authored setup agent responses."""

    model_config = ConfigDict(extra="ignore")

    assistant_message: str = Field(min_length=1)
    intent: SetupAgentIntent = SetupAgentIntent.answer
    output: SetupAgentOutput

    @classmethod
    def validate_model_post(cls, payload: Dict[str, Any]) -> "SetupAgentModelPost":
        return cls.model_validate(payload)


class SetupAgentContractResponse(BaseModel):
    system_prompt: str
    required_output_schema: Dict[str, Any]
    validation_rules: List[str]


class SetupAgentRequest(BaseModel):
    latest_message: str = Field(min_length=1)
    phase: SetupAssistantPhase
    technical_depth: SetupTechnicalDepth = SetupTechnicalDepth.practical
    interview_answers: List[SetupInterviewAnswer] = Field(default_factory=list)
    discovery_facts: List[SetupDiscoveryFact] = Field(default_factory=list)
    chat_history: List[SetupAgentChatMessage] = Field(default_factory=list)
    existing_recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    existing_profile_suggestions: List[Dict[str, Any]] = Field(default_factory=list)
    existing_writing_sample_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    existing_model_choices: List[Dict[str, Any]] = Field(default_factory=list)
    existing_task_offers: List[Dict[str, Any]] = Field(default_factory=list)
    approved_tool_calls: List[SetupToolCall] = Field(default_factory=list)
    setup_agent_model_access: SetupAgentModelAccess
    calibration_events: List[SetupCalibrationEvent] = Field(default_factory=list)
    current_step_context: Dict[str, Any] = Field(default_factory=dict)
    setup_agent_model_override_id: Optional[str] = None
    session_goals: List[Dict[str, Any]] = Field(default_factory=list)
    agenda_items: List[Dict[str, Any]] = Field(default_factory=list)
    execution_outcomes: List[Dict[str, Any]] = Field(default_factory=list)


class SetupAgentResponse(BaseModel):
    status: SetupAgentStatus
    intent: SetupAgentIntent = SetupAgentIntent.answer
    assistant_message: str
    output: SetupAgentOutput
    model_metadata: Optional[SetupAgentModelMetadata] = None
    available_tools: List[SetupToolDefinition] = Field(default_factory=list)
    error_message: Optional[str] = None


class SetupAgentValidationRequest(BaseModel):
    output: SetupAgentOutput
    discovery_facts: List[SetupDiscoveryFact] = Field(default_factory=list)


class SetupAgentValidationResponse(BaseModel):
    valid: bool
    output: SetupAgentOutput


class SetupExecutionStatus(str, Enum):
    applied = "applied"
    executed = "executed"
    failed = "failed"
    skipped = "skipped"


class SetupActionExecutionItem(BaseModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: SetupExecutionStatus
    message: str = Field(min_length=1)
    result_payload: Dict[str, Any] = Field(default_factory=dict)


class SetupActionExecutionRequest(BaseModel):
    actions: List[SetupAction] = Field(default_factory=list)
    tool_calls: List[SetupToolCall] = Field(default_factory=list)


class SetupActionExecutionResponse(BaseModel):
    results: List[SetupActionExecutionItem] = Field(default_factory=list)


class SetupDiscoveryResponse(BaseModel):
    facts: List[SetupDiscoveryFact]
    collected_at: datetime

