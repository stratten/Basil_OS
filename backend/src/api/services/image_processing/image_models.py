from pydantic import BaseModel, Field, constr
from typing import Optional, Dict, Any, List
from datetime import datetime

class ImageProcessingError(Exception):
    """Base exception for image processing errors."""
    pass

class OCRError(ImageProcessingError):
    """Raised when OCR text extraction fails."""
    pass

class AnalysisError(ImageProcessingError):
    """Raised when AI analysis of the image fails."""
    pass

class TextAnalysisRequest(BaseModel):
    """Request model for text analysis."""
    text: constr(min_length=1, max_length=10000)  # Reasonable limits for text length
    app_name: constr(min_length=1, max_length=100)
    custom_prompt: Optional[str] = Field(None, max_length=2000)
    model_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "text": "Sample text to analyze",
                "app_name": "Visual Studio Code",
                "custom_prompt": None,
                "model_id": None
            }
        }

class ActivityAnalysis(BaseModel):
    """Model for activity analysis results."""
    activity_type: str = "unknown"  # Type of activity (coding, writing, browsing, etc.)
    context: str = ""  # Context of what the user is doing
    content_summary: str = ""  # Summary of the content
    entities: List[Dict[str, Any]] = []  # Extracted entities (people, projects, topics)
    skills: List[str] = []  # Skills being used or demonstrated
    topics: List[str] = []  # Topics being discussed or worked on
    sentiment: Optional[str] = None  # Optional sentiment analysis
    complexity: Optional[str] = None  # Optional complexity assessment
    
    class Config:
        json_schema_extra = {
            "example": {
                "activity_type": "coding",
                "context": "User is working on a Python web application",
                "content_summary": "Implementing an authentication system using Flask",
                "entities": [
                    {"type": "project", "name": "web_app", "confidence": 0.9},
                    {"type": "technology", "name": "Flask", "confidence": 0.95}
                ],
                "skills": ["Python", "Web Development", "Authentication"],
                "topics": ["security", "web development", "user management"],
                "sentiment": "focused",
                "complexity": "moderate"
            }
        }

class ProcessingResponse(BaseModel):
    """Response model for image processing results."""
    extracted_text: str
    analysis: ActivityAnalysis
    timestamp: datetime = Field(default_factory=datetime.now)
    app_name: Optional[str] = None
    window_title: Optional[str] = None
    analysis_type: str = "unknown"  # Type of analysis: text-only, none, error
    processing_time_ms: Optional[int] = None
    error: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "extracted_text": "Sample extracted text",
                "analysis": {
                    "activity_type": "coding",
                    "context": "User is working on a Python web application",
                    "content_summary": "Implementing an authentication system using Flask",
                    "entities": [
                        {"type": "project", "name": "web_app", "confidence": 0.9},
                        {"type": "technology", "name": "Flask", "confidence": 0.95}
                    ],
                    "skills": ["Python", "Web Development", "Authentication"],
                    "topics": ["security", "web development", "user management"],
                    "sentiment": "focused",
                    "complexity": "moderate"
                },
                "timestamp": "2024-03-14T12:00:00",
                "app_name": "Visual Studio Code",
                "window_title": "auth.py - Web App",
                "analysis_type": "text-only",
                "processing_time_ms": 1500
            }
        }

# analysis_type values that mean the model never produced a usable analysis:
# "none" (no reasoning model could be loaded) and "error" (the response could
# not be parsed). Both leave placeholder prose in `analysis`.
FAILED_ANALYSIS_TYPES = frozenset({"error", "none"})


def raise_if_analysis_unusable(result: ProcessingResponse) -> None:
    """Reject a failed analysis instead of storing its placeholder as a result."""
    if result.analysis_type in FAILED_ANALYSIS_TYPES:
        detail = f": {result.error}" if result.error else ""
        raise AnalysisError(
            f"Activity analysis unusable (analysis_type={result.analysis_type}){detail}"
        )
    if not result.analysis:
        raise AnalysisError("Activity analysis returned no analysis object")
