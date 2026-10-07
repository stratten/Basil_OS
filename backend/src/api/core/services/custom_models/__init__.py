"""
Custom Models Service Package

Provides services for managing user-defined custom models including:
- External service integration (connection testing, HuggingFace probing)
- Model downloads with progress tracking
- GGUF metadata extraction
"""

from .schemas import (
    CustomModelCreate,
    CustomModelUpdate,
    CustomModelResponse,
    CustomModelsListResponse,
    ConnectionTestRequest,
    ConnectionTestResponse,
    HFFileInfo,
    HFModelMetadata,
    HFProbeRequest,
    HFProbeResponse,
    GGUFMetadataRequest,
    PathValidationRequest,
    PathValidationResponse,
    DownloadRequest,
    DownloadResponse,
    SERVER_TYPE_OLLAMA,
    SERVER_TYPE_OPENAI_COMPATIBLE,
    SERVER_TYPES,
)

from .huggingface_service import (
    HuggingFaceService,
    huggingface_service,
    format_size,
    normalize_hf_url,
)

from .api_connection import (
    ConnectionTester,
    connection_tester,
    validate_local_path,
)

from .download_service import (
    CustomModelDownloadService,
    download_service,
    get_download_progress,
    extract_gguf_metadata,
)

__all__ = [
    # Schemas
    "CustomModelCreate",
    "CustomModelUpdate", 
    "CustomModelResponse",
    "CustomModelsListResponse",
    "ConnectionTestRequest",
    "ConnectionTestResponse",
    "HFFileInfo",
    "HFModelMetadata",
    "HFProbeRequest",
    "HFProbeResponse",
    "GGUFMetadataRequest",
    "PathValidationRequest",
    "PathValidationResponse",
    "DownloadRequest",
    "DownloadResponse",
    "SERVER_TYPE_OLLAMA",
    "SERVER_TYPE_OPENAI_COMPATIBLE",
    "SERVER_TYPES",
    # Services
    "ConnectionTester",
    "HuggingFaceService",
    "connection_tester",
    "huggingface_service",
    "validate_local_path",
    "format_size",
    "normalize_hf_url",
    "CustomModelDownloadService",
    "download_service",
    "get_download_progress",
    "extract_gguf_metadata",
]
