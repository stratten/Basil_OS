"""Request and response models for API model settings routes."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class APIKeyRequest(BaseModel):
    """Model for API key request."""
    provider: str
    key: str


class APIKeyResponse(BaseModel):
    """Model for API key response."""
    provider: str
    has_key: bool
    key_preview: Optional[str] = None
    available_models: Dict[str, Dict[str, Any]] = {}


class APIKeyTestRequest(BaseModel):
    """Model for testing an API key."""
    provider: str
    key: Optional[str] = None  # If None, use the stored key


class APIKeyTestResponse(BaseModel):
    """Model for API key test response."""
    provider: str
    valid: bool
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class APIModelUpdateRequest(BaseModel):
    """Model for updating a specific API model's settings."""
    enabled: bool = Field(
        ...,
        description="Whether this model should be enabled"
    )
    set_as_default_for: Optional[List[str]] = Field(
        default=None,
        description="List of capabilities to set this as the default for (e.g., ['reasoning', 'vision'])"
    )


class APIProviderUpdateRequest(BaseModel):
    """Model for enabling or disabling an API provider."""
    enabled: bool = Field(
        ...,
        description="Whether this provider should be enabled"
    )
    use_own_api_key: bool = Field(
        default=False,
        description="Whether to use user's own API key (true) or the application's built-in key (false)"
    )


class APIModelToggleRequest(BaseModel):
    """Model for toggling the master API models switch."""
    enabled: bool = Field(
        ...,
        description="Whether to enable or disable all API models"
    )


class APIModelsInfoResponse(BaseModel):
    """Response model for GET /api_models/"""
    status: str = "success"
    api_models: Dict[str, Any]
    settings: Dict[str, Any]


class APIProviderUpdateResponse(BaseModel):
    """Response model for updating API provider settings."""
    status: str = "updated"
    provider: Dict[str, Any]


class APIModelToggleResponse(BaseModel):
    """Response model for toggling API models."""
    status: str = "success"
    api_models_enabled: bool
    providers_enabled: Dict[str, bool]
    current_models: Dict[str, str]


class APIModelUpdateResponse(BaseModel):
    """Response model for updating a specific API model."""
    status: str = "updated"
    model: Dict[str, Any]


class ReasoningModelItem(BaseModel):
    """One selectable reasoning model with a canonical identity."""

    id: str
    name: str
    display_name: str
    provider: str
    category: Literal["local", "api", "custom"]
    is_api_model: bool
    description: Optional[str] = None


class ReasoningModelsResponse(BaseModel):
    """Response model for GET /reasoning"""
    status: str = "success"
    models: List[ReasoningModelItem]
    api_models_enabled: bool
    current_model: str
    fallback_enabled: bool = False
    fallback_model_id: str = ""


class TranscriptionAPIModelsResponse(BaseModel):
    """Response model for GET /transcription"""
    status: str = "success"
    models: List[Dict[str, Any]]
    api_transcription_models_enabled: bool
    current_model: str
    providers: Dict[str, Dict[str, Any]] = {}


class TranscriptionAPIToggleRequest(BaseModel):
    """Model for toggling the master API transcription models switch."""
    enabled: bool = Field(
        ...,
        description="Whether to enable or disable API transcription models"
    )


class TranscriptionAPIToggleResponse(BaseModel):
    """Response model for toggling API transcription models."""
    status: str = "success"
    api_transcription_models_enabled: bool
    providers_enabled: Dict[str, bool]


class TranscriptionAPIProviderUpdateRequest(BaseModel):
    """Model for enabling or disabling a transcription API provider."""
    enabled: bool = Field(
        ...,
        description="Whether this transcription provider should be enabled"
    )


class TranscriptionAPIProviderUpdateResponse(BaseModel):
    """Response model for updating a transcription API provider."""
    status: str = "updated"
    provider: Dict[str, Any]


class TranscriptionAPIModelUpdateRequest(BaseModel):
    """Model for updating a specific transcription API model's settings."""
    enabled: bool = Field(
        ...,
        description="Whether this transcription model should be enabled"
    )
    set_as_default: bool = Field(
        default=False,
        description="Whether to set this as the default transcription model"
    )


class TranscriptionAPIModelUpdateResponse(BaseModel):
    """Response model for updating a specific transcription API model."""
    status: str = "updated"
    model: Dict[str, Any]


class APIKeysResponse(BaseModel):
    """Response model for GET /api_keys"""
    providers: List[APIKeyResponse]


class APIKeyUpdateResponse(BaseModel):
    """Response model for API key operations."""
    status: str
    message: str
