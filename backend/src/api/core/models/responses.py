"""Standard response wrappers for consistent API responses."""

from typing import TypeVar, Generic, Optional, Dict, Any
from pydantic import BaseModel, Field

T = TypeVar('T')


class SettingsResponse(BaseModel, Generic[T]):
    """Standard settings response wrapper.

    Used for all settings GET and PUT endpoints to ensure consistent
    response structure across the API.

    Example:
        {
            "status": "success",
            "settings": { ... }
        }
    """
    status: str = Field(default="success", description="Response status")
    settings: T = Field(..., description="Settings data")


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response wrapper.

    Used for successful operations that return data.

    Example:
        {
            "status": "success",
            "data": { ... },
            "message": "Operation completed successfully"
        }
    """
    status: str = Field(default="success", description="Response status")
    data: T = Field(..., description="Response data")
    message: Optional[str] = Field(
        None, description="Optional success message"
    )


class ErrorResponse(BaseModel):
    """Standard error response.

    Used for error responses across the API.

    Example:
        {
            "status": "error",
            "error": "Invalid input",
            "error_code": "VALIDATION_ERROR",
            "details": { "field": "email", "reason": "Invalid format" }
        }
    """
    status: str = Field(default="error", description="Response status")
    error: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(
        None, description="Error code for client handling"
    )
    details: Optional[Dict[str, Any]] = Field(
        None, description="Additional error details"
    )


class StatusResponse(BaseModel):
    """Simple status response.

    Used for operations that only need to indicate success/failure.

    Example:
        {
            "status": "success",
            "message": "Settings updated"
        }
    """
    status: str = Field(..., description="Response status (success/error)")
    message: Optional[str] = Field(None, description="Optional message")


class UpdateResponse(BaseModel, Generic[T]):
    """Standard update response wrapper.

    Used for PUT/PATCH endpoints that update resources.

    Example:
        {
            "status": "updated",
            "updated_settings": { ... },
            "message": "Settings updated successfully"
        }
    """
    status: str = Field(default="updated", description="Response status")
    updated_settings: T = Field(..., description="Updated settings data")
    message: Optional[str] = Field(None, description="Optional message")

