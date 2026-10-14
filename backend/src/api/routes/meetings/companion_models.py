"""Request and response models for the Meeting Companion routes."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from api.services.meeting_companion.models import CompanionMode, FeedbackAction

FOCUS_MAX_LENGTH = 600


class CompanionGlobalSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_enable: Optional[bool] = None
    default_mode: Optional[CompanionMode] = None
    screen_share_note_dismissed: Optional[bool] = None
    next_focus: Optional[str] = Field(default=None, max_length=FOCUS_MAX_LENGTH)


class CompanionSettingsRequest(BaseModel):
    """Used by enable and by the settings patch; an omitted ``model_id`` leaves the model unchanged, ``null`` clears it."""

    model_config = ConfigDict(extra="forbid")

    mode: Optional[CompanionMode] = None
    model_id: Optional[str] = Field(default=None, max_length=200)
    focus: Optional[str] = Field(default=None, max_length=FOCUS_MAX_LENGTH)


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


class CompanionAck(BaseModel):
    ok: bool = True
