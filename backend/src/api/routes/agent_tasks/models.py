"""Pydantic models for agent task route modules."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, overload

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class LocalPreviewFeedbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_artifact_id: str = Field(min_length=1, max_length=256)
    mode: Literal["static", "devServer"]
    preview_url: str = Field(min_length=1, max_length=2_048)
    location_status: Literal["current", "fallback"]
    screenshot_path: Optional[str] = Field(default=None, max_length=4_096)
    console_evidence: str = Field(default="", max_length=8_000)
    session_id: Optional[str] = Field(default=None, max_length=128)
    session_status: Optional[Literal["starting", "running", "stopped", "error", "denied"]] = None


class AgentTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_task: str
    display_prompt_markdown: Optional[str] = None
    clarification_agent_task: Optional[str] = None
    agent_task_id: Optional[str] = None  # For clarifications, pass the original AgentTask ID
    root_task_id: Optional[str] = None  # Explicit root task ID for follow-up chains
    previous_task_id: Optional[str] = None  # Immediate predecessor task ID for follow-up turns
    reference_paths: Optional[List[str]] = None  # File/folder paths dropped as context
    local_preview_feedback: Optional[LocalPreviewFeedbackPayload] = None
    model_id: Optional[str] = None  # Override the default reasoning model for this request
    # TEST-ONLY: per-run approval-policy override (approval_mode/timeout_behavior/etc.).
    # Normal UI flows never set this; absent == saved-preferences behavior.
    approval_policy_override: Optional[Dict[str, Any]] = None


class AgentTaskProcessingResponse(BaseModel):
    success: bool
    operation: str
    confidence: float
    reasoning: str
    message: str
    processing_time: float
    agent_task_id: Optional[str] = None  # Include agent_task_id for clarifications


class AgentTaskClarificationRequest(BaseModel):
    agent_task_id: str
    clarification_text: str


class AgentTaskClarificationResponse(BaseModel):
    success: bool
    agent_task_id: str
    message: str
    error: Optional[str] = None


class ScheduledAgentTaskCreateRequest(BaseModel):
    title: str
    agent_task_text: str
    schedule_type: str  # one_time | recurring
    schedule_config: Dict[str, Any]
    timezone: str = "UTC"
    source_type: str = "manual"
    is_active: bool = True
    # Absolute filesystem paths attached as context for every scheduled run.
    # Mirrors AgentTaskRequest.reference_paths and is forwarded into
    # process_agent_task_direct(reference_paths=...) at execution time.
    reference_paths: Optional[List[str]] = None


class ScheduledAgentTaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    agent_task_text: Optional[str] = None
    schedule_type: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None
    # Replaces the stored list wholesale on each PATCH. Send an empty
    # array to clear all attachments; omit the field to leave them
    # unchanged (handled via exclude_none in the route).
    reference_paths: Optional[List[str]] = None


class ScheduleInterpretationRequest(BaseModel):
    prompt: str
    context_id: Optional[str] = None
    # IANA timezone name (e.g. "America/New_York") for the user's local zone.
    # The result widget always sends the form's currently-selected timezone
    # (which itself defaults to the user's browser-detected IANA zone via
    # Intl.DateTimeFormat().resolvedOptions().timeZone). When omitted, the
    # service falls back to host autodetection so callers like the voice
    # agent-task tool still get correct local-time interpretation without
    # having to know the user's zone themselves. This is what prevents
    # requests like "every day at 8pm" from triggering an unnecessary
    # clarification round-trip purely about timezone.
    user_timezone: Optional[str] = None


class ScheduleInterpretationResponse(BaseModel):
    success: bool
    title: Optional[str] = None
    agent_task_text: Optional[str] = None
    schedule_type: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = None
    source_type: str = "smart"
    is_active: bool = True
    needs_user_confirmation: bool = False
    clarification_question: Optional[str] = None
    context_id: Optional[str] = None
    error: Optional[str] = None


class ScheduledAgentTaskRunNowResponse(BaseModel):
    success: bool
    run_id: Optional[str] = None
    error: Optional[str] = None


class ScheduledAgentTaskRunItem(BaseModel):
    id: str
    scheduled_agent_task_id: str
    agent_task_id: Optional[str] = None
    scheduled_for: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: str
    error_message: Optional[str] = None


class ScheduledActiveRunItem(BaseModel):
    """Currently in-flight scheduled run, joined to its parent agent task for label."""

    run_id: str
    scheduled_agent_task_id: str
    agent_task_id: Optional[str] = None
    scheduled_for: str
    started_at: Optional[str] = None
    title: str
    agent_task_text: str


class ScheduledAgentTaskItem(BaseModel):
    id: str
    title: str
    agent_task_text: str
    schedule_type: str
    schedule_config: Dict[str, Any]
    timezone: str
    is_active: bool
    source_type: str
    reference_paths: List[str] = []
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None
    created_at: str
    updated_at: str
    run_count: int = 0
    last_scheduled_for: Optional[str] = None


class ScheduledAgentTaskListResponse(BaseModel):
    agent_tasks: List[ScheduledAgentTaskItem]


@overload
def serialize_datetime_with_z(dt: datetime) -> str:
    ...


@overload
def serialize_datetime_with_z(dt: None) -> None:
    ...


def serialize_datetime_with_z(dt: Optional[datetime]) -> Optional[str]:
    """Serialize datetime with 'Z' suffix for Swift ISO8601DateFormatter compatibility."""
    if dt is None:
        return None
    return dt.isoformat() + "Z"


class AgentTaskListItem(BaseModel):
    """Summary item for agent_task history list."""
    id: str
    original_prompt: str
    title: Optional[str] = None
    result_preview: Optional[str] = None
    timestamp: datetime
    status: str
    outcome: Optional[str] = None
    result_severity: Optional[str] = None
    file_count: int = 0
    app_name: Optional[str] = None
    follow_up_count: int = 0  # Number of follow-up agent tasks in the chain
    origin_type: Optional[str] = None  # NULL | 'conversation' | 'scheduled_task'
    origin_id: Optional[str] = None
    is_scheduled_run: bool = False
    scheduled_agent_task_id: Optional[str] = None
    scheduled_agent_task_title: Optional[str] = None

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime) -> str:
        return serialize_datetime_with_z(timestamp)


class AgentTaskHistoryResponse(BaseModel):
    """Response for agent_task history list."""
    agentTasks: List[AgentTaskListItem]
    total_count: int
    has_more: bool


class AgentTaskArtifactPreviewResponse(BaseModel):
    """Selected preview capability for one local Agent Task artifact."""

    capability: Literal["supported", "unsupported", "unknown"] = "unknown"
    kind: Optional[str] = None


class AgentTaskArtifactVerificationResponse(BaseModel):
    """Selected verification state for one local Agent Task artifact."""

    status: Literal["not_applicable", "pending", "verified", "failed", "unknown"] = "unknown"
    summary: Optional[str] = None


class AgentTaskArtifactReviewResponse(BaseModel):
    """Selected durable revision presentation for one local Agent Task artifact."""

    revision: Optional[int] = Field(default=None, ge=1)
    revision_count: int = Field(default=0, ge=0)
    kind: Optional[
        Literal["markdown", "html", "text", "code", "json", "yaml", "xml", "pdf", "unsupported"]
    ] = None
    snapshot_status: Literal["available", "unchanged", "unavailable"] = "unavailable"
    unavailable_reason: Optional[str] = Field(default=None, max_length=160)


class AgentTaskArtifactResponse(BaseModel):
    """Presentation-safe artifact metadata derived from a task file record."""

    artifact_id: str
    display_name: str
    local_path: Optional[str] = None
    artifact_kind: Literal["file", "directory", "unknown"] = "unknown"
    operation: Optional[str] = None
    lifecycle: Literal["discovered", "ready", "verified", "failed", "unavailable"]
    source_timeline_entry_id: Optional[str] = None
    source_step_id: Optional[str] = None
    preview: AgentTaskArtifactPreviewResponse
    verification: AgentTaskArtifactVerificationResponse
    review: Optional[AgentTaskArtifactReviewResponse] = None


class AgentTaskArtifactRevisionItemResponse(BaseModel):
    """One metadata-only revision row, newest-first, owned by one task."""

    revision: int = Field(ge=1)
    display_name: str
    content_kind: Literal["markdown", "html", "text", "code", "json", "yaml", "xml"]
    byte_count: int = Field(ge=0)
    created_at: datetime

    @field_serializer('created_at')
    def serialize_created_at(self, created_at: datetime) -> str:
        return serialize_datetime_with_z(created_at)


class AgentTaskArtifactRevisionListResponse(BaseModel):
    """Newest-first revision metadata for one task-owned artifact."""

    revisions: List[AgentTaskArtifactRevisionItemResponse] = Field(default_factory=list)


class AgentTaskArtifactRevisionContentResponse(BaseModel):
    """One bounded text snapshot owned by one Agent Task."""

    revision: int = Field(ge=1)
    display_name: str
    content_kind: Literal["markdown", "html", "text", "code", "json", "yaml", "xml"]
    byte_count: int = Field(ge=0)
    created_at: datetime
    content: str
    content_sha256: str

    @field_serializer('created_at')
    def serialize_created_at(self, created_at: datetime) -> str:
        return serialize_datetime_with_z(created_at)


class AgentTaskPresentationWorkflowResponse(BaseModel):
    """Optional finalizer workflow counts selected for compact presentation."""

    total_steps: Optional[int] = None
    completed_steps: Optional[int] = None


class DelegatedProviderReportCardResponse(BaseModel):
    """Compact, presentation-safe derived status for one delegated provider run."""

    delegated_agent_run_id: str
    run_status: Literal["admitted", "running", "idle", "waiting_user_input", "waiting_permission", "supervision_due", "cancelling", "interrupted", "settled", "failed", "cancelled"]
    run_revision: int = Field(ge=0)
    capture_state: Literal["available", "unavailable"]
    evidence_count: int = Field(ge=0)
    latest_summary: Optional[str] = Field(default=None, max_length=160)
    verification_state: Literal["not_applicable", "pending", "verified", "verification_mismatch", "unavailable"]


class DelegatedProviderReportCardsResponse(BaseModel):
    """Selected delegated-provider cards owned by one displayed Agent Task turn."""

    items: List[DelegatedProviderReportCardResponse] = Field(default_factory=list)


class AgentTaskPresentationSummaryResponse(BaseModel):
    """Compact, presentation-safe durable summary for one Agent Task."""

    agent_task_id: str
    lifecycle: str
    latest_activity: Optional[str] = None
    workflow: AgentTaskPresentationWorkflowResponse = Field(default_factory=AgentTaskPresentationWorkflowResponse)
    artifacts: List[AgentTaskArtifactResponse] = Field(default_factory=list)
    artifact_count: int = 0
    verification_status: Literal["pending", "resolved", "unknown"] = "unknown"
    requires_user_attention: bool
    delegated_provider_report_cards: DelegatedProviderReportCardsResponse = Field(default_factory=DelegatedProviderReportCardsResponse)


class AgentTaskFileArtifactResponse(BaseModel):
    """A filesystem artifact reported by an agent task."""
    name: str = ""
    path: str = ""
    operation: str = ""
    source_path: Optional[str] = None
    kind: Optional[str] = None
    artifact: Optional[AgentTaskArtifactResponse] = None


class RetryAgentTaskRequest(BaseModel):
    """Optional retry override. Omitted/`None` preserves the original attempt's model."""
    model_id: Optional[str] = None


class AgentTaskChainItem(BaseModel):
    """A single item in a agent_task chain (parent or follow-up)."""
    id: str
    original_prompt: str
    display_prompt_markdown: Optional[str] = None
    timestamp: datetime
    status: str
    outcome: Optional[str] = None
    result_severity: Optional[str] = None
    result_message: Optional[str] = None
    files: List[AgentTaskFileArtifactResponse] = []
    agent_task_presentation_summary: Optional[AgentTaskPresentationSummaryResponse] = None
    reference_paths: List[str] = []
    root_task_id: Optional[str] = None
    previous_task_id: Optional[str] = None
    chain_sequence_number: int = 0
    error_message: Optional[str] = None
    execution_timeline: Optional[List[Dict[str, Any]]] = None
    thinking_history: List[Dict[str, Any]] = []
    reasoning_fallback_model_used: Optional[str] = None
    model_id: Optional[str] = None

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime) -> str:
        return serialize_datetime_with_z(timestamp)


class AgentTaskDetailResponse(BaseModel):
    """Full details for a single agent_task including follow-up chain."""
    id: str
    original_prompt: str
    transcribed_prompt: str
    display_prompt_markdown: Optional[str] = None
    title: Optional[str] = None
    origin_type: Optional[str] = None
    origin_id: Optional[str] = None
    timestamp: datetime
    status: str
    outcome: Optional[str] = None
    result_severity: Optional[str] = None
    result_message: Optional[str] = None
    app_name: Optional[str] = None
    window_title: Optional[str] = None
    files: List[AgentTaskFileArtifactResponse] = []
    agent_task_presentation_summary: Optional[AgentTaskPresentationSummaryResponse] = None
    reference_paths: List[str] = []
    root_task_id: Optional[str] = None
    previous_task_id: Optional[str] = None
    follow_ups: List[AgentTaskChainItem] = []
    error_message: Optional[str] = None
    execution_timeline: Optional[List[Dict[str, Any]]] = None
    thinking_history: List[Dict[str, Any]] = []
    checkpoint_data: Optional[Dict[str, Any]] = None
    reasoning_fallback_model_used: Optional[str] = None
    model_id: Optional[str] = None

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime) -> str:
        return serialize_datetime_with_z(timestamp)


class DeleteAgentTaskResponse(BaseModel):
    """Response for agent_task deletion."""
    success: bool
    message: str


class ActiveAgentItem(BaseModel):
    """An active agent task that is currently processing."""
    id: str
    original_prompt: str
    timestamp: datetime
    status: str
    current_step: Optional[str] = None

    @field_serializer('timestamp')
    def serialize_timestamp(self, timestamp: datetime) -> str:
        return serialize_datetime_with_z(timestamp)


class ActiveAgentsResponse(BaseModel):
    """Response for active agents list."""
    agents: List[ActiveAgentItem]
    count: int
