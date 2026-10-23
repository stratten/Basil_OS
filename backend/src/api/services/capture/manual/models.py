"""Data models for capture handler."""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class CaptureRequest(BaseModel):
    """Request model for capture operations."""
    temporary: bool = Field(default=False, description="Whether to store the capture temporarily")
    force_text_only: bool = Field(default=False, description="Deprecated: Always uses text-only analysis now")


class ActivitySummary(BaseModel):
    """Summary of an activity for display in the UI."""
    id: str = Field(..., description="Unique identifier for the activity")
    timestamp: datetime = Field(..., description="When the activity occurred")
    app_name: str = Field(..., description="Name of the application")
    window_title: Optional[str] = Field(None, description="Title of the window")
    preview_text: Optional[str] = Field(None, description="Preview of the extracted text")
    has_analysis: bool = Field(default=False, description="Whether AI analysis is available")
    has_image: bool = Field(default=False, description="Whether an image is available")
    analysis_type: str = Field(default="unknown", description="Type of analysis performed (text-only, none)")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class CaptureResponse(BaseModel):
    """Response model for capture operations."""
    success: bool = Field(..., description="Whether the operation was successful")
    timestamp: datetime = Field(..., description="When the capture was taken")
    app_name: Optional[str] = Field(None, description="Name of the application")
    window_title: Optional[str] = Field(None, description="Title of the window")
    image_path: Optional[str] = Field(None, description="Path to the captured image")
    extracted_text: Optional[str] = Field(None, description="Text extracted from the image")
    analysis: Optional[Dict[str, Any]] = Field(None, description="AI analysis of the content")
    analysis_type: str = Field(default="unknown", description="Type of analysis performed (text-only, none)")
    activity_id: Optional[str] = Field(None, description="ID of the stored activity")
    error: Optional[str] = Field(None, description="Error message if operation failed")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class SimilarActivitiesRequest(BaseModel):
    """Request model for finding similar activities."""
    content: str = Field(..., description="Text content to match against")
    app_name: Optional[str] = Field(None, description="Filter by application name")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of results to return")


class SimilarActivitiesResponse(BaseModel):
    """Response model for similar activities."""
    success: bool = Field(..., description="Whether the operation was successful")
    count: int = Field(default=0, description="Number of activities found")
    activities: List[ActivitySummary] = Field(default_factory=list, description="List of similar activities")
    error: Optional[str] = Field(None, description="Error message if operation failed")


class RecentActivitiesResponse(BaseModel):
    """Response model for recent activities."""
    success: bool = Field(..., description="Whether the operation was successful")
    count: int = Field(default=0, description="Number of activities found")
    activities: List[ActivitySummary] = Field(default_factory=list, description="List of recent activities")
    error: Optional[str] = Field(None, description="Error message if operation failed")


class CleanupResponse(BaseModel):
    """Response model for cleanup operations."""
    success: bool = Field(..., description="Whether the operation was successful")
    message: Optional[str] = Field(None, description="Success message")
    error: Optional[str] = Field(None, description="Error message if operation failed")

# Note: ProcessingResponse has been moved to image_processing.image_models
# Use: from ..image_processing.image_models import ProcessingResponse 