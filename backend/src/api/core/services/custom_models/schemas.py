"""
Pydantic schemas for Custom Models API.

Contains all request and response models for custom model operations.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from api.core.models.models_registry import ModelHandler


# Handler types that are API-based (require base_url and model_identifier)
API_HANDLERS = {
    ModelHandler.OPENAI_COMPATIBLE.value,
    ModelHandler.ANTHROPIC_COMPATIBLE.value,
}

SERVER_TYPE_OPENAI_COMPATIBLE = "openai_compatible"
SERVER_TYPE_OLLAMA = "ollama"
SERVER_TYPES = (SERVER_TYPE_OPENAI_COMPATIBLE, SERVER_TYPE_OLLAMA)


def _validate_server_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    if value not in SERVER_TYPES:
        raise ValueError(f"server_type must be one of {list(SERVER_TYPES)}, got '{value}'")
    return value


# =============================================================================
# CRUD SCHEMAS
# =============================================================================


class CustomModelCreate(BaseModel):
    """Request body for creating a custom model."""
    
    model_id: str = Field(..., description="Unique identifier for the model")
    display_name: str = Field(..., description="Human-readable name")
    handler: str = Field(..., description="Handler type: 'openai_compatible', 'anthropic_compatible', or 'llama_cpp'")
    
    # API model fields (required for openai_compatible/anthropic_compatible)
    base_url: Optional[str] = Field(default=None, description="API endpoint URL (e.g., 'http://localhost:11434/v1')")
    model_identifier: Optional[str] = Field(default=None, description="Model name sent in API calls (e.g., 'llama3.2')")
    
    # Local model fields (for llama_cpp handler)
    model_path: Optional[str] = Field(default=None, description="Path to local model file (e.g., '/path/to/model.gguf')")
    download_url: Optional[str] = Field(default=None, description="HuggingFace repo URL for downloading")
    
    # Common fields
    context_window: int = Field(..., gt=0, description="Maximum input tokens")
    max_output_tokens: int = Field(..., gt=0, description="Maximum output tokens")
    requires_auth: bool = Field(default=False, description="Whether API key is required")
    api_key_name: Optional[str] = Field(default=None, description="Name for storing API key")
    api_key: Optional[str] = Field(default=None, description="API key value (if requires_auth)")
    capabilities: List[str] = Field(default_factory=lambda: ["reasoning"],
                                    description="Model capabilities used for feature routing")
    features: List[str] = Field(default_factory=lambda: ["streaming", "system_prompts"], 
                                 description="Supported features")
    feature_config: Dict[str, Any] = Field(default_factory=dict,
                                           description="Feature-specific model configuration")
    tool_rendering: Optional[str] = Field(default=None, description="Tool schema rendering profile")
    tool_call_format: Optional[str] = Field(default=None, description="Text tool-call format")
    server_type: Optional[str] = Field(
        default=None,
        description="Server behind an openai_compatible endpoint: 'openai_compatible' (default) or 'ollama', which sends the context window to Ollama's native chat API",
    )
    description: Optional[str] = Field(default=None, description="Model description")
    
    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate that base_url is a valid URL if provided."""
        if v is None:
            return v
        parsed = urlparse(v)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                f"Invalid URL format: '{v}'. Must include scheme (http/https) and host."
            )
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"URL scheme must be 'http' or 'https', got '{parsed.scheme}'"
            )
        return v

    @field_validator("server_type")
    @classmethod
    def validate_server_type(cls, v: Optional[str]) -> Optional[str]:
        return _validate_server_type(v)
    
    @model_validator(mode="after")
    def validate_handler_fields(self) -> "CustomModelCreate":
        """Validate that required fields are present based on handler type."""
        if self.server_type == SERVER_TYPE_OLLAMA and self.handler != ModelHandler.OPENAI_COMPATIBLE.value:
            raise ValueError("server_type 'ollama' requires the openai_compatible handler")
        if self.handler in API_HANDLERS:
            # API models require base_url and model_identifier
            if not self.base_url:
                raise ValueError(f"base_url is required for {self.handler} handler")
            if not self.model_identifier:
                raise ValueError(f"model_identifier is required for {self.handler} handler")
        elif self.handler == ModelHandler.LLAMA_CPP.value:
            # Local models require either model_path or download_url
            if not self.model_path and not self.download_url:
                raise ValueError("llama_cpp handler requires either model_path or download_url")
        return self


class CustomModelUpdate(BaseModel):
    """Request body for updating a custom model."""
    
    display_name: Optional[str] = None
    handler: Optional[str] = Field(default=None, description="Updated API handler type for an existing remote custom model")
    base_url: Optional[str] = None
    model_identifier: Optional[str] = None
    model_path: Optional[str] = None
    download_url: Optional[str] = None
    context_window: Optional[int] = Field(default=None, gt=0)
    max_output_tokens: Optional[int] = Field(default=None, gt=0)
    requires_auth: Optional[bool] = None
    api_key_name: Optional[str] = None
    api_key: Optional[str] = None
    capabilities: Optional[List[str]] = None
    features: Optional[List[str]] = None
    feature_config: Optional[Dict[str, Any]] = None
    tool_rendering: Optional[str] = None
    tool_call_format: Optional[str] = None
    server_type: Optional[str] = None
    description: Optional[str] = None

    @field_validator("server_type")
    @classmethod
    def validate_server_type(cls, v: Optional[str]) -> Optional[str]:
        return _validate_server_type(v)
    
    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate that base_url is a valid URL if provided."""
        if v is None:
            return v
        parsed = urlparse(v)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                f"Invalid URL format: '{v}'. Must include scheme (http/https) and host."
            )
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"URL scheme must be 'http' or 'https', got '{parsed.scheme}'"
            )
        return v


class CustomModelResponse(BaseModel):
    """Response for a single custom model."""
    
    model_id: str
    config: Dict[str, Any]


class CustomModelsListResponse(BaseModel):
    """Response for listing all custom models."""
    
    models: Dict[str, Dict[str, Any]]
    count: int


# =============================================================================
# CONNECTION TEST SCHEMAS
# =============================================================================


class ConnectionTestRequest(BaseModel):
    """Request body for testing connection to a custom model endpoint."""
    
    handler: str = Field(..., description="Handler type: 'openai_compatible' or 'anthropic_compatible'")
    base_url: str = Field(..., description="API endpoint URL")
    model_identifier: str = Field(..., description="Model name to test")
    api_key: Optional[str] = Field(default=None, description="API key if required")


class ConnectionTestResponse(BaseModel):
    """Response for connection test."""
    
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None


# =============================================================================
# HUGGINGFACE SCHEMAS
# =============================================================================


class HFFileInfo(BaseModel):
    """Information about a file in a HuggingFace repository."""
    
    name: str
    size_bytes: Optional[int] = None
    size_human: Optional[str] = None


class HFModelMetadata(BaseModel):
    """Model metadata extracted from HuggingFace config files."""
    
    context_window: Optional[int] = None
    model_type: Optional[str] = None
    architecture: Optional[str] = None
    model_name: Optional[str] = None


class HFProbeRequest(BaseModel):
    """Request body for probing a HuggingFace repository."""
    
    url: str = Field(..., description="HuggingFace URL or repo_id")


class HFProbeResponse(BaseModel):
    """Response for HuggingFace repository probe."""
    
    repo_id: str
    gguf_files: List[HFFileInfo]
    safetensor_files: List[HFFileInfo]
    model_metadata: Optional[HFModelMetadata] = None
    error: Optional[str] = None


class GGUFMetadataRequest(BaseModel):
    """Request body for fetching GGUF file metadata via partial download."""
    
    repo_id: str = Field(..., description="HuggingFace repo_id (e.g., 'microsoft/Phi-3-mini-4k-instruct-gguf')")
    filename: str = Field(..., description="GGUF filename to fetch metadata for")


# =============================================================================
# PATH VALIDATION SCHEMAS
# =============================================================================


class PathValidationRequest(BaseModel):
    """Request body for validating a local model file path."""
    
    path: str = Field(..., description="Path to the model file")


class PathValidationResponse(BaseModel):
    """Response for path validation."""
    
    valid: bool
    path: str
    error: Optional[str] = None
    file_size: Optional[int] = None
    file_size_human: Optional[str] = None
    file_type: Optional[str] = None


# =============================================================================
# DOWNLOAD SCHEMAS
# =============================================================================


class DownloadRequest(BaseModel):
    """Request body for initiating a model download."""
    
    filename: str = Field(..., description="Specific file to download from the repo")


class DownloadResponse(BaseModel):
    """Response for download initiation."""
    
    success: bool
    message: str
    model_path: Optional[str] = None
    error: Optional[str] = None
