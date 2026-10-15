"""Typed contracts shared by every Companion module and route."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

COMPANION_SCHEMA_VERSION = 1

ItemKind = Literal["insight", "suggestion", "answer", "context_note", "proposal"]
FeedbackAction = Literal["dismissed", "pinned", "unpinned", "copied", "useful", "not_useful"]
CompanionMode = Literal["active", "passive"]
TimelineKind = Literal["item", "retrieval", "feedback", "chat", "watch", "source", "status", "error", "proposal"]
TurnRole = Literal["self", "other"]
CapacityState = Literal["ok", "deferred", "paused"]
RootKind = Literal["folder", "file"]
ProposalAction = Literal["todo", "agent_task", "assistant_session"]
AutoProposalAction = Literal["todo", "agent_task"]
ProposalAuthority = Literal["review", "watch"]
ProposalState = Literal["proposed", "started", "handed_off", "dismissed", "failed"]
ProposalMode = Literal["suggestion_only", "auto_execute"]


class CompanionTurn(BaseModel):
    """One assembled utterance from a single audio source, on the meeting timeline."""

    id: str
    source_meeting_id: str
    role: TurnRole
    speaker: str
    start: float
    end: float
    text: str


class TranscriptRange(BaseModel):
    """The transcript span an item, retrieval or reply refers to."""

    start: float
    end: float
    turn_ids: List[str] = Field(default_factory=list)


class FileCitation(BaseModel):
    """A cited excerpt from an attached file, resolved by code from a retrieved context pack."""

    path: str
    line_start: int
    line_end: int
    excerpt: str


class ProposalInfo(BaseModel):
    """A follow-up action the investigator proposes, and what became of it. ``authority`` is ``watch`` only when the investigation came from a watch the user created."""

    proposal_id: str
    action: ProposalAction
    title: str
    instruction: str
    authority: ProposalAuthority = "review"
    state: ProposalState = "proposed"
    todo_id: Optional[str] = None
    agent_task_id: Optional[str] = None
    error: Optional[str] = None
    auto_started: bool = False


class CompanionItem(BaseModel):
    """One Companion output shown in the feed."""

    id: str
    kind: ItemKind
    text: str
    confidence: float
    citations: List[FileCitation] = Field(default_factory=list)
    no_source: bool = False
    transcript_range: TranscriptRange
    trigger: str
    watch_id: Optional[str] = None
    truncated: bool = False
    pinned: bool = False
    dismissed: bool = False
    latency_ms: Optional[int] = None
    researched: bool = False
    investigation_id: Optional[str] = None
    evidence_count: int = 0
    proposal: Optional[ProposalInfo] = None


class TimelineEvent(BaseModel):
    """One persisted, timestamped record in the Companion timeline."""

    id: str
    seq: int
    kind: TimelineKind
    meeting_time: float
    wall_time: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class CompanionRoot(BaseModel):
    """A folder or file the user attached as read-only context."""

    id: str
    path: str
    display_name: str
    kind: RootKind
    attached_at: float
    detached_at: Optional[float] = None


class CompanionWatch(BaseModel):
    """A standing request: when the topic comes up, produce the instructed output."""

    id: str
    topic: str
    instruction: str
    keywords: List[str] = Field(default_factory=list)
    created_at: float
    active: bool = True
    last_triggered_at: Optional[float] = None


class ChatMessage(BaseModel):
    """One persisted chat message."""

    id: str
    role: Literal["user", "assistant"]
    text: str
    meeting_time: float
    truncated: bool = False
    status: Literal["complete", "error"] = "complete"


class CompanionSettings(BaseModel):
    """Per-meeting Companion settings."""

    enabled: bool = False
    mode: CompanionMode = "active"
    model_id: Optional[str] = None
    focus: str = ""
    investigate: bool = True


class CompanionGlobalSettings(BaseModel):
    """App-wide Companion defaults."""

    auto_enable: bool = False
    default_mode: CompanionMode = "active"
    screen_share_note_dismissed: bool = False
    next_focus: str = ""
    proposal_mode: ProposalMode = "suggestion_only"
    proposal_capabilities: List[ProposalAction] = Field(default_factory=lambda: ["todo", "agent_task", "assistant_session"])
    auto_execute_capabilities: List[AutoProposalAction] = Field(default_factory=list)


class CompanionStatus(BaseModel):
    """Live status carried in snapshots and status events."""

    live: bool = False
    enabled: bool = False
    mode: CompanionMode = "active"
    model_id: Optional[str] = None
    focus: str = ""
    capacity: CapacityState = "ok"
    capacity_reason: Optional[str] = None
    latest_meeting_time: float = 0.0
    transcription_lag_seconds: float = 0.0
    evaluating: bool = False
    investigating: int = 0
    investigate: bool = True


class CompanionSnapshot(BaseModel):
    """Everything a client needs to render the Companion for one meeting."""

    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    session_key: str
    status: CompanionStatus
    roots: List[CompanionRoot] = Field(default_factory=list)
    items: List[CompanionItem] = Field(default_factory=list)
    watches: List[CompanionWatch] = Field(default_factory=list)
    chat: List[ChatMessage] = Field(default_factory=list)
    retrievals: List[TimelineEvent] = Field(default_factory=list)
    last_seq: int = 0
