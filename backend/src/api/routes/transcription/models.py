"""Models and constants for transcription routes."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TranscriptionResponse(BaseModel):
    """Response model for basic transcription."""
    success: bool
    text: Optional[str] = None
    error: Optional[str] = None


class TranscriptionHistoryResponse(BaseModel):
    """Response model for transcription history."""
    success: bool
    transcriptions: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


class TranscriptionSearchResponse(BaseModel):
    """Response model for transcription search."""
    success: bool
    transcriptions: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


class TranscriptionFeedbackResponse(BaseModel):
    """Response model for transcription feedback."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class TranscriptionUpdateResponse(BaseModel):
    """Response model for transcription update."""
    success: bool
    message: Optional[str] = None
    transcription: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TranscriptionFileResponse(BaseModel):
    """Response model for file transcription."""
    success: bool
    text: Optional[str] = None
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    language: Optional[str] = None
    error: Optional[str] = None


class TranscriptionDeleteResponse(BaseModel):
    """Response model for transcription deletion."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class RetranscribeResponse(BaseModel):
    """Response model for retranscription."""
    success: bool
    text: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class RetranscribeRequest(BaseModel):
    """Request model for retranscription."""
    model_id: Optional[str] = None


ALLOWED_AUDIO_TYPES = [
    'audio/wav',
    'audio/x-wav',
    'audio/wave',
    'audio/webm',
    'audio/ogg',
    'audio/mpeg',
    'audio/mp3',
    'audio/mp4',
    'audio/aac',
    'audio/flac',
    'audio/x-flac',
    'audio/x-m4a'
]
