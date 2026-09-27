"""Transcription API model settings routes."""

from fastapi import APIRouter, HTTPException

from config.api_keys import get_api_key

from ....core.logging.api_logger import api_logger

from .helpers import (
    _get_transcription_provider_models_dict,
    _is_transcription_provider_enabled,
    _set_transcription_provider_enabled,
    load_preferences,
    save_preferences,
)
from .schemas import (
    TranscriptionAPIModelUpdateRequest,
    TranscriptionAPIModelUpdateResponse,
    TranscriptionAPIModelsResponse,
    TranscriptionAPIProviderUpdateRequest,
    TranscriptionAPIProviderUpdateResponse,
    TranscriptionAPIToggleRequest,
    TranscriptionAPIToggleResponse,
)


transcription_router = APIRouter()


@transcription_router.get("/transcription", response_model=TranscriptionAPIModelsResponse)
async def get_api_transcription_models() -> TranscriptionAPIModelsResponse:
    """Get all enabled API models with the TRANSCRIPTION capability."""
    try:
        preferences = load_preferences()

        # Check if OpenAI has a valid key (shared with reasoning models).
        def _has_openai_key() -> bool:
            try:
                key = get_api_key("openai")
                return bool(key)
            except Exception:
                return False

        openai_has_key = _has_openai_key()

        providers_info = {
            "openai": {
                "enabled": preferences.models.openai_transcription_enabled,
                "has_key": openai_has_key,
            }
        }

        if not preferences.models.use_api_transcription_models:
            return TranscriptionAPIModelsResponse(
                status="success",
                models=[],
                api_transcription_models_enabled=False,
                current_model=preferences.models.transcription_model,
                providers=providers_info,
            )

        transcription_models = []

        if preferences.models.openai_transcription_enabled:
            try:
                from ....core.models.models_registry import get_cloud_transcription_models

                cloud_models = get_cloud_transcription_models()
                for model_id, cfg in sorted(cloud_models.items(), key=lambda x: x[1].get("display_order", 999)):
                    if cfg.get("provider") != "openai":
                        continue
                    if model_id in preferences.models.openai_transcription_models and preferences.models.openai_transcription_models[model_id]:
                        transcription_models.append({
                            "id": model_id,
                            "name": model_id,
                            "display_name": f"{cfg.get('display_name', model_id)}",
                            "provider": "openai",
                            "is_api_model": True,
                            "description": cfg.get("description", "OpenAI transcription model"),
                            "api_model_name": cfg.get("api_model_name", ""),
                        })
            except Exception as e:
                api_logger.warning(f"Failed to load cloud transcription models: {e}")

        return TranscriptionAPIModelsResponse(
            status="success",
            models=transcription_models,
            api_transcription_models_enabled=preferences.models.use_api_transcription_models,
            current_model=preferences.models.transcription_model,
            providers=providers_info,
        )
    except Exception as e:
        api_logger.error(f"❌ Error getting API transcription models: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@transcription_router.put("/transcription/toggle", response_model=TranscriptionAPIToggleResponse)
async def toggle_api_transcription_models(settings: TranscriptionAPIToggleRequest) -> TranscriptionAPIToggleResponse:
    """Toggle the master switch for API transcription models."""
    try:
        api_logger.debug(f"🔧 Toggling API transcription models master switch: {settings.enabled}")

        preferences = load_preferences()
        preferences.models.use_api_transcription_models = settings.enabled

        if settings.enabled and not preferences.models.openai_transcription_enabled:
            try:
                if get_api_key("openai"):
                    preferences.models.openai_transcription_enabled = True
                    api_logger.info("Automatically enabling OpenAI transcription provider")
            except Exception as e:
                api_logger.info(f"OpenAI API key not available for transcription: {e}")

        save_preferences(preferences)

        return TranscriptionAPIToggleResponse(
            status="success",
            api_transcription_models_enabled=preferences.models.use_api_transcription_models,
            providers_enabled={
                "openai": preferences.models.openai_transcription_enabled,
            }
        )
    except Exception as e:
        api_logger.error(f"❌ Error toggling API transcription models: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@transcription_router.put("/transcription/providers/{provider}", response_model=TranscriptionAPIProviderUpdateResponse)
async def update_transcription_provider_settings(
    provider: str,
    settings: TranscriptionAPIProviderUpdateRequest
) -> TranscriptionAPIProviderUpdateResponse:
    """Update settings for a transcription API provider."""
    try:
        if provider not in ["openai"]:
            raise HTTPException(status_code=400, detail=f"Invalid transcription provider: {provider}. Currently only 'openai' is supported.")

        preferences = load_preferences()
        _set_transcription_provider_enabled(preferences, provider, settings.enabled)

        if not settings.enabled:
            other_providers = [p for p in ["openai"] if p != provider]
            other_enabled = any(_is_transcription_provider_enabled(preferences, p) for p in other_providers)
            if not other_enabled:
                preferences.models.use_api_transcription_models = False
        else:
            if not preferences.models.use_api_transcription_models:
                preferences.models.use_api_transcription_models = True

        save_preferences(preferences)

        provider_models = _get_transcription_provider_models_dict(preferences, provider) or {}
        provider_info = {
            "provider": provider,
            "enabled": _is_transcription_provider_enabled(preferences, provider),
            "models_enabled": sum(1 for e in provider_models.values() if e),
            "total_models": len(provider_models),
        }

        return TranscriptionAPIProviderUpdateResponse(status="updated", provider=provider_info)
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Error updating transcription API provider: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@transcription_router.put("/transcription/{provider}/{model_id}", response_model=TranscriptionAPIModelUpdateResponse)
async def update_transcription_model_settings(
    provider: str,
    model_id: str,
    settings: TranscriptionAPIModelUpdateRequest
) -> TranscriptionAPIModelUpdateResponse:
    """Update settings for a specific transcription API model."""
    try:
        if provider not in ["openai"]:
            raise HTTPException(status_code=400, detail=f"Invalid transcription provider: {provider}")

        preferences = load_preferences()

        from ....core.models.models_registry import is_in_registry

        models_dict = _get_transcription_provider_models_dict(preferences, provider)
        if models_dict is None:
            raise HTTPException(status_code=400, detail=f"Invalid transcription provider: {provider}")

        if model_id not in models_dict:
            if is_in_registry(model_id):
                models_dict[model_id] = False
            else:
                raise HTTPException(status_code=400, detail=f"Unknown transcription model: {model_id}")

        models_dict[model_id] = settings.enabled

        if settings.enabled and settings.set_as_default:
            preferences.models.transcription_model = model_id
            api_logger.info(f"Set {provider}/{model_id} as the default transcription model")

        save_preferences(preferences)

        model_info = {
            "provider": provider,
            "model_id": model_id,
            "enabled": models_dict.get(model_id, False),
            "is_current_model": preferences.models.transcription_model == model_id,
        }

        return TranscriptionAPIModelUpdateResponse(status="updated", model=model_info)
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Error updating transcription API model: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
