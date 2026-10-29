"""API Models routes for managing API model settings and configurations."""

from fastapi import APIRouter

from .api_models.api_key_routes import (
    api_key_router,
    delete_api_key,
    get_api_keys,
    set_api_key_endpoint,
    test_api_key,
)
from .api_models.helpers import (
    _find_fallback_model,
    _get_local_default_for_capability,
    _get_models_from_registry_for_provider,
    _get_provider_from_registry,
    _get_provider_models_dict,
    _get_transcription_provider_models_dict,
    _is_provider_enabled,
    _is_transcription_provider_enabled,
    _resolve_fallback_default,
    _set_provider_enabled,
    _set_transcription_provider_enabled,
    get_model_capabilities_from_implementation,
    load_preferences,
    save_preferences,
)
from .api_models.model_settings_routes import (
    get_api_models,
    model_settings_router,
    model_update_router,
    toggle_api_models,
    update_api_model_settings,
    update_api_provider_settings,
)
from .api_models.reasoning_routes import get_api_reasoning_models, reasoning_router
from .api_models.schemas import (
    APIKeyRequest,
    APIKeyResponse,
    APIKeyTestRequest,
    APIKeyTestResponse,
    APIKeyUpdateResponse,
    APIKeysResponse,
    APIModelToggleRequest,
    APIModelToggleResponse,
    APIModelUpdateRequest,
    APIModelUpdateResponse,
    APIModelsInfoResponse,
    APIProviderUpdateRequest,
    APIProviderUpdateResponse,
    ReasoningModelsResponse,
    TranscriptionAPIModelUpdateRequest,
    TranscriptionAPIModelUpdateResponse,
    TranscriptionAPIModelsResponse,
    TranscriptionAPIProviderUpdateRequest,
    TranscriptionAPIProviderUpdateResponse,
    TranscriptionAPIToggleRequest,
    TranscriptionAPIToggleResponse,
)
from .api_models.transcription_routes import (
    get_api_transcription_models,
    toggle_api_transcription_models,
    transcription_router,
    update_transcription_model_settings,
    update_transcription_provider_settings,
)


router = APIRouter(prefix="/api_models", tags=["api-models"])

# Keep specific PUT /transcription/* routes before PUT /{provider}/{model_id}.
router.include_router(model_settings_router)
router.include_router(transcription_router)
router.include_router(model_update_router)
router.include_router(reasoning_router)
router.include_router(api_key_router)