"""WebSocket event models for real-time communication."""

from enum import Enum
from typing import Optional, Dict, Any, Union, List
from pydantic import BaseModel, Field
import time

class WebSocketEventType(str, Enum):
    """Types of WebSocket events."""
    TRANSCRIPTION_STARTED = "transcription_started"
    TRANSCRIPTION_COMPLETED = "transcription_completed"
    TRANSCRIPTION_FAILED = "transcription_failed"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    CAPTURE_STARTED = "capture_started"
    CAPTURE_COMPLETED = "capture_completed"
    HISTORY_CHAT_EVENT = "history_chat_event"
    ERROR_OCCURRED = "error_occurred"
    STATUS_UPDATE = "status_update"
    
    # Meeting-related event types
    MEETING_INITIALIZED = "meeting_initialized"
    MEETING_STARTED = "meeting_started"
    MEETING_PAUSED = "meeting_paused"
    MEETING_RESUMED = "meeting_resumed"
    MEETING_ENDED = "meeting_ended"
    MEETING_TRANSCRIPT_SEGMENT = "meeting_transcript_segment"
    TRANSCRIPT_REPLACEMENT = "transcript_replacement"
    MEETING_PROCESSING_STARTED = "meeting_processing_started"
    MEETING_PROCESSING_COMPLETED = "meeting_processing_completed"
    MEETING_ERROR = "meeting_error"

class WebSocketEvent(BaseModel):
    """Base model for WebSocket events."""
    event_type: WebSocketEventType
    data: Optional[Dict[str, Any]] = None
    timestamp: float = Field(default_factory=lambda: time.time())

class TranscriptionEvent(WebSocketEvent):
    """Event for transcription-related updates."""
    text: Optional[str] = None
    duration: Optional[float] = None
    model_used: Optional[str] = None

class CaptureEvent(WebSocketEvent):
    """Event for screen capture updates."""
    image_path: Optional[str] = None
    window_title: Optional[str] = None
    app_name: Optional[str] = None

class HistoryChatEvent(WebSocketEvent):
    """Event for history chat updates.
    
    This event is used for interactions with the activity history query system.
    """
    active: bool
    context: Optional[str] = None
    message: Optional[str] = None
    message_type: Optional[str] = None  # "user", "assistant", "system", "error"
    timestamp: Optional[float] = None
    message_id: Optional[str] = None
    is_loading: Optional[bool] = False
    conversation_id: Optional[str] = None  # ID for tracking the conversation

class MeetingEvent(WebSocketEvent):
    """Event for meeting-related updates.
    
    This event is used for operations related to the Meeting Assistant feature.
    """
    meeting_id: str
    name: Optional[str] = None
    purpose: Optional[str] = None
    participants: Optional[List[str]] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    
class MeetingTranscriptEvent(MeetingEvent):
    """Event for meeting transcript segment updates."""
    speaker_id: str
    speaker_name: str
    text: str
    confidence: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    audio_source: Optional[str] = None
    chunk_id: Optional[str] = None  # ID of the audio chunk that generated this transcript
    application_name: Optional[str] = None  # Name of the application for system audio

class MeetingTranscriptReplacementEvent(MeetingEvent):
    """Event for replacing transcript segments with an improved version."""
    new_segment: Dict[str, Any]  # The new segment replacing previous ones
    replaced_segment_ids: List[str]  # IDs of segments being replaced

class MeetingProcessingEvent(MeetingEvent):
    """Event for meeting processing updates."""
    processing_type: str  # "summary", "action_items", "minutes", etc.
    result: Optional[str] = None
    completion_percentage: Optional[float] = None

class ErrorEvent(WebSocketEvent):
    """Event for error notifications."""
    error_message: str
    error_type: Optional[str] = None
    recoverable: bool = True

class StatusEvent(WebSocketEvent):
    """Event for status updates."""
    operation: str
    status: str
    details: Optional[str] = None
    progress: Optional[float] = None 