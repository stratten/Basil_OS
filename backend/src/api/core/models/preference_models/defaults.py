"""Registry-backed default helpers for preference models."""

from typing import Dict


def _get_anthropic_model_defaults() -> Dict[str, bool]:
    """Get Anthropic model defaults from the unified registry."""
    try:
        from ..models_registry import get_default_enabled_for_provider, PROVIDER_ANTHROPIC
        return get_default_enabled_for_provider(PROVIDER_ANTHROPIC)
    except Exception:
        return {}


def _get_openai_model_defaults() -> Dict[str, bool]:
    """Get OpenAI model defaults from the unified registry."""
    try:
        from ..models_registry import get_default_enabled_for_provider, PROVIDER_OPENAI
        return get_default_enabled_for_provider(PROVIDER_OPENAI)
    except Exception:
        return {}


def _get_gemini_model_defaults() -> Dict[str, bool]:
    """Get Gemini model defaults from the unified registry."""
    try:
        from ..models_registry import get_default_enabled_for_provider, PROVIDER_GOOGLE
        return get_default_enabled_for_provider(PROVIDER_GOOGLE)
    except Exception:
        return {}


def _get_openai_transcription_model_defaults() -> Dict[str, bool]:
    """Get OpenAI cloud transcription model defaults from the unified registry."""
    try:
        from ..models_registry import get_cloud_transcription_models
        return {
            model_id: cfg.get("default_enabled", False)
            for model_id, cfg in get_cloud_transcription_models().items()
            if cfg.get("provider") == "openai"
        }
    except Exception:
        return {}
