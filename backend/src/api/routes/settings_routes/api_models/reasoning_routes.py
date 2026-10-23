"""Reasoning API model listing route."""

from fastapi import APIRouter, Depends, HTTPException

from ....core.logging.api_logger import api_logger
from ....core.models.models_registry import get_local_reasoning_models
from ....core.services.model_service import ModelService, get_model_service

from .helpers import (
    _get_models_from_registry_for_provider,
    get_model_capabilities_from_implementation,
    load_preferences,
)
from .schemas import ReasoningModelsResponse


reasoning_router = APIRouter()


def _installed_local_reasoning_models(installed_models: dict) -> list[dict]:
    """Return installed, valid local reasoning variants in registry order."""
    installed_by_id = {
        details.get("model_id"): details
        for provider in installed_models.values()
        if isinstance(provider, dict)
        for details in provider.get("variants", {}).values()
        if isinstance(details, dict) and isinstance(details.get("model_id"), str)
    }
    local_models = []
    for model_id, config in get_local_reasoning_models().items():
        installed = installed_by_id.get(model_id)
        if installed is None or installed.get("valid") is not True:
            continue
        if "reasoning" not in installed.get("capabilities", config.get("capabilities", [])):
            continue
        local_models.append({
            "id": model_id,
            "name": model_id,
            "display_name": installed.get("name") or config.get("display_name", model_id),
            "provider": config.get("provider", "local"),
            "category": "local",
            "is_api_model": False,
            "description": config.get("description", "Installed local reasoning model"),
        })
    return local_models


def _enabled_api_reasoning_models(preferences) -> list[dict]:
    """Return enabled API reasoning models in the registry's display order."""
    models = []
    provider_specs = (
        ("anthropic", "Anthropic", preferences.models.anthropic_enabled, preferences.models.anthropic_models),
        ("openai", "OpenAI", preferences.models.openai_enabled, preferences.models.openai_models),
        ("gemini", "Google", preferences.models.gemini_enabled, preferences.models.gemini_models),
    )
    for provider, provider_label, provider_enabled, enabled_models in provider_specs:
        if not provider_enabled:
            continue
        for model_id, config in _get_models_from_registry_for_provider(provider):
            if not enabled_models.get(model_id):
                continue
            if "reasoning" not in get_model_capabilities_from_implementation(provider, model_id):
                continue
            display_name = config.get("display_name", model_id)
            models.append({
                "id": model_id,
                "name": model_id,
                "display_name": f"{display_name} ({provider_label})",
                "provider": provider,
                "category": "api",
                "is_api_model": True,
                "description": f"{provider_label} reasoning model",
            })
    return models


def _custom_reasoning_models() -> list[dict]:
    """Return configured custom reasoning models in their persisted order."""
    try:
        from ....core.models.models_registry import get_custom_models

        models = []
        for model_id, config in get_custom_models().items():
            if "reasoning" not in config.get("capabilities", []):
                continue
            handler = config.get("handler", "openai_compatible")
            handler_label = "OpenAI-Compatible" if handler == "openai_compatible" else "Anthropic-Compatible"
            models.append({
                "id": model_id,
                "name": model_id,
                "display_name": config.get("display_name", model_id),
                "provider": "custom",
                "category": "custom",
                "is_api_model": True,
                "description": config.get("description", f"Custom {handler_label} reasoning model"),
            })
        return models
    except Exception as error:
        api_logger.warning(f"Failed to load custom models for reasoning list: {error}")
        return []


@reasoning_router.get("/reasoning", response_model=ReasoningModelsResponse)
async def get_api_reasoning_models(
    model_service: ModelService = Depends(get_model_service),
) -> ReasoningModelsResponse:
    """Get installed local plus enabled API and custom reasoning models."""
    try:
        preferences = load_preferences()
        reasoning_models = _installed_local_reasoning_models(model_service.get_installed_models())
        if preferences.models.use_api_models:
            reasoning_models.extend(_enabled_api_reasoning_models(preferences))
            reasoning_models.extend(_custom_reasoning_models())

        return ReasoningModelsResponse(
            status="success",
            models=reasoning_models,
            api_models_enabled=preferences.models.use_api_models,
            current_model=preferences.models.reasoning_model,
            fallback_enabled=preferences.models.reasoning_fallback_enabled,
            fallback_model_id=preferences.models.reasoning_fallback_model_id,
        )
    except Exception as error:
        api_logger.error(f"❌ Error getting API reasoning models: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(error))
