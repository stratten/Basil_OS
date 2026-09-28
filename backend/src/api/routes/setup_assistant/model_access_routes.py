"""Backend-confirmed model-access selection for the Setup Assistant."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from api.core.models.models_registry import get_local_reasoning_models, get_model
from api.core.models.models_registry.cloud_reasoning_registry import CLOUD_REASONING_MODELS
from api.core.models.preferences import APIKeyPreference, Preferences
from api.core.preferences.preferences_io import save_preferences
from api.core.services.api_key_validation import validate_provider_api_key
from api.core.services.model_access_policy import check_basil_cloud_eligibility
from api.core.services.model_service import get_auth_access_token, get_model_service
from api.routes.setup_assistant.models import (
    SetupAgentModelAccess,
    SetupAgentModelAccessMode,
    SetupAgentModelAccessOption,
    SetupAgentModelAccessOptionsResponse,
    SetupAgentModelAccessSelectRequest,
    SetupAgentModelAccessSelectResponse,
    SetupAgentModelMetadata,
    SetupAgentProviderModelChoice,
)
from config.api_keys import has_user_key, set_api_key

router = APIRouter(prefix="/model-access", tags=["Setup Assistant"])

PROVIDER_KEY_CANDIDATES = ("anthropic", "openai", "google")


def _default_local_model_id() -> Optional[str]:
    return next(
        (
            model_id
            for model_id, config in get_local_reasoning_models().items()
            if config.get("recommended_for_onboarding") is True
            and "reasoning" in config.get("capabilities", [])
        ),
        None,
    )


def _provider_model_candidates(provider: str) -> list[tuple[str, dict]]:
    candidates = [
        (model_id, config)
        for model_id, config in CLOUD_REASONING_MODELS.items()
        if config.get("provider") == provider
        and "reasoning" in config.get("capabilities", [])
        and config.get("visible", True) is not False
    ]
    return sorted(candidates, key=lambda candidate: candidate[1].get("display_order", 999))


def _default_provider_model(provider: str) -> Optional[tuple[str, dict]]:
    """Return the registry-designated setup default, falling back to display order."""

    candidates = _provider_model_candidates(provider)
    return next(
        (
            candidate
            for candidate in candidates
            if candidate[1].get("recommended_for_onboarding") is True
        ),
        candidates[0] if candidates else None,
    )


def _provider_model_choices(provider: str) -> list[SetupAgentProviderModelChoice]:
    default = _default_provider_model(provider)
    default_model_id = default[0] if default else None
    return [
        SetupAgentProviderModelChoice(
            provider=provider,
            model_id=model_id,
            display_name=str(config.get("display_name", model_id)),
            recommended=model_id == default_model_id,
        )
        for model_id, config in _provider_model_candidates(provider)
    ]


def _selected_provider_model(provider: str, model_id: Optional[str]) -> tuple[str, dict]:
    if model_id:
        config = get_model(model_id)
        if not config:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_id}' is not in the model registry.",
            )
        if config.get("provider") != provider or config.get("location") != "cloud":
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_id}' is not a cloud model for {provider}.",
            )
        if "reasoning" not in config.get("capabilities", []):
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_id}' does not support reasoning.",
            )
        return model_id, config

    candidate = _default_provider_model(provider)
    if candidate is None:
        raise HTTPException(
            status_code=500,
            detail=f"No reasoning-capable {provider} model is configured.",
        )
    return candidate


def _save_access_preference(preference: APIKeyPreference) -> None:
    preferences = Preferences.load()
    preferences.auth.api_key_preference = preference
    save_preferences(preferences)


@router.get("/options", response_model=SetupAgentModelAccessOptionsResponse)
async def get_model_access_options() -> SetupAgentModelAccessOptionsResponse:
    """Return sanitized availability for each setup model-access route."""

    local_model_id = _default_local_model_id()
    configured_provider = next(
        (
            provider
            for provider in PROVIDER_KEY_CANDIDATES
            if has_user_key(provider)
        ),
        None,
    )
    access_token = get_auth_access_token()
    configured_default = (
        _default_provider_model(configured_provider) if configured_provider else None
    )

    options = [
        SetupAgentModelAccessOption(
            mode=SetupAgentModelAccessMode.local,
            available=local_model_id is not None,
            unavailable_reason=(
                None
                if local_model_id
                else "No reasoning-capable local model is available. Download one in Settings first."
            ),
            local_model_id=local_model_id,
        ),
        SetupAgentModelAccessOption(
            mode=SetupAgentModelAccessMode.provider_key,
            available=True,
            provider=configured_provider,
            model_id=configured_default[0] if configured_default else None,
            display_name=(
                str(configured_default[1].get("display_name", configured_default[0]))
                if configured_default
                else None
            ),
            requires_provider_key_input=configured_provider is None,
            provider_models=[
                choice
                for provider in PROVIDER_KEY_CANDIDATES
                for choice in _provider_model_choices(provider)
            ],
        ),
    ]

    if access_token is None:
        options.append(
            SetupAgentModelAccessOption(
                mode=SetupAgentModelAccessMode.basil_cloud,
                available=False,
                unavailable_reason="Sign in to Basil Cloud to use this route.",
            )
        )
    else:
        eligibility = await check_basil_cloud_eligibility(access_token)
        options.append(
            SetupAgentModelAccessOption(
                mode=SetupAgentModelAccessMode.basil_cloud,
                available=eligibility.eligible,
                unavailable_reason=(
                    None
                    if eligibility.eligible
                    else eligibility.message or eligibility.reason
                ),
            )
        )

    return SetupAgentModelAccessOptionsResponse(options=options)


@router.post("/select", response_model=SetupAgentModelAccessSelectResponse)
async def select_model_access(
    request: SetupAgentModelAccessSelectRequest,
) -> SetupAgentModelAccessSelectResponse:
    """Validate one requested route and return a backend-confirmed selection."""

    if request.mode == SetupAgentModelAccessMode.local:
        return _select_local(request)
    if request.mode == SetupAgentModelAccessMode.provider_key:
        return _select_provider_key(request)
    if request.mode == SetupAgentModelAccessMode.basil_cloud:
        return await _select_basil_cloud(request)
    raise HTTPException(status_code=400, detail=f"Unknown model-access mode: {request.mode}")


def _select_local(
    request: SetupAgentModelAccessSelectRequest,
) -> SetupAgentModelAccessSelectResponse:
    local_models = get_local_reasoning_models()
    model_id = request.local_model_id or _default_local_model_id()
    if not model_id or model_id not in local_models:
        raise HTTPException(
            status_code=400,
            detail="No reasoning-capable local model is available. Download one in Settings first.",
        )

    config = local_models[model_id]
    if "reasoning" not in config.get("capabilities", []):
        raise HTTPException(
            status_code=400,
            detail=f"Local model '{model_id}' does not support reasoning.",
        )

    model_type, separator, variant = model_id.partition("-")
    if not separator or not get_model_service().is_model_downloaded(model_type, variant):
        raise HTTPException(
            status_code=400,
            detail=f"Local model '{model_id}' is not downloaded yet.",
        )

    _save_access_preference(APIKeyPreference.LOCAL_ONLY)
    return SetupAgentModelAccessSelectResponse(
        access=SetupAgentModelAccess(
            mode=SetupAgentModelAccessMode.local,
            local_model_id=model_id,
            resolved=True,
        ),
        model_metadata=SetupAgentModelMetadata(
            provider=str(config.get("provider", "local")),
            model_id=model_id,
            display_name=str(config.get("display_name", model_id)),
            access_mode=SetupAgentModelAccessMode.local,
        ),
    )


def _select_provider_key(
    request: SetupAgentModelAccessSelectRequest,
) -> SetupAgentModelAccessSelectResponse:
    if not request.provider:
        raise HTTPException(
            status_code=400,
            detail="Select a provider before choosing the provider-key route.",
        )
    provider = request.provider.lower()
    if provider not in PROVIDER_KEY_CANDIDATES:
        raise HTTPException(status_code=400, detail=f"Unsupported provider '{provider}'.")

    if request.provider_api_key:
        valid, error = validate_provider_api_key(provider, request.provider_api_key)
        if not valid:
            raise HTTPException(
                status_code=400,
                detail=error or f"That {provider} key could not be validated.",
            )
        if not set_api_key(provider, request.provider_api_key):
            raise HTTPException(status_code=400, detail=f"Could not save the {provider} key.")
    elif not has_user_key(provider):
        raise HTTPException(
            status_code=400,
            detail=f"No {provider} key is configured yet.",
        )

    model_id, config = _selected_provider_model(provider, request.model_id)
    _save_access_preference(APIKeyPreference.OWN_KEYS)
    return SetupAgentModelAccessSelectResponse(
        access=SetupAgentModelAccess(
            mode=SetupAgentModelAccessMode.provider_key,
            provider=provider,
            model_id=model_id,
            resolved=True,
        ),
        model_metadata=SetupAgentModelMetadata(
            provider=provider,
            model_id=model_id,
            display_name=str(config.get("display_name", model_id)),
            openrouter_model_id=config.get("openrouter_id"),
            access_mode=SetupAgentModelAccessMode.provider_key,
        ),
    )


async def _select_basil_cloud(
    request: SetupAgentModelAccessSelectRequest,
) -> SetupAgentModelAccessSelectResponse:
    access_token = get_auth_access_token()
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail="Sign in to Basil Cloud before choosing this route.",
        )

    eligibility = await check_basil_cloud_eligibility(access_token)
    if not eligibility.eligible:
        raise HTTPException(
            status_code=402,
            detail=eligibility.message or eligibility.reason or "Basil Cloud is unavailable.",
        )

    candidates = (
        (model_id, config)
        for model_id, config in CLOUD_REASONING_MODELS.items()
        if config.get("used_by_setup_agent") is True
        and config.get("supports_openrouter_proxy") is True
    )
    selected = next(candidates, None)
    if selected is None:
        raise HTTPException(
            status_code=500,
            detail="No proxy-compatible setup model is configured.",
        )

    model_id, config = selected
    _save_access_preference(APIKeyPreference.BASIL_CLOUD)
    return SetupAgentModelAccessSelectResponse(
        access=SetupAgentModelAccess(
            mode=SetupAgentModelAccessMode.basil_cloud,
            model_id=model_id,
            resolved=True,
        ),
        model_metadata=SetupAgentModelMetadata(
            provider=str(config.get("provider", "proxy")),
            model_id=model_id,
            display_name=str(config.get("display_name", model_id)),
            openrouter_model_id=config.get("openrouter_id"),
            access_mode=SetupAgentModelAccessMode.basil_cloud,
        ),
    )
