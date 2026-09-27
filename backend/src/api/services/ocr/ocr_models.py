"""Data models and exceptions for OCR text extraction service."""

from typing import Dict, Any, Optional
from pydantic import BaseModel


class OCRError(Exception):
    """Error occurred during OCR text extraction processing."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class OCRResult(BaseModel):
    """Result of OCR text extraction processing."""
    status: str  # "success" or "error"
    image_path: str
    app_name: Optional[str] = None
    raw_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    processed_text: Optional[str] = None
    # New fields for pre-formatted display text
    formatted_text: Optional[str] = None  # HTML or other format ready for display
    format_type: Optional[str] = None  # "html", "markdown", or "plain"
    error: Optional[str] = None
    error_type: Optional[str] = None
    processing_time_ms: int 