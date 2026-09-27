"""Route-local models for personalization endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class WritingSamplesCountResponse(BaseModel):
    """Response model for writing samples count."""
    count: int


class DeleteResponse(BaseModel):
    """Standard delete operation response."""
    success: bool
    message: str


class DeleteWithCountResponse(BaseModel):
    """Delete operation response with count."""
    success: bool
    count: int
    message: str


class WritingSamplesListResponse(BaseModel):
    """Response model for writing samples list."""
    samples: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class StyleAnalysisResponse(BaseModel):
    """Response model for style analysis."""
    success: bool
    context_type: str
    profile: Dict[str, Any]
    message: str


class StyleAnalysisAllResponse(BaseModel):
    """Response model for analyze all styles."""
    success: bool
    analyzed_contexts: int
    results: Dict[str, Any]
    message: str


# Request/Response models for saving writing samples
class SaveWritingSampleRequest(BaseModel):
    """Request to save a writing sample."""
    content: str
    context_type: str  # email_reply, email_compose, document, social_media, code, etc.
    recipient: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SaveWritingSampleResponse(BaseModel):
    """Response from saving a writing sample."""
    status: str
    sample_id: str
    context_type: str
    signature_detected: bool = False
    contact_tracked: bool = False
