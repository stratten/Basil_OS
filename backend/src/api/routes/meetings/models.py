"""Models for meeting routes."""

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel

from .analysis_summary import MeetingAnalysisSummary


class MeetingInfo(BaseModel):
    """Meeting information for starting a recording."""
    name: str
    purpose: Optional[str] = None
    participants: Optional[List[str]] = None


class MeetingMetadataUpdate(BaseModel):
    """Editable meeting metadata fields."""
    name: str
    purpose: Optional[str] = None
    participants: Optional[List[str]] = None


class PostProcessingConfig(BaseModel):
    """Configuration for post-processing a meeting."""
    model: str  # e.g. "Large V3", "base", etc.
    operation: str = "both"  # "both" (default), "transcribe", or "diarize"


class RetranscribeWindowConfig(BaseModel):
    """Configuration for re-transcribing a closed time window of a meeting.

    Used for incremental, mid-recording upgrades: the client requests a
    ``[start_seconds, end_seconds)`` range be re-transcribed with the
    higher-quality model and gets back absolute-timeline segments to splice into
    the live transcript.
    """
    model: str
    start_seconds: float
    end_seconds: float
    live: bool = True  # Read the still-growing audio.wav by default


class MeetingAnalysisConfig(BaseModel):
    """Configuration for analyzing a meeting."""
    model_id: Optional[str] = None  # Reasoning model ID (defaults to user preference)
    analysis_modes: List[str]  # e.g. ["action_items", "summary", "decisions"]
    custom_instructions: Optional[str] = None  # Additional user instructions


class ProposalOutcomeUpdate(BaseModel):
    """Persisted outcome for a single suggested-action proposal."""
    execution_status: str
    submitted_agent_task_id: Optional[str] = None
    todo_id: Optional[str] = None


class MeetingSearchFilters(BaseModel):
    """Structured, composable constraints for the meeting history search."""
    query: str = ""
    query_mode: Literal["and", "or"] = "and"
    name: str = ""
    name_mode: Literal["and", "or"] = "and"
    purpose: str = ""
    purpose_mode: Literal["and", "or"] = "and"
    participants: str = ""
    participants_mode: Literal["and", "or"] = "and"
    transcript: str = ""
    transcript_mode: Literal["and", "or"] = "and"
    source: str = ""
    source_mode: Literal["and", "or"] = "and"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    processing: Literal["any", "complete", "incomplete"] = "any"
    analysis: Literal["any", "has_analysis", "no_analysis"] = "any"

    @property
    def has_invalid_date_range(self) -> bool:
        return bool(self.start_date and self.end_date and self.start_date > self.end_date)

    @property
    def has_text_constraints(self) -> bool:
        return any(value.strip() for value in (
            self.query,
            self.name,
            self.purpose,
            self.participants,
            self.transcript,
        ))

    @property
    def is_active(self) -> bool:
        return self.has_text_constraints or bool(self.source.strip()) or any((
            self.start_date,
            self.end_date,
            self.processing != "any",
            self.analysis != "any",
        ))


class MeetingResponse(BaseModel):
    """Response containing meeting metadata."""
    id: str
    name: str
    purpose: Optional[str]
    participants: List[str]
    start_time: str
    end_time: Optional[str]
    duration_seconds: Optional[float]
    audio_path: Optional[str]
    transcript_path: Optional[str]
    is_post_processed: bool
    session_id: Optional[str] = None  # Shared id linking mic + system-audio recordings of one meeting
    audio_source: Optional[str] = None  # Source of this recording (e.g. "Microphone", "Zoom")
    # For grouped (multi-source / resumed) meetings: one entry per member recording.
    # Each item is {"id": str, "source": Optional[str], "is_post_processed": bool,
    # "start_time": Optional[str], "duration_seconds": Optional[float],
    # "timeline_offset_seconds": Optional[float], "recording_part_index": Optional[int]}.
    members: Optional[List[dict]] = None
    analysis_summary: Optional[MeetingAnalysisSummary] = None
