"""Typed contracts for BasilBoard persistence and API responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class BasilBoardTabKind(str, Enum):
    HOME = "home"
    CAPABILITY = "capability"
    SYSTEM_EMBED = "system_embed"
    AGENT_REPORT = "agent_report"


class BasilBoardTabStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class HomeTurnRouteKind(str, Enum):
    CONVERSATION = "conversation"
    AGENT_TASK = "agent_task"


class HomeTurnState(str, Enum):
    ROUTING = "routing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


SUPPORTED_TAB_KINDS = {kind.value for kind in BasilBoardTabKind}
SUPPORTED_ARTIFACT_KINDS: set[str] = set()
SUPPORTED_ARTIFACT_SCHEMA_VERSIONS: dict[str, set[str]] = {}


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    label: Optional[str] = None


class BasilBoardTab(BaseModel):
    id: str
    title: str
    icon_key: Optional[str] = None
    position: int = 0
    tab_kind: BasilBoardTabKind
    status: BasilBoardTabStatus = BasilBoardTabStatus.ACTIVE
    configuration: Dict[str, Any] = Field(default_factory=dict)
    created_by_kind: str = "system"
    created_by_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class HomeState(BaseModel):
    id: str = "default"
    conversation_id: str
    updated_at: Optional[str] = None


class HomeTurnRoute(BaseModel):
    route_kind: HomeTurnRouteKind
    reason: str
    confidence: Optional[float] = None


class HomeTurn(BaseModel):
    user_message_id: str
    conversation_id: str
    route_kind: HomeTurnRouteKind
    route_reason: str
    route_confidence: Optional[float] = None
    agent_task_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    state: HomeTurnState
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LinkedAgentTaskSummary(BaseModel):
    agent_task_id: str
    user_message_id: str
    state: HomeTurnState
    status: Optional[str] = None
    result: Optional[str] = None
    outcome: Optional[str] = None


class BoardInquirySummary(BaseModel):
    """A single durable, independently-addressable Home submission. One
    inquiry = one prompt -> one route -> one outcome; the durability and
    independent identity is the point, not multi-message threading."""

    id: str
    promptText: str
    displayMarkdown: Optional[str] = None
    referencePaths: List[str] = Field(default_factory=list)
    routeKind: Optional[HomeTurnRouteKind] = None
    routeReason: Optional[str] = None
    routeConfidence: Optional[float] = None
    state: HomeTurnState
    conversationId: Optional[str] = None
    agentTaskId: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class BoardInquiryDetail(BoardInquirySummary):
    timeline: List[Dict[str, Any]] = Field(default_factory=list)


class HomeTimelineUserMessage(BaseModel):
    kind: Literal["user_message"] = "user_message"
    messageId: str
    content: str
    displayMarkdown: Optional[str] = None
    referencePaths: List[str] = Field(default_factory=list)
    createdAt: str


class HomeTimelineConversationAnswer(BaseModel):
    kind: Literal["conversation_answer"] = "conversation_answer"
    messageId: str
    inReplyTo: str
    content: str
    createdAt: str


class HomeTimelineAgentTask(BaseModel):
    kind: Literal["agent_task"] = "agent_task"
    messageId: str
    inReplyTo: str
    agentTaskId: str
    state: Literal["queued", "running", "completed", "failed", "canceled"]
    result: Optional[str] = None
    outcome: Optional[str] = None
    createdAt: str


HomeTimelineItem = (
    HomeTimelineUserMessage
    | HomeTimelineConversationAnswer
    | HomeTimelineAgentTask
)


class BasilBoardArtifact(BaseModel):
    id: str
    tab_id: str
    artifact_kind: str
    schema_version: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    source_refs: List[SourceReference] = Field(default_factory=list)
    coverage: Dict[str, Any] = Field(default_factory=dict)
    owner_task_id: Optional[str] = None
    owner_run_id: Optional[str] = None
    status: str = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("artifact_kind")
    @classmethod
    def validate_artifact_kind(cls, value: str) -> str:
        if value not in SUPPORTED_ARTIFACT_KINDS:
            raise ValueError(f"Unsupported artifact kind: {value}")
        return value

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str, info) -> str:
        kind = info.data.get("artifact_kind")
        if not kind or value not in SUPPORTED_ARTIFACT_SCHEMA_VERSIONS.get(kind, set()):
            raise ValueError(f"Unsupported schema version {value} for {kind or 'unknown kind'}")
        return value


class BasilBoardHydration(BaseModel):
    tabs: List[BasilBoardTab]
    recent_inquiries: List[BoardInquirySummary] = Field(default_factory=list)
    supported_tab_kinds: List[str] = Field(default_factory=lambda: sorted(SUPPORTED_TAB_KINDS))
    supported_renderer_kinds: List[str] = Field(
        default_factory=lambda: [
            "home",
            "todos.workspace",
            "conversations.history",
            "meetings.history",
            "agent_tasks.history",
        ]
    )


class HomeTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    display_prompt_markdown: Optional[str] = None
    reference_paths: List[StrictStr] = Field(default_factory=list)
    model_id: Optional[str] = None

    @field_validator("reference_paths")
    @classmethod
    def normalize_reference_paths(cls, value: List[StrictStr]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for raw_path in value:
            path = raw_path.strip()
            if not path:
                raise ValueError("reference_paths must not contain blank paths")
            if path not in seen:
                seen.add(path)
                normalized.append(path)
        if len(normalized) > 32:
            raise ValueError("reference_paths must contain at most 32 paths")
        return normalized


class HomeTurnRerouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_kind: HomeTurnRouteKind


class HomeTurnResponse(BaseModel):
    inquiry_id: str
    user_message_id: Optional[str] = None
    conversation_id: Optional[str] = None
    route_kind: HomeTurnRouteKind
    route_reason: str
    route_confidence: Optional[float] = None
    state: HomeTurnState
    assistant_message_id: Optional[str] = None
    agent_task_id: Optional[str] = None
    assistant_content: Optional[str] = None


class HomeTranscribeResponse(BaseModel):
    success: bool
    transcription: str = ""
    error_code: Optional[str] = None


class BasilBoardError(Exception):
    """Base exception for BasilBoard domain errors."""
