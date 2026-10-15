"""Request and response models for the Meeting Companion routes."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from api.services.meeting_companion.investigator.models import MAX_QUESTION_CHARS
from api.services.meeting_companion.models import AutoProposalAction, CompanionMode, FeedbackAction, ProposalAction, ProposalMode, ProposalState

FOCUS_MAX_LENGTH = 600


class CompanionGlobalSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_enable: Optional[bool] = None
    default_mode: Optional[CompanionMode] = None
    screen_share_note_dismissed: Optional[bool] = None
    next_focus: Optional[str] = Field(default=None, max_length=FOCUS_MAX_LENGTH)
    proposal_mode: Optional[ProposalMode] = None
    proposal_capabilities: Optional[List[ProposalAction]] = Field(default=None, max_length=6)
    auto_execute_capabilities: Optional[List[AutoProposalAction]] = Field(default=None, max_length=6)


class CompanionSettingsRequest(BaseModel):
    """Used by enable and by the settings patch; an omitted ``model_id`` leaves the model unchanged, ``null`` clears it."""

    model_config = ConfigDict(extra="forbid")

    mode: Optional[CompanionMode] = None
    model_id: Optional[str] = Field(default=None, max_length=200)
    focus: Optional[str] = Field(default=None, max_length=FOCUS_MAX_LENGTH)
    investigate: Optional[bool] = None


class CompanionRootRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)


class CompanionFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: FeedbackAction


class CompanionChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class CompanionChatAccepted(BaseModel):
    message_id: str


class CompanionWatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=200)
    instruction: str = Field(default="", max_length=600)


class CompanionInvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class CompanionInvestigationAccepted(BaseModel):
    investigation_id: str


class CompanionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "dismiss"]


class CompanionProposalResult(BaseModel):
    state: ProposalState
    title: str
    instruction: str
    todo_id: Optional[str] = None
    agent_task_id: Optional[str] = None
    error: Optional[str] = None


class CompanionAck(BaseModel):
    ok: bool = True
