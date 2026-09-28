"""General API model settings routes."""

from fastapi import APIRouter, HTTPException

from config.api_keys import get_api_key

from ....core.logging.api_logger import api_logger

from .helpers import (
    _get_models_from_registry_for_provider,
    _get_provider_models_dict,
    _is_provider_enabled,
    _resolve_fallback_default,
    _set_provider_enabled,
    get_model_capabilities_from_implementation,
    load_preferences,
    save_preferences,
)
from .schemas import (
    APIModelToggleRequest,
    APIModelToggleResponse,
    APIModelUpdateRequest,
    APIModelUpdateResponse,
    APIModelsInfoResponse,
    APIProviderUpdateRequest,
    APIProviderUpdateResponse,
)


model_settings_router = APIRouter()
model_update_router = APIRouter()


@model_settings_router.get("/", response_model=APIModelsInfoResponse)
async def get_api_models() -> APIModelsInfoResponse:
    """Get information about all available API models."""
    try:
        # Get current preferences to determine which models are enabled
        preferences = load_preferences()

        # Import the API key manager to check if using user keys
        from config.api_keys import api_key_manager

        # Helper function to safely check for API keys
        def has_valid_api_key(provider: str) -> bool:
            try:
                key = get_api_key(provider)
                return bool(key)
            except Exception:
                return False

        model_info = {
            "anthropic": {
                "enabled": preferences.models.anthropic_enabled,
                "models": {},
                "model_order": [],
                "has_key": has_valid_api_key("anthropic"),
                "using_own_api_key": api_key_manager.is_using_user_key("anthropic")
            },
            "openai": {
                "enabled": preferences.models.openai_enabled,
                "models": {},
                "model_order": [],
                "has_key": has_valid_api_key("openai"),
                "using_own_api_key": api_key_manager.is_using_user_key("openai")
            },
            "gemini": {
                "enabled": preferences.models.gemini_enabled,
                "models": {},
                "model_order": [],
                "has_key": has_valid_api_key("google") or has_valid_api_key("gemini"),
                "using_own_api_key": api_key_manager.is_using_user_key("google") or api_key_manager.is_using_user_key("gemini")
            }
        }

        # Get Anthropic models from registry (ordered by display_order).
        anthropic_models_ordered = _get_models_from_registry_for_provider("anthropic")

        # Add Anthropic models in order
        for model_id, model_data in anthropic_models_ordered:
            model_info["anthropic"]["models"][model_id] = {
                **model_data,
                "capabilities": get_model_capabilities_from_implementation("anthropic", model_id),
                "enabled": preferences.models.anthropic_models.get(model_id, False)
            }
            model_info["anthropic"]["model_order"].append(model_id)

        # Get OpenAI models from registry (ordered by display_order).
        openai_models_ordered = _get_models_from_registry_for_provider("openai")

        # Add OpenAI models in order
        for model_id, model_data in openai_models_ordered:
            model_info["openai"]["models"][model_id] = {
                **model_data,
                "capabilities": get_model_capabilities_from_implementation("openai", model_id),
                "enabled": preferences.models.openai_models.get(model_id, False)
            }
            model_info["openai"]["model_order"].append(model_id)

        # Get Gemini models from registry (ordered by display_order).
        gemini_models_ordered = _get_models_from_registry_for_provider("gemini")

        # Add Gemini models in order
        for model_id, model_data in gemini_models_ordered:
            model_info["gemini"]["models"][model_id] = {
                **model_data,
                "capabilities": get_model_capabilities_from_implementation("gemini", model_id),
                "enabled": preferences.models.gemini_models.get(model_id, False)
            }
            model_info["gemini"]["model_order"].append(model_id)

        return APIModelsInfoResponse(
            status="success",
            api_models=model_info,
            settings={
                "use_api_models": preferences.models.use_api_models,
                "api_extended_thinking": preferences.models.api_extended_thinking,
                "current_models": {
                    "reasoning": preferences.models.reasoning_model,
                    "vision": preferences.models.vision_model,
                    "language": preferences.models.language_model
                }
            }
        )
    except Exception as e:
        api_logger.error(f"❌ Error getting API models: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@model_settings_router.put("/api_providers/{provider}", response_model=APIProviderUpdateResponse)
async def update_api_provider_settings(
    provider: str,
    settings: APIProviderUpdateRequest
) -> APIProviderUpdateResponse:
    """Update settings for an API provider."""
    try:
        api_logger.debug(f"🔧 Received API provider update for {provider}")
        api_logger.debug(f"🔧 Raw settings data: {settings.model_dump()}")

        # Validate provider
        if provider not in ["anthropic", "openai", "gemini"]:
            raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}. Must be 'anthropic', 'openai', or 'gemini'")

        # Load current preferences
        preferences = load_preferences()

        # Import the API key manager
        from config.api_keys import api_key_manager

        # Special handling for Gemini which can use either "google" or "gemini" key
        key_provider = provider
        if provider == "gemini":
            # Check if user has either google or gemini key
            has_google_key = api_key_manager.has_user_key("google")
            has_gemini_key = api_key_manager.has_user_key("gemini")

            # Use whichever key is available
            if has_google_key:
                key_provider = "google"
            elif has_gemini_key:
                key_provider = "gemini"

        # If we're enabling the provider and want to use our own API key, validate it exists
        if settings.enabled and settings.use_own_api_key:
            if not api_key_manager.has_user_key(key_provider):
                raise HTTPException(
                    status_code=400,
                    detail=f"You need to set your own API key for {provider} before enabling it with 'use_own_api_key=true'"
                )

        # Update the API key preference based on the setting
        if settings.enabled:
            if settings.use_own_api_key:
                try:
                    # Use user's own key
                    api_key_manager.use_user_key(key_provider)
                    api_logger.info(f"Using user's API key for {provider} (key provider: {key_provider})")
                except Exception as e:
                    api_logger.error(f"❌ Error setting user API key for {provider}: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to use your API key for {provider}: {str(e)}"
                    )
            else:
                # Use application's built-in key
                try:
                    api_key_manager.use_application_key(key_provider)
                    api_logger.info(f"Using application default API key for {provider} (key provider: {key_provider})")
                except Exception as e:
                    api_logger.error(f"❌ Error using application default key: {e}")
                    # Don't fail here - allow enabling provider even if no default key
                    api_logger.warning(f"No application default key available for {provider}, but allowing provider to be enabled")

        # Check if a valid API key is available (either user or application default)
        # but don't prevent enabling if no key - just log warnings
        has_valid_key = False
        if settings.enabled:
            try:
                key = get_api_key(key_provider)
                if key:
                    has_valid_key = True
                    api_logger.info(f"Valid API key confirmed for {provider} (key provider: {key_provider})")
            except Exception as e:
                api_logger.warning(f"No valid API key available for {provider}: {e}. Provider will be enabled but users will need to add a valid key before using models.")

        # Update provider-specific settings using helper
        _set_provider_enabled(preferences, provider, settings.enabled)

        # If disabling, and this is the only enabled provider, also disable API models master toggle
        if not settings.enabled:
            # Check if any other providers are enabled
            other_providers = [p for p in ["anthropic", "openai", "gemini"] if p != provider]
            other_providers_enabled = any(_is_provider_enabled(preferences, p) for p in other_providers)
            if not other_providers_enabled:
                preferences.models.use_api_models = False
                api_logger.info("Disabling API models master toggle since no providers are enabled")
        else:
            # If enabling, make sure master toggle is on
            if not preferences.models.use_api_models:
                preferences.models.use_api_models = True
                api_logger.info("Enabling API models master toggle")

        # Save updated preferences
        save_preferences(preferences)

        # Get the provider's model information using helpers
        provider_enabled = _is_provider_enabled(preferences, provider)
        provider_models = _get_provider_models_dict(preferences, provider) or {}

        provider_info = {
            "provider": provider,
            "enabled": provider_enabled,
            "models_enabled": sum(1 for enabled in provider_models.values() if enabled),
            "total_models": len(provider_models),
            "has_key": has_valid_key,
            "using_own_api_key": api_key_manager.is_using_user_key(provider) if provider != "gemini" else (api_key_manager.is_using_user_key("google") or api_key_manager.is_using_user_key("gemini"))
        }

        return APIProviderUpdateResponse(
            status="updated",
            provider=provider_info
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        api_logger.error(f"❌ Error updating API provider settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@model_settings_router.put("/toggle", response_model=APIModelToggleResponse)
async def toggle_api_models(settings: APIModelToggleRequest) -> APIModelToggleResponse:
    """Toggle the master switch for API models."""
    try:
        api_logger.debug(f"🔧 Toggling API models master switch: {settings.enabled}")

        # Load current preferences
        preferences = load_preferences()

        # Update the master toggle
        preferences.models.use_api_models = settings.enabled

        # If enabling API models but no providers are enabled, try to enable default providers
        # BUT don't fail if no keys are available - just log warnings
        if settings.enabled and not (preferences.models.anthropic_enabled or preferences.models.openai_enabled):
            # Try to enable Anthropic by default if we have a key
            try:
                if get_api_key("anthropic"):
                    preferences.models.anthropic_enabled = True
                    api_logger.info("Automatically enabling Anthropic provider")
            except Exception as e:
                api_logger.info(f"Anthropic API key not available: {e}")

            # Try to enable OpenAI by default if we have a key
            try:
                if get_api_key("openai"):
                    preferences.models.openai_enabled = True
                    api_logger.info("Automatically enabling OpenAI provider")
            except Exception as e:
                api_logger.info(f"OpenAI API key not available: {e}")

            # If still no providers enabled, log a warning but don't fail
            if not (preferences.models.anthropic_enabled or preferences.models.openai_enabled):
                api_logger.warning("API models enabled but no providers have valid API keys. Users will need to add their own API keys.")

        # Save updated preferences
        save_preferences(preferences)

        return APIModelToggleResponse(
            status="success",
            api_models_enabled=preferences.models.use_api_models,
            providers_enabled={
                "anthropic": preferences.models.anthropic_enabled,
                "openai": preferences.models.openai_enabled
            },
            current_models={
                "reasoning": preferences.models.reasoning_model,
                "vision": preferences.models.vision_model,
                "language": preferences.models.language_model
            }
        )
    except Exception as e:
        api_logger.error(f"❌ Error toggling API models: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@model_update_router.put("/{provider}/{model_id}", response_model=APIModelUpdateResponse)
async def update_api_model_settings(
    provider: str,
    model_id: str,
    settings: APIModelUpdateRequest
) -> APIModelUpdateResponse:
    """Update settings for a specific API model."""
    try:
        api_logger.debug(f"🔧 Received API model update for {provider}/{model_id}")
        api_logger.debug(f"🔧 Raw settings data: {settings.model_dump()}")

        # Validate provider
        if provider not in ["anthropic", "openai", "gemini"]:
            raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}. Must be 'anthropic', 'openai', or 'gemini'")

        # Load current preferences
        preferences = load_preferences()

        # Get the provider-specific model dict using unified helper
        from ....core.models.models_registry import is_in_registry

        models_dict = _get_provider_models_dict(preferences, provider)
        if models_dict is None:
            raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")

        # If model not in preferences but IS in registry, add it
        if model_id not in models_dict:
            if is_in_registry(model_id):
                api_logger.info(f"Adding new registry model {model_id} to {provider} preferences")
                models_dict[model_id] = False  # Will be updated below
            else:
                raise HTTPException(status_code=400, detail=f"Unknown {provider} model: {model_id}")

            # Update enabled state
        models_dict[model_id] = settings.enabled

        # If disabling a model that was the default, find a replacement
        if not settings.enabled:
            # Handle reasoning model fallback
            if preferences.models.reasoning_model == model_id:
                new_default = _resolve_fallback_default(
                    preferences,
                    model_id,
                    capability="reasoning",
                    prefer_provider=provider,
                )
                preferences.models.reasoning_model = new_default
                api_logger.info(f"Changed reasoning model to {new_default} since {model_id} was disabled")

            # Handle vision model fallback
            if preferences.models.vision_model == model_id:
                new_default = _resolve_fallback_default(
                    preferences,
                    model_id,
                    capability="vision",
                    prefer_provider=provider,
                )
                preferences.models.vision_model = new_default
                api_logger.info(f"Changed vision model to {new_default} since {model_id} was disabled")

        # Set as default for capabilities if requested
        if settings.enabled and settings.set_as_default_for:
            for capability in settings.set_as_default_for:
                if capability.lower() == "reasoning":
                    preferences.models.reasoning_model = model_id
                    api_logger.info(f"Set {provider}/{model_id} as the reasoning model")

                elif capability.lower() == "vision":
                    # OpenAI and Gemini models support vision
                    if provider in ["openai", "gemini"]:
                        preferences.models.vision_model = model_id
                        api_logger.info(f"Set {provider}/{model_id} as the vision model")
                    else:
                        api_logger.warning(f"Provider {provider} does not support vision capability for {model_id}")

        # Save updated preferences
        save_preferences(preferences)

        # Get model capabilities
        model_capabilities = get_model_capabilities_from_implementation(provider, model_id)

        # Return the updated model info
        model_enabled = models_dict.get(model_id, False)

        model_info = {
            "provider": provider,
            "model_id": model_id,
            "enabled": model_enabled,
            "capabilities": model_capabilities,
            "is_current_model": {
                "reasoning": preferences.models.reasoning_model == model_id,
                "vision": preferences.models.vision_model == model_id if "vision" in model_capabilities else False
            }
        }

        return APIModelUpdateResponse(
            status="updated",
            model=model_info
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating API model settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
