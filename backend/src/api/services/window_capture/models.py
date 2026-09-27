from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class WindowCaptureError(Exception):
    """Base class for window capture errors."""
    def __init__(self, message: str, app_name: Optional[str] = None):
        self.app_name = app_name
        super().__init__(message)


class NoWindowError(WindowCaptureError):
    """Error raised when no window is available for capture."""
    pass


class CaptureFailedError(WindowCaptureError):
    """Error raised when window capture fails."""
    pass


class TextInsertError(WindowCaptureError):
    """Error raised when text insertion fails."""
    pass


class CaptureResponse(BaseModel):
    """Response model for window capture operations."""
    file_path: str
    app_name: str
    window_title: str
    timestamp: datetime
    is_temporary: bool
    extracted_text: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = None


class TextInsertRequest(BaseModel):
    """Request model for text insertion operations."""
    text: str
    target_app: Optional[str] = None  # Optional app name to verify correct target
