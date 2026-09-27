"""
Unified Models Registry Package.

This package provides a single source of truth for all model definitions,
with per-category registries and a unified accessor API.

Usage:
    from api.core.models.models_registry import (
        # Enums.
        ModelHandler,
        ModelLocation,
        ModelFeature,
        # Provider constants.
        PROVIDER_OPENAI,
        PROVIDER_ANTHROPIC,
        # Accessors.
        get_model,
        get_models_by_capability,
        get_display_ordered_models,
        # etc.
    )

Per-category registries (for direct access if needed):
    - cloud_reasoning_registry.CLOUD_REASONING_MODELS
    - cloud_transcription_registry.CLOUD_TRANSCRIPTION_MODELS
    - local_reasoning_registry.LOCAL_GGUF_MODELS, LOCAL_HF_MODELS
    - transcription_registry.TRANSCRIPTION_MODELS
"""

# Re-export public API from schema.py.
from .schema import (
    # Enums.
    ModelHandler,
    ModelLocation,
    ModelCategory,
    ModelFeature,
    # Schemas (TypedDicts).
    BaseModelConfig,
    CloudReasoningConfig,
    CloudTranscriptionConfig,
    LocalGGUFConfig,
    LocalHuggingFaceConfig,
    TranscriptionConfig,
    CustomModelConfig,
    # Provider constants.
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_QWEN,
    PROVIDER_MISTRAL,
    PROVIDER_META,
    PROVIDER_SOLAR,
    PROVIDER_OPENAI_WHISPER,
    PROVIDER_DISTIL_WHISPER,
    PROVIDER_NVIDIA_PARAKEET,
    PROVIDER_CUSTOM,
    # Accessor functions.
    get_model,
    is_in_registry,
    find_model_by_display_name,
    get_models_by_capability,
    get_models_by_feature,
    get_models_by_location,
    get_models_by_provider,
    get_models_by_handler,
    get_cloud_providers,
    get_default_enabled_for_provider,
    get_display_ordered_models,
    has_feature,
    get_feature_config,
    get_api_endpoint,
    requires_responses_api,
    get_reasoning_effort_default,
    get_validation_model_for_provider,
    get_visible_models,
    get_omitted_request_parameters,
    apply_request_parameter_omissions,
    # Local model download accessors.
    get_repo_info,
    get_on_disk_name,
    get_local_reasoning_models,
    get_transcription_models,
    get_cloud_transcription_models,
    get_parakeet_transcription_models,
    get_downloadable_models,
)

from .thinking_config import get_thinking_request_config

# Re-export custom model CRUD functions.
from .custom_models_registry import (
    get_custom_models,
    add_custom_model,
    update_custom_model,
    remove_custom_model,
)

# Also re-export ModelCapability from parent for convenience.
from ..model_types import ModelCapability

from typing import Optional as _Optional


def get_model_chunk_seconds(model_id: str) -> _Optional[float]:
    """Return the registry-configured app-level chunk window (seconds) for a
    transcription model, or ``None`` when the model declares no ``chunk_seconds``.

    Callers fall back to their backend's hardcoded default when this is ``None``,
    so behavior is preserved for models (e.g. faster-whisper) that omit it. Also
    used to derive the cadence for threshold-based incremental retranscription.
    """
    config = get_model(model_id)
    if not config:
        return None
    value = config.get("chunk_seconds")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None

__all__ = [
    # Enums.
    "ModelHandler",
    "ModelLocation",
    "ModelFeature",
    "ModelCapability",
    # Schemas.
    "BaseModelConfig",
    "CloudReasoningConfig",
    "CloudTranscriptionConfig",
    "LocalGGUFConfig",
    "LocalHuggingFaceConfig",
    "TranscriptionConfig",
    "CustomModelConfig",
    # Provider constants.
    "PROVIDER_OPENAI",
    "PROVIDER_ANTHROPIC",
    "PROVIDER_GOOGLE",
    "PROVIDER_QWEN",
    "PROVIDER_MISTRAL",
    "PROVIDER_META",
    "PROVIDER_SOLAR",
    "PROVIDER_OPENAI_WHISPER",
    "PROVIDER_DISTIL_WHISPER",
    "PROVIDER_NVIDIA_PARAKEET",
    "PROVIDER_CUSTOM",
    # Accessors.
    "get_model",
    "is_in_registry",
    "find_model_by_display_name",
    "get_models_by_capability",
    "get_models_by_feature",
    "get_models_by_location",
    "get_models_by_provider",
    "get_models_by_handler",
    "get_cloud_providers",
    "get_default_enabled_for_provider",
    "get_display_ordered_models",
    "has_feature",
    "get_feature_config",
    "get_api_endpoint",
    "requires_responses_api",
    "get_reasoning_effort_default",
    "get_thinking_request_config",
    "get_validation_model_for_provider",
    "get_visible_models",
    "get_omitted_request_parameters",
    "apply_request_parameter_omissions",
    # Local model download accessors.
    "get_repo_info",
    "get_on_disk_name",
    "get_local_reasoning_models",
    "get_transcription_models",
    "get_cloud_transcription_models",
    "get_parakeet_transcription_models",
    "get_downloadable_models",
    "get_model_chunk_seconds",
    # Custom model CRUD.
    "get_custom_models",
    "add_custom_model",
    "update_custom_model",
    "remove_custom_model",
]
