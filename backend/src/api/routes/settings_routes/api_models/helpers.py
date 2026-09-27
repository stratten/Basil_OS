"""Shared helpers for API model settings routes."""

from typing import Any, Dict, List, Optional, Tuple

from ....core.logging.api_logger import api_logger
from ....core.models.preferences import Preferences


def _get_provider_from_registry(model_id: str) -> Optional[str]:
    """
    Get the provider name for a model from the registry.

    Returns:
        Provider name ("anthropic", "openai", "gemini") or None if not found.
    """
    try:
        from ....core.models.models_registry import get_model, PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GOOGLE

        cfg = get_model(model_id)
        if not cfg:
            return None

        # Map registry provider constants to our provider names
        registry_provider = cfg.get("provider")
        provider_reverse_map = {
            PROVIDER_ANTHROPIC: "anthropic",
            PROVIDER_OPENAI: "openai",
            PROVIDER_GOOGLE: "gemini",
        }
        return provider_reverse_map.get(registry_provider)
    except Exception:
        return None


def _get_provider_models_dict(preferences: "Preferences", provider: str) -> Optional[Dict[str, bool]]:
    """Get the reasoning models dict for a provider from preferences."""
    provider_map = {
        "anthropic": preferences.models.anthropic_models,
        "openai": preferences.models.openai_models,
        "gemini": preferences.models.gemini_models,
    }
    return provider_map.get(provider)


def _get_transcription_provider_models_dict(preferences: "Preferences", provider: str) -> Optional[Dict[str, bool]]:
    """Get the transcription API models dict for a provider from preferences."""
    provider_map = {
        "openai": preferences.models.openai_transcription_models,
    }
    return provider_map.get(provider)


def _is_transcription_provider_enabled(preferences: "Preferences", provider: str) -> bool:
    """Check if a transcription API provider is enabled in preferences."""
    if provider == "openai":
        return preferences.models.openai_transcription_enabled
    return False


def _set_transcription_provider_enabled(preferences: "Preferences", provider: str, enabled: bool) -> None:
    """Set the enabled state for a transcription API provider in preferences."""
    if provider == "openai":
        preferences.models.openai_transcription_enabled = enabled


def _is_provider_enabled(preferences: "Preferences", provider: str) -> bool:
    """Check if a provider is enabled in preferences."""
    if provider == "anthropic":
        return preferences.models.anthropic_enabled
    elif provider == "openai":
        return preferences.models.openai_enabled
    elif provider == "gemini":
        return preferences.models.gemini_enabled
    return False


def _set_provider_enabled(preferences: "Preferences", provider: str, enabled: bool) -> None:
    """Set the enabled state for a provider in preferences."""
    if provider == "anthropic":
        preferences.models.anthropic_enabled = enabled
    elif provider == "openai":
        preferences.models.openai_enabled = enabled
    elif provider == "gemini":
        preferences.models.gemini_enabled = enabled


def _find_fallback_model(preferences: "Preferences", exclude_model: str, prefer_provider: Optional[str] = None) -> Optional[str]:
    """
    Find an enabled model to use as fallback when a model is disabled.

    Args:
        preferences: Current preferences
        exclude_model: Model being disabled (to exclude from search)
        prefer_provider: Try this provider first, then others

    Returns:
        Model ID of an enabled model, or None if none found
    """
    # Provider search order - prefer same provider, then others
    provider_order = ["anthropic", "openai", "gemini"]
    if prefer_provider and prefer_provider in provider_order:
        provider_order.remove(prefer_provider)
        provider_order.insert(0, prefer_provider)

    for provider in provider_order:
        # Check if provider is enabled
        if provider == "anthropic" and not preferences.models.anthropic_enabled:
            continue
        elif provider == "openai" and not preferences.models.openai_enabled:
            continue
        elif provider == "gemini" and not preferences.models.gemini_enabled:
            continue

        models_dict = _get_provider_models_dict(preferences, provider)
        if models_dict:
            for model_id, enabled in models_dict.items():
                if model_id != exclude_model and enabled:
                    return model_id

    return None


def _get_local_default_for_capability(capability: str) -> str:
    """Return the stable local default for a model capability."""
    if capability == "vision":
        return "vikhyatk/moondream2"
    return "qwen/qwen3-8b-instruct-q4km"


def _resolve_fallback_default(
    preferences: "Preferences",
    excluded_model: str,
    capability: str,
    prefer_provider: Optional[str] = None,
) -> str:
    """Choose an enabled API fallback or a stable local default."""
    return (
        _find_fallback_model(preferences, excluded_model, prefer_provider=prefer_provider)
        or _get_local_default_for_capability(capability)
    )


def _get_models_from_registry_for_provider(provider: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Get ordered models for a provider from the unified registry.

    Returns:
        List of (model_id, model_info_dict) tuples, sorted by display_order.
        Empty list if registry has no models for this provider.
    """
    try:
        from ....core.models.models_registry import (
            get_display_ordered_models,
            ModelLocation,
            PROVIDER_ANTHROPIC,
            PROVIDER_OPENAI,
            PROVIDER_GOOGLE,
        )

        # Map our provider names to registry provider constants.
        provider_map = {
            "anthropic": PROVIDER_ANTHROPIC,
            "openai": PROVIDER_OPENAI,
            "gemini": PROVIDER_GOOGLE,
        }

        registry_provider = provider_map.get(provider)
        if not registry_provider:
            return []

        # Get models from registry filtered by provider and cloud location.
        models = get_display_ordered_models(
            location=ModelLocation.CLOUD,
            provider=registry_provider,
        )

        if not models:
            return []

        # Transform registry format to route format.
        result = []
        for model_id, cfg in models:
            model_info = {
                "display_name": cfg.get("display_name", model_id),
                "description": cfg.get("description", ""),
                "recommended": cfg.get("recommended", False),
            }
            if cfg.get("recommended_reason"):
                model_info["recommended_reason"] = cfg["recommended_reason"]

            # Check for extended thinking feature.
            features = cfg.get("features", [])
            if "extended_thinking" in [f.value if hasattr(f, "value") else f for f in features]:
                model_info["supports_extended_thinking"] = True

            result.append((model_id, model_info))

        api_logger.debug(f"📚 Got {len(result)} models from registry for provider '{provider}'")
        return result

    except ImportError as e:
        api_logger.debug(f"Registry not available: {e}")
        return []
    except Exception as e:
        api_logger.debug(f"Error getting models from registry for {provider}: {e}")
        return []


# Preference helpers live outside route modules so services and routes share the same persistence path.
def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()


def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)


def get_model_capabilities_from_implementation(model_type: str, model_id: str) -> List[str]:
    """Get capabilities from the unified model registry.

    Args:
        model_type: The model provider (e.g., "anthropic", "openai") - unused, kept for compatibility
        model_id: The specific model ID (e.g., "claude-sonnet-4-5-20250929")

    Returns:
        List of capability strings (e.g., ["reasoning", "vision"])
    """
    try:
        from ....core.models.models_registry import get_model

        cfg = get_model(model_id)
        if cfg and "capabilities" in cfg:
            return cfg["capabilities"]
    except Exception as e:
        api_logger.debug(f"Could not get capabilities from registry for {model_id}: {e}")

    # Fallback: all cloud reasoning models have at least reasoning
    return ["reasoning"]
