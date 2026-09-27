"""Transcription preference models and duration enums."""

from enum import Enum
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator


class ModelPersistenceDuration(Enum):
    """Duration to keep models loaded after last use."""
    SECONDS_30 = 30
    MINUTES_1 = 60
    MINUTES_5 = 300
    MINUTES_30 = 1800
    HOURS_1 = 3600

    @classmethod
    def from_seconds(cls, seconds: int) -> Optional['ModelPersistenceDuration']:
        """Get enum value from seconds."""
        try:
            return next(v for v in cls if v.value == seconds)
        except StopIteration:
            return None

    @property
    def display_name(self) -> str:
        """Get human-readable display name."""
        if self.value < 60:
            return f"{self.value} seconds"
        elif self.value < 3600:
            return f"{self.value // 60} minutes"
        return f"{self.value // 3600} hours"


class TranscriptionModelUnloadDelay(Enum):
    """Delay before unloading the transcription model after widget close."""
    IMMEDIATELY = 0
    SECONDS_5 = 5
    SECONDS_30 = 30
    MINUTES_1 = 60
    MINUTES_2 = 120
    MINUTES_5 = 300
    MINUTES_10 = 600
    MINUTES_30 = 1800
    HOURS_1 = 3600

    @classmethod
    def from_seconds(cls, seconds: int) -> Optional['TranscriptionModelUnloadDelay']:
        """Get enum value from seconds."""
        try:
            return next(v for v in cls if v.value == seconds)
        except StopIteration:
            return None

    @property
    def display_name(self) -> str:
        """Get human-readable display name."""
        if self == TranscriptionModelUnloadDelay.IMMEDIATELY:
            return "Immediately"
        elif self.value < 60:
            return f"{self.value} seconds"
        elif self.value < 3600:
            return f"{self.value // 60} minutes"
        return f"{self.value // 3600} hour"


class TranscriptionTextReplacement(BaseModel):
    """Literal transcription-output substitution configured by the user."""

    source: str = Field(
        ...,
        description="Spoken phrase to match, case-insensitively, as a whole word or phrase",
    )
    replacement: str = Field(
        ...,
        description="Exact text inserted in place of every source match",
    )

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("source cannot be empty")
        if len(normalized) > 120:
            raise ValueError("source cannot exceed 120 characters")
        return normalized

    @field_validator("replacement")
    @classmethod
    def validate_replacement(cls, value: str) -> str:
        if len(value) > 500:
            raise ValueError("replacement cannot exceed 500 characters")
        return value


class TranscriptionSettings(BaseModel):
    """Consolidated transcription settings."""
    model_unload_delay: int = Field(
        default=TranscriptionModelUnloadDelay.MINUTES_1.value,
        description="Delay in seconds before unloading the transcription model after widget close"
    )
    auto_paste: bool = Field(
        default=False,
        description="Automatically paste transcribed text when complete"
    )
    auto_close_on_paste: bool = Field(
        default=False,
        description="Automatically close the transcription widget after pasting"
    )
    language: str = Field(
        default="en",
        description="Default language for transcription"
    )
    selected_model: str = Field(
        default="base",
        description="Selected transcription model"
    )
    widget_size: Tuple[int, int] = Field(
        default=(400, 300),
        description="Size of the transcription widget window (width, height)"
    )
    widget_position: Optional[Tuple[float, float, int]] = Field(
        default=None,
        description="Position of the transcription widget (x, y, screenID)"
    )
    is_widget_minimized: bool = Field(
        default=False,
        description="Whether the transcription widget is in minimized mode"
    )

    # Push-to-talk settings
    enable_push_to_talk: bool = Field(
        default=False,
        description="Enable push-to-talk mode (auto-process on key release after threshold)"
    )
    push_to_talk_threshold_ms: int = Field(
        default=750,
        description="Duration in milliseconds to trigger auto-process on key release (500-5000)"
    )

    # Meeting post-processing automation defaults
    auto_retranscribe_on_stop: bool = Field(
        default=False,
        description="Automatically re-transcribe a meeting with the higher-quality model when recording stops"
    )
    auto_retranscribe_during_recording: bool = Field(
        default=False,
        description="Incrementally re-transcribe elapsed windows with the higher-quality model while recording continues"
    )
    retranscribe_window_seconds: int = Field(
        default=600,
        description="Cadence (in seconds) at which mid-recording windows are re-transcribed (default 10 minutes)"
    )
    auto_analyze_on_complete: bool = Field(
        default=False,
        description="Automatically run meeting analysis after a meeting completes"
    )
    auto_analyze_modes: List[str] = Field(
        default_factory=list,
        description="Analysis modes to run automatically (e.g. summary, action_items, suggested_actions)"
    )
    auto_analyze_custom_instructions: str = Field(
        default="",
        description="Optional custom instructions applied to automatic analysis"
    )
    auto_analyze_timing: Literal["before", "after"] = Field(
        default="after",
        description="Whether automatic analysis runs before or after automatic re-transcription"
    )
    text_replacements: List[TranscriptionTextReplacement] = Field(
        default_factory=list,
        description="Literal substitutions applied to transcription output before copy or auto-paste",
    )

    @field_validator("text_replacements")
    @classmethod
    def validate_text_replacements(
        cls, value: List[TranscriptionTextReplacement]
    ) -> List[TranscriptionTextReplacement]:
        if len(value) > 100:
            raise ValueError("text_replacements cannot exceed 100 rules")
        seen_sources: set[str] = set()
        for rule in value:
            normalized_source = rule.source.lower()
            if normalized_source in seen_sources:
                raise ValueError(
                    f"duplicate text_replacements source: {rule.source}"
                )
            seen_sources.add(normalized_source)
        return value

    @property
    def unload_delay_enum(self) -> Optional[TranscriptionModelUnloadDelay]:
        """Get the transcription model unload delay as an enum value."""
        return TranscriptionModelUnloadDelay.from_seconds(self.model_unload_delay)

    @property
    def unload_delay_display(self) -> str:
        """Get the human-readable transcription model unload delay."""
        if enum_value := self.unload_delay_enum:
            return enum_value.display_name
        return f"{self.model_unload_delay} seconds"
