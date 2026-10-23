"""API key management routes for API model settings."""

from fastapi import APIRouter, HTTPException

from config.api_keys import get_api_key, list_available_providers, set_api_key

from ....core.logging.api_logger import api_logger
from ....core.services.api_key_validation import validate_provider_api_key

from .helpers import _get_models_from_registry_for_provider
from .schemas import (
    APIKeyRequest,
    APIKeyResponse,
    APIKeyTestRequest,
    APIKeyTestResponse,
    APIKeyUpdateResponse,
    APIKeysResponse,
)


api_key_router = APIRouter()


@api_key_router.get("/api_keys", response_model=APIKeysResponse)
async def get_api_keys() -> APIKeysResponse:
    """Get information about available API keys."""
    try:
        available_providers = list_available_providers()
        provider_keys = []

        for provider in available_providers:
            # Safely check for API key without throwing exceptions
            has_key = False
            key_preview = None
            try:
                key = get_api_key(provider)
                has_key = key is not None and len(key) > 0

                # Create a preview that shows just a few characters of the key
                if has_key and len(key) > 8:
                    key_preview = f"{key[:4]}...{key[-4:]}"
            except Exception as e:
                # No key available - this is fine, just means no key is set
                api_logger.debug(f"No API key available for {provider}: {e}")
                has_key = False

            # Get available models from registry
            available_models = {}
            registry_models = _get_models_from_registry_for_provider(provider)
            for model_id, model_info in registry_models:
                available_models[model_id] = {
                    "display_name": model_info.get("display_name", model_id),
                    "description": model_info.get("description", ""),
                }

            provider_keys.append(APIKeyResponse(
                provider=provider,
                has_key=has_key,
                key_preview=key_preview,
                available_models=available_models
            ))

        return APIKeysResponse(providers=provider_keys)
    except Exception as e:
        api_logger.error(f"❌ Error getting API keys: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@api_key_router.post("/api_keys", response_model=APIKeyUpdateResponse)
async def set_api_key_endpoint(request: APIKeyRequest) -> APIKeyUpdateResponse:
    """Set an API key for a provider."""
    try:
        provider = request.provider
        key = request.key

        if not provider or not key:
            raise HTTPException(status_code=400, detail="Provider and key are required")

        success = set_api_key(provider, key)

        if success:
            return APIKeyUpdateResponse(status="success", message=f"API key for {provider} has been saved")
        else:
            raise HTTPException(status_code=500, detail=f"Failed to save API key for {provider}")
    except Exception as e:
        api_logger.error(f"❌ Error setting API key: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@api_key_router.delete("/api_keys/{provider}", response_model=APIKeyUpdateResponse)
async def delete_api_key(provider: str) -> APIKeyUpdateResponse:
    """Delete an API key for a provider."""
    try:
        if not provider:
            raise HTTPException(status_code=400, detail="Provider is required")

        # Set an empty key to effectively delete it
        success = set_api_key(provider, "")

        if success:
            return APIKeyUpdateResponse(status="success", message=f"API key for {provider} has been deleted")
        else:
            raise HTTPException(status_code=500, detail=f"Failed to delete API key for {provider}")
    except Exception as e:
        api_logger.error(f"❌ Error deleting API key: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@api_key_router.post("/api_keys/test")
async def test_api_key(request: APIKeyTestRequest) -> APIKeyTestResponse:
    """Test if an API key is valid by making a simple request to the provider's API."""
    provider = request.provider
    key = request.key

    if not provider:
        raise HTTPException(status_code=400, detail="Provider is required")

    # If no key is provided, try to use the stored key
    if not key:
        key = get_api_key(provider)

    if not key or len(key) == 0:
        return APIKeyTestResponse(provider=provider, valid=False, error="No API key available")

    api_logger.info(f"Testing {provider} API key with actual API call")
    valid, error = validate_provider_api_key(provider, key)
    if valid:
        return APIKeyTestResponse(provider=provider, valid=True, details={"format": "valid", "api_validated": True})

    api_logger.error(f"{provider.capitalize()} API key validation failed: {error}")
    return APIKeyTestResponse(provider=provider, valid=False, error=error)
