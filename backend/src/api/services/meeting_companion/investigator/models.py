"""Contracts, limits and constants for the Companion investigator. Every cost-control knob lives in this one module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..models import CompanionTurn, FileCitation

MAX_RUNS_PER_MEETING = 10
RUN_DEADLINE_SECONDS = 75.0
CONCLUDE_TIMEOUT_SECONDS = 45.0
MAX_TOOL_CALLS = 8
MAX_CONCURRENT_LOCAL = 1
MAX_CONCURRENT_API = 2
MAX_QUESTION_CHARS = 300
MAX_ANSWER_CHARS = 900
MAX_TOOL_OUTPUT_CHARS = 6000
MAX_EVIDENCE_ENTRIES = 32
SEARCH_EVIDENCE_ENTRIES = 20
FIND_CONTEXT_LINES = 6
MAX_FIND_WINDOWS = 5
MAX_EXCERPT_CHARS = 1200
MAX_RECORD_EXCERPT_CHARS = 600
READ_WINDOW_LINES = 120
DUPLICATE_QUESTION_SIMILARITY = 0.6
MIN_CONFIDENCE = 0.4
API_HANDLERS = ("openai_api", "anthropic_api", "gemini_api")
RECORD_SOURCE_KINDS = ("meeting", "transcription", "conversation", "agent_task", "assistant_output")
AUTOMATIC_ORIGINS = ("unanswered", "watch")

InvestigationOrigin = Literal["unanswered", "watch", "chat", "explicit"]
InvestigationStatus = Literal["completed", "not_found", "failed", "canceled", "timed_out"]


class InvestigationRejected(ValueError):
    """Raised with a user-facing reason when an investigation may not start."""


class ProposedAction(BaseModel):
    """One follow-up the model suggests after a supported answer. Code shapes, caps and filters it."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["todo", "agent_task", "assistant_session"]
    title: str
    instruction: str


class InvestigationConclusion(BaseModel):
    """The one structured answer the model writes after the evidence has been gathered."""

    model_config = ConfigDict(extra="forbid")

    found: bool
    answer: str = ""
    confidence: float = 0.0
    evidence_ids: List[str] = Field(default_factory=list)
    proposals: List[ProposedAction] = Field(default_factory=list)


@dataclass
class InvestigationRequest:
    investigation_id: str
    origin: InvestigationOrigin
    question: str
    meeting_time: float
    window_turns: List[CompanionTurn]
    conversation_state: str
    focus: str = ""
    model_id: Optional[str] = None
    watch_id: Optional[str] = None
    source_turn_ids: List[str] = field(default_factory=list)
    # The chat message the question came from, so the answer can quote it.
    reply_to_message_id: Optional[str] = None


@dataclass
class InvestigationResult:
    investigation_id: str
    status: InvestigationStatus
    answer: str = ""
    confidence: float = 0.0
    citations: List[FileCitation] = field(default_factory=list)
    tool_calls: int = 0
    evidence_count: int = 0
    duration_ms: int = 0
    detail: str = ""
    proposals: List[ProposedAction] = field(default_factory=list)
