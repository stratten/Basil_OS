"""Pydantic models for the To-Do domain. Snake-case JSON throughout."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TodoStatus = Literal[
    "candidate", "open", "in_progress", "ready_for_review", "completed", "dismissed", "cancelled"
]
TodoResponsibility = Literal["user", "agent", "shared", "unspecified"]
TodoPriority = Literal["low", "normal", "high"]
TodoActorKind = Literal["user", "agent", "system"]

_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "dismissed", "cancelled"})


def is_terminal_todo_status(status: str) -> bool:
    return status in _TERMINAL_STATUSES


def normalize_todo_priority(raw_priority: Optional[str]) -> str:
    """External callers may still send legacy `medium`; normalize before persistence."""
    if not raw_priority:
        return "normal"
    candidate = raw_priority.strip().lower()
    if candidate == "medium":
        return "normal"
    if candidate in ("low", "normal", "high"):
        return candidate
    return "normal"


class TodoSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    todo_id: str
    source_kind: str
    source_id: str
    source_locator: Dict[str, Any] = Field(default_factory=dict)
    source_excerpt: str = ""
    created_by_kind: TodoActorKind
    created_at: str


class TodoWorkAttempt(BaseModel):
    """Read-only projection of one directly sourced Agent Task."""
    model_config = ConfigDict(extra="forbid")

    agent_task_id: str
    title: Optional[str] = None
    status: str
    created_at: str
    updated_at: str
    result_summary: Optional[str] = None
    outcome: Optional[str] = None
    result_severity: Optional[str] = None
    attention: bool = False


class TodoAttention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs_attention: bool = False
    reason: Optional[str] = None


class TodoAgentStatusSummary(BaseModel):
    """The single most-relevant Agent Task status for one To-Do, projected
    from `AgentTaskQueries.list_latest_agent_task_status_by_origins`."""

    model_config = ConfigDict(extra="forbid")

    agent_task_id: str
    status: str
    result_severity: Optional[str] = None
    is_active: bool
    updated_at: str


class TodoItemSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: TodoStatus
    responsibility: TodoResponsibility
    priority: TodoPriority
    due_at: Optional[str] = None
    completed_at: Optional[str] = None
    revision: int
    created_at: str
    updated_at: str
    attention: TodoAttention = Field(default_factory=TodoAttention)
    agent_status: Optional[TodoAgentStatusSummary] = None


class TodoReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    todo_id: str
    path: str
    created_by_kind: TodoActorKind
    created_by_id: Optional[str] = None
    created_at: str


class TodoItemDetail(TodoItemSummary):
    description: str = ""
    notes: str = ""
    idempotency_key: Optional[str] = None
    created_by_kind: TodoActorKind
    created_by_id: Optional[str] = None
    sources: List[TodoSource] = Field(default_factory=list)
    references: List[TodoReference] = Field(default_factory=list)
    worker_attempts: List[TodoWorkAttempt] = Field(default_factory=list)


class TodoWorkerLaunchResponse(BaseModel):
    """The durable To-Do state and exact Agent Task created for one launch."""

    model_config = ConfigDict(extra="forbid")

    item: TodoItemDetail
    agent_task_id: str


class TodoWorkspaceHydration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[TodoItemSummary]
    next_cursor: Optional[str] = None
    has_more: bool = False
    counts_by_status: Dict[str, int] = Field(default_factory=dict)


class CreateTodoItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    notes: str = ""
    responsibility: TodoResponsibility = "unspecified"
    priority: TodoPriority = "normal"
    due_at: Optional[str] = None
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not (1 <= len(trimmed) <= 240):
            raise ValueError("title must be between 1 and 240 characters")
        return trimmed

    @field_validator("description", "notes")
    @classmethod
    def validate_bounded_text(cls, value: str) -> str:
        if len(value) > 12000:
            raise ValueError("field must be at most 12000 characters")
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: Any) -> str:
        return normalize_todo_priority(value if isinstance(value, str) else None)


class UpdateTodoItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    title: Optional[str] = None
    description: Optional[str] = None
    responsibility: Optional[TodoResponsibility] = None
    priority: Optional[TodoPriority] = None
    due_at: Optional[str] = None
    completed_at: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not (1 <= len(trimmed) <= 240):
            raise ValueError("title must be between 1 and 240 characters")
        return trimmed

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and len(value) > 12000:
            raise ValueError("description must be at most 12000 characters")
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: Any) -> Any:
        if value is None:
            return None
        return normalize_todo_priority(value if isinstance(value, str) else None)

    @model_validator(mode="after")
    def require_a_mutable_field(self) -> "UpdateTodoItemRequest":
        changed_fields = self.model_fields_set - {"expected_revision"}
        if not changed_fields:
            raise ValueError("at least one mutable field is required")
        if any(
            getattr(self, field) is None
            for field in changed_fields
            if field not in {"due_at", "completed_at"}
        ):
            raise ValueError("only due_at may be cleared with null")
        return self


class ReplaceTodoNotesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str
    expected_revision: int = Field(ge=1)

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str) -> str:
        if len(value) > 12000:
            raise ValueError("notes must be at most 12000 characters")
        return value


class AddTodoReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    path: str

    @field_validator("path")
    @classmethod
    def validate_absolute_path(cls, value: str) -> str:
        trimmed = value.strip()
        if "\x00" in trimmed or not trimmed or len(trimmed) > 4096 or not os.path.isabs(trimmed):
            raise ValueError("path must be a nonblank absolute path of at most 4096 characters without NUL bytes")
        return trimmed


class RemoveTodoReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class ExpectedRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class LaunchTodoWorkerRequest(BaseModel):
    """The worker's prompt is always deterministically built from the To-Do's
    title/description/notes by `TodoAgentTaskBridge.launch_todo_item_agent_task`;
    this request intentionally carries no caller-supplied purpose or prompt
    override, so there is no unused field a client could be misled by."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class PromoteMeetingProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    filename: str
    proposal_id: str
    source_task: str
    suggested_agent_task: str
    why_basil_can_help: str = ""
    source_context: Optional[str] = None


class TodoConflictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
    item: TodoItemDetail
