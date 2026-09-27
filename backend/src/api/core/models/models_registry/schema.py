"""
Unified Models Registry - Schema, Enums, and Accessors.

This module provides the shared type definitions and a unified API for accessing
models across all per-category registries (cloud reasoning, local reasoning, transcription).

ADDING A NEW MODEL:
1. Add an entry to the appropriate per-category registry file:
   - cloud_reasoning_registry.py for OpenAI, Anthropic, Gemini models.
   - local_reasoning_registry.py for GGUF or HuggingFace local models.
   - transcription_registry.py for Whisper/Distil-Whisper models.
2. Use the correct schema (CloudReasoningConfig, LocalGGUFConfig, etc.).
3. Set display_order and update *_PROVIDER_DISPLAY_ORDER if needed.
4. That's it. No other files should need changes for basic support.

ADDING A NEW FEATURE:
1. Add the feature to ModelFeature enum below.
2. Models that support it add it to their "features" array.
3. If the feature needs configuration, add it under feature_config[feature].
"""

from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict

from ..model_types import ModelCapability


# =============================================================================
# HANDLER TYPES - Explicit, never inferred.
# =============================================================================


class ModelHandler(str, Enum):
    """Supported model handlers. Each maps to a registered model class."""

    # Local handlers.
    LLAMA_CPP = "llama_cpp"  # GGUF models via llama-cpp-python.
    LLAMA_CPP_VISION = "llama_cpp_vision"  # GGUF VLM (e.g. Qwen2.5-VL + mmproj).
    HUGGINGFACE = "huggingface"  # HuggingFace transformers.
    WHISPER = "whisper"  # Whisper transcription (HF pipeline).
    PARAKEET = "parakeet"  # NVIDIA Parakeet ASR via ONNX Runtime (no NeMo).

    # Cloud API handlers.
    OPENAI_API = "openai_api"  # Direct OpenAI API.
    ANTHROPIC_API = "anthropic_api"  # Direct Anthropic API.
    GEMINI_API = "gemini_api"  # Direct Google Gemini API.
    OPENROUTER = "openrouter"  # OpenRouter proxy (any provider).
    OPENAI_WHISPER_API = "openai_whisper_api"  # OpenAI Whisper transcription API.

    # User-configurable handlers for custom models.
    OPENAI_COMPATIBLE = "openai_compatible"  # Any OpenAI-compatible endpoint.
    ANTHROPIC_COMPATIBLE = "anthropic_compatible"  # Any Anthropic-compatible endpoint.


class ModelLocation(str, Enum):
    """Where the model runs."""

    LOCAL = "local"
    CLOUD = "cloud"


class ModelCategory(str, Enum):
    """
    Distinguishes predefined models from user-defined custom models.
    Used in routing and request handling to ensure proper API dispatch.
    """

    STANDARD = "standard"  # Predefined models in the registry
    CUSTOM = "custom"      # User-defined models via custom_models_registry


# =============================================================================
# FEATURES - API/Runtime features (extensible).
# =============================================================================


class ModelFeature(str, Enum):
    """
    Extensible features that models may support.
    Add new features here as providers introduce them.
    """

    # API features (primarily cloud models).
    WEB_SEARCH = "web_search"  # Can use web search tools.
    EXTENDED_THINKING = "extended_thinking"  # Exposes thinking/reasoning process.
    FUNCTION_CALLING = "function_calling"  # Tool/function use support.
    JSON_MODE = "json_mode"  # Structured JSON output mode.
    STREAMING = "streaming"  # Streaming response support.
    SYSTEM_PROMPTS = "system_prompts"  # Supports system message role.

    # Runtime features (primarily local models).
    GPU_ACCELERATION = "gpu_acceleration"  # Can use GPU (CUDA/MPS).
    QUANTIZATION = "quantization"  # Is a quantised model (GGUF).

    # Internal use features.
    API_KEY_VALIDATION = "api_key_validation"  # Designated for API key validation (cheap, fast).


# =============================================================================
# PROVIDER CONSTANTS.
# =============================================================================

# Cloud providers.
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GOOGLE = "google"

# Local model sources.
PROVIDER_QWEN = "qwen"
PROVIDER_MISTRAL = "mistral"
PROVIDER_META = "meta"
PROVIDER_SOLAR = "solar"
PROVIDER_OPENAI_WHISPER = "openai_whisper"
PROVIDER_DISTIL_WHISPER = "distil_whisper"
PROVIDER_NVIDIA_PARAKEET = "nvidia_parakeet"

# User-defined.
PROVIDER_CUSTOM = "custom"


# =============================================================================
# SCHEMA DEFINITIONS - Separate schemas per model type.
# =============================================================================


class BaseModelConfig(TypedDict, total=False):
    """Common fields across all model types."""

    # Required.
    handler: str  # ModelHandler value.
    location: str  # ModelLocation value.
    provider: str  # Provider constant.
    display_name: str  # Human-readable name.
    capabilities: List[str]  # List of ModelCapability values.
    category: str  # ModelCategory value: "standard" or "custom".

    # Optional - features.
    features: List[str]  # List of ModelFeature values.
    feature_config: Dict[str, Any]  # Config for features that need parameters.

    # Optional - UI/display.
    description: str
    display_order: int  # Sort order within provider group (default: 999).
    default_enabled: bool  # Default state in preferences (default: False).
    recommended: bool  # Show as recommended (default: False).
    recommended_reason: str  # Why recommended.
    visible: bool  # Whether model appears in UI (default: True). Set False for internal-only models.


class CloudReasoningConfig(BaseModelConfig):
    """Schema for cloud-based reasoning models (OpenAI, Anthropic, Gemini)."""

    # Required for cloud reasoning.
    context_window: int  # Max input tokens.
    max_output_tokens: int  # Max output tokens.

    # Optional - routing.
    api_endpoint: str  # E.g. "chat_completions" or "responses".
    openrouter_id: str  # For OpenRouter proxy routing.

    # Optional - OpenRouter-specific routing hints.
    supports_openrouter_proxy: bool  # Model can be proxied via OpenRouter (default: False).
    openrouter_provider: str  # Explicit provider name for OpenRouter, if different.


class LocalGGUFConfig(BaseModelConfig):
    """Schema for local GGUF models (llama.cpp)."""

    # Required for local GGUF.
    context_window: int
    max_output_tokens: int
    download_url: str  # Direct download URL.
    on_disk_name: str  # Filename or folder on disk.
    size: str  # Human-readable size (e.g. "5.03GB").

    # Optional.
    sha256: Optional[str]  # Integrity verification.
    recommended_ram: str  # E.g. "16GB".
    speed_rating: int  # 1-10 scale.
    accuracy_rating: int  # 1-10 scale.
    artifact_root: str
    primary_artifact: str
    artifact_files: List[Dict[str, Any]]
    local_generation: Dict[str, Any]


class LocalHuggingFaceConfig(BaseModelConfig):
    """Schema for local HuggingFace transformers models."""

    # Required for local HF.
    context_window: int
    max_output_tokens: int
    repo_url: str  # HuggingFace repo URL.
    revision: str  # Git revision (default: "main").
    on_disk_name: str  # Folder name on disk.
    size: str  # Human-readable size.

    # Optional.
    recommended_ram: str
    speed_rating: int
    accuracy_rating: int
    local_generation: Dict[str, Any]


class TranscriptionConfig(BaseModelConfig):
    """Schema for transcription models (Whisper, Parakeet)."""

    # Required for transcription.
    repo_url: str  # HuggingFace repo URL.
    revision: str  # Git revision.
    on_disk_name: str  # Folder name on disk.
    size: str  # Human-readable size.

    # Optional.
    recommended_ram: str
    speed_rating: int  # Relative speed (1-10).
    accuracy_rating: int  # Relative quality (1-10).
    # Optional weight precision selector. Currently only consumed by the
    # Parakeet handler, where a single HuggingFace repo
    # (``istupakov/parakeet-tdt-0.6b-v2-onnx``) ships both an ``int8``
    # quantized variant (~640 MB on disk) and an ``fp32`` full-precision
    # variant (~2.4 GB on disk). Two distinct registry entries point at
    # the same ``repo_url`` and use this field to drive (a) the
    # downloader's per-file allow-list (so we never silently pull the
    # wrong variant or both at once) and (b) the
    # :class:`ParakeetModelManager` filename selection at session-load
    # time. Whisper / Distil-Whisper entries omit this field; the
    # downloader and HuggingFace pipeline ignore it for those handlers.
    precision: str  # One of: "int8", "fp16", "fp32". Optional (TypedDict total=False).
    # Optional app-level chunk window (seconds) used when a backend splits long
    # audio into windows before transcription (e.g. Parakeet silence-aware
    # chunking, local/cloud Whisper windowing). When present this overrides the
    # backend's hardcoded default; when absent the backend default is retained
    # (behavior-preserving). Also used to derive the cadence for threshold-based
    # incremental retranscription. Omit for models that do no app-level chunking.
    chunk_seconds: float
    # Note: No context_window or max_output_tokens; not applicable for audio models.


class CloudTranscriptionConfig(BaseModelConfig):
    """Schema for cloud-based transcription models (OpenAI Whisper API)."""

    # Required for cloud transcription.
    api_model_name: str  # Model name sent to the OpenAI SDK (e.g. "whisper-1").

    # Optional - routing.
    openrouter_id: str  # For OpenRouter proxy routing.

    # Optional - OpenRouter-specific routing hints.
    supports_openrouter_proxy: bool  # Model can be proxied via OpenRouter (default: False).
    openrouter_provider: str  # Explicit provider name for OpenRouter, if different.

    # Optional app-level chunk window (seconds) for long-audio windowing, in the
    # same sense as TranscriptionConfig.chunk_seconds. Used to derive the cadence
    # for threshold-based incremental retranscription. Omit when no chunking.
    chunk_seconds: float


class CustomModelConfig(BaseModelConfig):
    """Schema for user-defined custom models (OpenAI-compatible or Anthropic-compatible)."""

    # Required for custom models.
    context_window: int  # Max input tokens.
    max_output_tokens: int  # Max output tokens.
    base_url: str  # API endpoint (e.g., "http://localhost:11434/v1").
    model_identifier: str  # Model name sent in API calls (e.g., "llama3.2").

    # Optional - authentication.
    api_key_name: Optional[str]  # Reference to stored key name, or None for no auth.
    requires_auth: bool  # Whether API key is required (default: False for local models).


# =============================================================================
# INTERNAL HELPERS - Aggregate per-category registries.
# =============================================================================


def _iter_all_models() -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Iterate over all models across all per-category registries.
    
    Automatically adds the 'category' field to each model config:
    - 'standard' for predefined models in the built-in registries
    - 'custom' for user-defined models
    """
    # Import inside function to avoid circular imports.
    from .cloud_reasoning_registry import CLOUD_REASONING_MODELS
    from .cloud_transcription_registry import CLOUD_TRANSCRIPTION_MODELS
    from .local_reasoning_registry import LOCAL_GGUF_MODELS, LOCAL_HF_MODELS
    from .local_vision_registry import LOCAL_VISION_MODELS
    from .transcription_registry import TRANSCRIPTION_MODELS
    from .custom_models_registry import get_custom_models

    # Standard (predefined) models.
    for registry in (
        CLOUD_REASONING_MODELS,
        CLOUD_TRANSCRIPTION_MODELS,
        LOCAL_GGUF_MODELS,
        LOCAL_HF_MODELS,
        LOCAL_VISION_MODELS,
        TRANSCRIPTION_MODELS,
    ):
        for model_id, cfg in registry.items():
            # Add category if not already set.
            enriched_cfg = {**cfg, "category": cfg.get("category", ModelCategory.STANDARD.value)}
            yield model_id, enriched_cfg

    # User-defined custom models.
    for model_id, cfg in get_custom_models().items():
        enriched_cfg = {**cfg, "category": cfg.get("category", ModelCategory.CUSTOM.value)}
        yield model_id, enriched_cfg


def _get_provider_order(model_id: str, cfg: Dict[str, Any]) -> int:
    """Get the provider display order for a model based on its category."""
    # Import inside function to avoid circular imports.
    from .cloud_reasoning_registry import CLOUD_PROVIDER_DISPLAY_ORDER, CLOUD_REASONING_MODELS
    from .cloud_transcription_registry import CLOUD_TRANSCRIPTION_MODELS, CLOUD_TRANSCRIPTION_PROVIDER_DISPLAY_ORDER
    from .local_reasoning_registry import (
        LOCAL_GGUF_MODELS,
        LOCAL_HF_MODELS,
        LOCAL_REASONING_PROVIDER_DISPLAY_ORDER,
    )
    from .local_vision_registry import LOCAL_VISION_MODELS
    from .transcription_registry import TRANSCRIPTION_MODELS, TRANSCRIPTION_PROVIDER_DISPLAY_ORDER
    from .custom_models_registry import get_custom_models

    provider = cfg.get("provider", "")

    # Determine which category this model belongs to.
    if model_id in CLOUD_REASONING_MODELS:
        return CLOUD_PROVIDER_DISPLAY_ORDER.get(provider, 999)
    elif model_id in CLOUD_TRANSCRIPTION_MODELS:
        return CLOUD_TRANSCRIPTION_PROVIDER_DISPLAY_ORDER.get(provider, 999)
    elif model_id in LOCAL_GGUF_MODELS or model_id in LOCAL_HF_MODELS or model_id in LOCAL_VISION_MODELS:
        return LOCAL_REASONING_PROVIDER_DISPLAY_ORDER.get(provider, 999)
    elif model_id in TRANSCRIPTION_MODELS:
        return TRANSCRIPTION_PROVIDER_DISPLAY_ORDER.get(provider, 999)
    elif model_id in get_custom_models():
        # Custom models appear after built-in models (order 1000+).
        return 1000

    return 999


# =============================================================================
# PUBLIC ACCESSOR FUNCTIONS.
# =============================================================================


def get_model(model_id: str) -> Optional[Dict[str, Any]]:
    """Get a model by ID. Returns None if it is not in any registry."""
    for mid, cfg in _iter_all_models():
        if mid == model_id:
            return cfg
    return None


def is_in_registry(model_id: str) -> bool:
    """Check if a model exists in any registry."""
    for mid, _ in _iter_all_models():
        if mid == model_id:
            return True
    return False


def find_model_by_display_name(display_name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Find a model by its human-readable display_name instead of its canonical id.

    Used to self-heal callers/preferences that were persisted with a model's
    display_name (e.g. a client-side bug that stored the wrong field when
    populating a model picker) instead of the canonical registry id.
    Returns (model_id, cfg) for the first match, or None if none found.
    """
    for mid, cfg in _iter_all_models():
        if cfg.get("display_name") == display_name:
            return mid, cfg
    return None


def get_models_by_capability(capability: ModelCapability) -> Dict[str, Dict[str, Any]]:
    """Get all models with a specific capability."""
    cap_str = capability.value if isinstance(capability, ModelCapability) else capability
    return {
        model_id: cfg
        for model_id, cfg in _iter_all_models()
        if cap_str in [c.value if isinstance(c, ModelCapability) else c for c in cfg.get("capabilities", [])]
    }


def get_models_by_feature(feature: ModelFeature) -> Dict[str, Dict[str, Any]]:
    """Get all models with a specific feature."""
    feat_str = feature.value if isinstance(feature, ModelFeature) else feature
    return {
        model_id: cfg
        for model_id, cfg in _iter_all_models()
        if feat_str in [f.value if isinstance(f, ModelFeature) else f for f in cfg.get("features", [])]
    }


def get_models_by_location(location: ModelLocation) -> Dict[str, Dict[str, Any]]:
    """Get all local or all cloud models."""
    loc_str = location.value if isinstance(location, ModelLocation) else location
    return {
        model_id: cfg
        for model_id, cfg in _iter_all_models()
        if cfg.get("location") == loc_str or cfg.get("location") == location
    }


def get_models_by_provider(provider: str) -> Dict[str, Dict[str, Any]]:
    """Get all models from a specific provider."""
    return {model_id: cfg for model_id, cfg in _iter_all_models() if cfg.get("provider") == provider}


def get_models_by_handler(handler: ModelHandler) -> Dict[str, Dict[str, Any]]:
    """Get all models using a specific handler."""
    handler_str = handler.value if isinstance(handler, ModelHandler) else handler
    return {
        model_id: cfg
        for model_id, cfg in _iter_all_models()
        if cfg.get("handler") == handler_str or cfg.get("handler") == handler
    }


def get_cloud_providers() -> List[str]:
    """Get list of cloud providers with at least one registered model."""
    providers: set[str] = set()
    for _, cfg in _iter_all_models():
        location = cfg.get("location")
        provider = cfg.get("provider")
        if provider and (location == ModelLocation.CLOUD or location == "cloud"):
            providers.add(provider)
    return sorted(providers)


def get_default_enabled_for_provider(provider: str) -> Dict[str, bool]:
    """Get {model_id: default_enabled} for all models from a provider."""
    return {
        model_id: cfg.get("default_enabled", False)
        for model_id, cfg in _iter_all_models()
        if cfg.get("provider") == provider
    }


def get_omitted_request_parameters(model_id: str) -> List[str]:
    """Return outbound request parameter names the registry says to omit."""
    cfg = get_model(model_id)
    if not cfg:
        return []

    feature_config = cfg.get("feature_config", {})
    request_parameters = feature_config.get("request_parameters", {})
    omitted = request_parameters.get("omit", [])

    # Backwards-compatible while older in-progress model entries migrate to
    # feature_config.request_parameters.omit.
    if not omitted:
        omitted = feature_config.get("deprecated_parameters", [])

    result: List[str] = []
    seen: set[str] = set()
    for parameter in omitted:
        if not isinstance(parameter, str):
            continue
        normalized = parameter.strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def apply_request_parameter_omissions(
    payload: Dict[str, Any],
    omitted_parameters: Iterable[str],
) -> Dict[str, Any]:
    """Return a payload copy without registry-omitted request parameters."""
    omitted = {parameter for parameter in omitted_parameters if isinstance(parameter, str)}
    return {key: value for key, value in payload.items() if key not in omitted}


def get_display_ordered_models(
    location: Optional[ModelLocation] = None,
    provider: Optional[str] = None,
    capability: Optional[ModelCapability] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Get (model_id, config) tuples sorted by provider order, then model display_order.

    Args:
        location: Filter by ModelLocation (LOCAL or CLOUD).
        provider: Filter by provider constant.
        capability: Filter by ModelCapability.

    Returns:
        List of (model_id, config) tuples sorted by:
        1. Provider display order (from per-category *_PROVIDER_DISPLAY_ORDER).
        2. Model display_order (default 999).
        3. Model ID as tiebreaker.
    """
    items = list(_iter_all_models())

    # Apply filters.
    if location:
        loc_str = location.value if isinstance(location, ModelLocation) else location
        items = [(m, c) for m, c in items if c.get("location") == loc_str or c.get("location") == location]

    if provider:
        items = [(m, c) for m, c in items if c.get("provider") == provider]

    if capability:
        cap_str = capability.value if isinstance(capability, ModelCapability) else capability
        items = [
            (m, c)
            for m, c in items
            if cap_str in [x.value if hasattr(x, "value") else x for x in c.get("capabilities", [])]
        ]

    # Sort by provider order, then model display_order, then model ID.
    return sorted(items, key=lambda x: (_get_provider_order(x[0], x[1]), x[1].get("display_order", 999), x[0]))


def has_feature(model_id: str, feature: ModelFeature) -> bool:
    """Check if a model has a specific feature."""
    cfg = get_model(model_id)
    if not cfg:
        return False
    feat_str = feature.value if isinstance(feature, ModelFeature) else feature
    return feat_str in [f.value if hasattr(f, "value") else f for f in cfg.get("features", [])]


def get_feature_config(model_id: str, feature: ModelFeature) -> Dict[str, Any]:
    """Get configuration for a specific feature, or empty dict if none."""
    cfg = get_model(model_id)
    if not cfg:
        return {}
    feat_str = feature.value if isinstance(feature, ModelFeature) else feature
    return cfg.get("feature_config", {}).get(feat_str, {})


def get_api_endpoint(model_id: str) -> Optional[str]:
    """Return the registry-declared API endpoint for a model, or None.

    Cloud reasoning entries may declare ``api_endpoint`` (e.g. "responses" or
    "chat_completions") to make endpoint selection explicit rather than inferred
    from feature flags. Returns None when the model is unknown or omits the field.
    """
    cfg = get_model(model_id)
    if not cfg:
        return None
    endpoint = cfg.get("api_endpoint")
    return endpoint if isinstance(endpoint, str) and endpoint else None


def requires_responses_api(model_id: str) -> bool:
    """True when a model must be served via the OpenAI Responses API.

    Single source of truth for endpoint selection across the direct model path
    and the LangChain agent path. A model requires the Responses API when it
    either explicitly declares ``api_endpoint == "responses"`` or exposes the
    ``reasoning_effort`` feature (kept as a fallback for entries that predate the
    explicit field).
    """
    if get_api_endpoint(model_id) == "responses":
        return True

    cfg = get_model(model_id)
    if not cfg:
        return False
    features = cfg.get("features", [])
    feature_values = [
        feature if isinstance(feature, str) else getattr(feature, "value", "")
        for feature in features
    ]
    return "reasoning_effort" in feature_values


def get_reasoning_effort_default(model_id: str) -> Optional[str]:
    """Return the registry-configured default reasoning effort for a model.

    Reads ``feature_config.reasoning_effort.default``. Returns None when the
    model is unknown, does not expose the ``reasoning_effort`` feature, or omits
    a default value.
    """
    cfg = get_model(model_id)
    if not cfg:
        return None
    reasoning_config = cfg.get("feature_config", {}).get("reasoning_effort", {})
    effort = reasoning_config.get("default")
    return effort if isinstance(effort, str) and effort else None


def get_validation_model_for_provider(provider: str) -> Optional[str]:
    """Get the model ID designated for API key validation for a provider.
    
    Returns the first model found with API_KEY_VALIDATION feature for the provider,
    or None if no validation model is configured.
    """
    for model_id, cfg in _iter_all_models():
        if cfg.get("provider") != provider:
            continue
        features = cfg.get("features", [])
        if ModelFeature.API_KEY_VALIDATION.value in [
            f.value if hasattr(f, "value") else f for f in features
        ]:
            return model_id
    return None


def get_visible_models() -> Dict[str, Dict[str, Any]]:
    """Get all models that should be visible in the UI.
    
    Models with visible=False are excluded. Default is visible=True.
    """
    return {
        model_id: cfg
        for model_id, cfg in _iter_all_models()
        if cfg.get("visible", True)
    }


# =============================================================================
# LOCAL MODEL DOWNLOAD ACCESSORS.
# =============================================================================


def get_repo_info(model_id: str) -> Optional[Tuple[str, str]]:
    """Get (repo_url, revision) for a HuggingFace model.
    
    Returns a tuple of (repo_url, revision) if the model has HuggingFace repo info,
    None otherwise. The revision defaults to "main" if not specified.
    """
    cfg = get_model(model_id)
    if not cfg:
        return None
    repo_url = cfg.get("repo_url")
    if not repo_url:
        return None
    revision = cfg.get("revision", "main")
    return (repo_url, revision)


def get_on_disk_name(model_id: str) -> Optional[str]:
    """Get the on-disk filename/folder for a model.
    
    Returns the on_disk_name field if present, None otherwise.
    This is the expected filename (for GGUF) or folder name (for HF repos) on disk.
    """
    cfg = get_model(model_id)
    if not cfg:
        return None
    return cfg.get("on_disk_name")


def get_local_reasoning_models() -> Dict[str, Dict[str, Any]]:
    """Get all local reasoning models (GGUF + HuggingFace).
    
    Returns a dict of {model_id: config} for all local models with the REASONING capability.
    """
    from .local_reasoning_registry import LOCAL_GGUF_MODELS, LOCAL_HF_MODELS
    
    result: Dict[str, Dict[str, Any]] = {}
    result.update(LOCAL_GGUF_MODELS)
    result.update(LOCAL_HF_MODELS)
    return result


def get_transcription_models() -> Dict[str, Dict[str, Any]]:
    """Get all local transcription models.
    
    Returns a dict of {model_id: config} for all local transcription models (Whisper variants).
    """
    from .transcription_registry import TRANSCRIPTION_MODELS
    
    return dict(TRANSCRIPTION_MODELS)


def get_cloud_transcription_models() -> Dict[str, Dict[str, Any]]:
    """Get all cloud transcription models (API-based).
    
    Returns a dict of {model_id: config} for all cloud transcription models
    (OpenAI Whisper API, etc.).
    """
    from .cloud_transcription_registry import CLOUD_TRANSCRIPTION_MODELS
    
    return dict(CLOUD_TRANSCRIPTION_MODELS)


def get_parakeet_transcription_models() -> Dict[str, Dict[str, Any]]:
    """Get all local Parakeet transcription models.

    Returns a dict of {model_id: config} for transcription models whose
    handler is `ModelHandler.PARAKEET` (NVIDIA Parakeet variants served via
    ONNX Runtime). Used by the dispatch layer in `dependencies.py` to route
    to `ParakeetTranscriptionService` instead of the default HuggingFace
    Whisper service.
    """
    from .transcription_registry import TRANSCRIPTION_MODELS

    return {
        model_id: cfg
        for model_id, cfg in TRANSCRIPTION_MODELS.items()
        if cfg.get("handler") == ModelHandler.PARAKEET.value
    }


def get_downloadable_models() -> Dict[str, Dict[str, Any]]:
    """Get all models that can be downloaded (local reasoning, vision, and transcription).
    
    Returns a dict of {model_id: config} for all models that have download
    information (download_url or repo_url).
    """
    from .local_vision_registry import LOCAL_VISION_MODELS

    result: Dict[str, Dict[str, Any]] = {}
    result.update(get_local_reasoning_models())
    result.update(LOCAL_VISION_MODELS)
    result.update(get_transcription_models())
    return result
