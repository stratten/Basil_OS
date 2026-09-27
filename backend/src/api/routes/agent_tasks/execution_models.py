"""Request and response models for agent-task execution-control routes."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from api.core.serialization import APIBaseModel


class SessionStateResponse(APIBaseModel):
    """Current state of a collaborative workflow session."""
    agent_task_id: str
    session_type: str
    session_status: str
    workflow_plan: Optional[List[Dict[str, Any]]]
    current_step: int
    total_planned_steps: int
    completed_steps: List[Dict[str, Any]]
    pending_steps: List[Dict[str, Any]]
    accumulated_artifacts: Dict[str, Any]
    last_interaction_timestamp: Optional[datetime]
    interaction_count: int


class ContinueSessionRequest(BaseModel):
    """Request to continue a collaborative workflow session."""
    agent_task_id: str
    user_input: Optional[str] = None  # Matches Swift client's field name
    user_response: Optional[str] = None  # Kept for backwards compatibility
    response_type: str = Field(default="voice", description="Type of response: voice, button, text_input, selection")
    metadata: Optional[Dict[str, str]] = None  # Matches Swift client


class SessionActionRequest(BaseModel):
    """Request to perform an action on a session."""
    agent_task_id: str
    action: str = Field(..., description="Action to perform: pause, cancel, resume")


class SessionActionResponse(BaseModel):
    """Response from a session action."""
    success: bool
    message: str
    agent_task_id: str
    new_status: Optional[str] = None


class ExecutionApprovalRequest(BaseModel):
    """Request for command execution approval."""
    command: str
    context: Optional[Dict[str, Any]] = None


class ExecutionApprovalResponse(BaseModel):
    """Response with approval decision."""
    needs_approval: bool
    reason: str
    risk_level: str
    is_blocked: bool = False
    block_reason: Optional[str] = None
    matched_pattern_id: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    """User's approval decision for a command."""
    approval_id: str = Field(description="Unique ID of the approval request")
    command: str
    approved: bool
    remember_choice: bool = False
    pattern_type: str = Field(default="exact", description="Type of pattern: exact, prefix, regex")
    description: Optional[str] = None
    agent_task_id: Optional[str] = Field(default=None, description="Owning Agent Task for stale decision rejection")
    expected_revision: Optional[int] = Field(default=None, description="Last known durable approval revision")


class PendingExecutionApprovalModel(BaseModel):
    """Safe rendering contract for one live generic execution approval."""

    approval_id: str
    agent_task_id: str
    command: str
    reason: str
    risk_level: str
    generalized_pattern: str
    execution_type: str = "shell"
    script_content: Optional[str] = None
    revision: int
    context: Dict[str, Any] = Field(default_factory=dict)
    risk_metadata: Optional[Dict[str, Any]] = None


class PendingExecutionApprovalResponseModel(BaseModel):
    """Live approvals and stale approvals requiring safe recovery."""

    approvals: List[PendingExecutionApprovalModel] = Field(default_factory=list)
    orphaned_approval_ids: List[str] = Field(default_factory=list)


class RecoverExecutionApprovalsRequest(BaseModel):
    """Explicitly retire approvals stranded after their live waiters disappeared."""

    approval_ids: List[str] = Field(min_length=1)

    @field_validator("approval_ids")
    @classmethod
    def validate_approval_ids(cls, approval_ids: List[str]) -> List[str]:
        normalized = [approval_id.strip() for approval_id in approval_ids]
        if any(not approval_id for approval_id in normalized):
            raise ValueError("approval_ids must contain only nonblank values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("approval_ids must not contain duplicates")
        return normalized


class RecoverExecutionApprovalsResponse(BaseModel):
    """Result of retiring orphaned approvals without executing their commands."""

    cancelled_approval_ids: List[str] = Field(default_factory=list)


class ApprovalDecisionResponse(BaseModel):
    """Response after processing approval decision."""
    success: bool
    message: str
    pattern_id: Optional[str] = None


class WhitelistPattern(APIBaseModel):
    """Whitelist pattern model with proper datetime serialization for Swift."""
    id: str
    pattern: str
    pattern_type: str
    description: str
    added_date: datetime
    last_used: Optional[datetime]
    use_count: int
    risk_level: str


class AddWhitelistRequest(BaseModel):
    """Request to add a pattern to whitelist."""
    pattern: str
    pattern_type: str = Field(default="exact", description="Type of pattern: exact, prefix, regex")
    description: str = ""
    risk_level: str = Field(default="low", description="Risk level: low, medium, high")


class RemoveWhitelistRequest(BaseModel):
    """Request to remove a pattern from whitelist."""
    pattern_id: str


class WhitelistResponse(APIBaseModel):
    """Response with whitelist patterns."""
    patterns: List[WhitelistPattern]
    total_count: int


class DeleteWhitelistResponse(BaseModel):
    """Response for deleting a whitelist pattern."""
    success: bool
    message: str


class ApprovalSettingsResponse(BaseModel):
    """Current command approval settings."""
    approval_mode: str
    show_full_command_in_prompt: bool
    remember_choice_option: bool
    auto_approve_read_only: bool
    block_dangerous_patterns: bool
    whitelisted_count: int
    safe_execution_mode: bool
    approval_timeout_seconds: int
    timeout_behavior: str


class UpdateApprovalSettingsRequest(BaseModel):
    """Request to update approval settings."""
    approval_mode: Optional[str] = None
    show_full_command_in_prompt: Optional[bool] = None
    remember_choice_option: Optional[bool] = None
    auto_approve_read_only: Optional[bool] = None
    block_dangerous_patterns: Optional[bool] = None
    safe_execution_mode: Optional[bool] = None
    approval_timeout_seconds: Optional[int] = None
    timeout_behavior: Optional[str] = None


class SessionInteraction(APIBaseModel):
    """A single interaction within a collaborative session."""
    id: str
    agent_task_id: str
    interaction_type: str
    prompt_text: Optional[str]
    user_response: Optional[str]
    response_type: Optional[str]
    step_index: Optional[int]
    step_description: Optional[str]
    step_results: Optional[Dict[str, Any]]
    requires_approval: bool
    approval_status: Optional[str]
    created_at: datetime


class SessionInteractionsResponse(APIBaseModel):
    """Response with session interactions."""
    agent_task_id: str
    interactions: List[SessionInteraction]
    total_count: int


class ContinueSessionResponseModel(BaseModel):
    """Response when continuing a session - matches Swift ContinueSessionResponse."""
    success: bool
    message: str
    session: Optional[Dict[str, Any]] = None
    requires_more_input: bool = False
    result: Optional[str] = None


class CheckpointStatusResponse(BaseModel):
    """Response for checkpoint status check."""
    agent_task_id: str
    has_checkpoint: bool
    can_resume: bool
    message: str
