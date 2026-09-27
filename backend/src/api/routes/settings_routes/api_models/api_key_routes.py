"""API key management routes for API model settings."""

from fastapi import APIRouter, HTTPException

from config.api_keys import get_api_key, list_available_providers, set_api_key

from ....core.logging.api_logger import api_logger

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


# Format validation patterns per provider
_KEY_FORMAT_VALIDATORS = {
    "anthropic": lambda k: k.startswith("sk-ant-") and len(k) > 20,
    "openai": lambda k: k.startswith("sk-") and len(k) > 20,
    "google": lambda k: k.startswith("AI") and len(k) > 20,
    "gemini": lambda k: k.startswith("AI") and len(k) > 20,
}


def _validate_key_with_api(provider: str, key: str, validation_model: str) -> None:
    """
    Make a minimal API call to validate the key. Raises on failure.

    Args:
        provider: Provider name (anthropic, openai, google, gemini)
        key: API key to validate
        validation_model: Model ID to use for validation
    """
    if provider == "anthropic":
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        client.messages.create(
            model=validation_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "Hello"}]
        )
    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=key)
        client.chat.completions.create(
            model=validation_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "Hello"}]
        )
    elif provider in ["google", "gemini"]:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel(validation_model)
        model.generate_content("Hi", generation_config={'max_output_tokens': 1})
    else:
        raise ValueError(f"No API validation logic for provider: {provider}")


def _normalize_api_error(error_msg: str) -> str:
    """Normalize common API error messages for user-friendly display."""
    error_lower = error_msg.lower()
    if "invalid api key" in error_lower or "unauthorized" in error_lower or "api_key_invalid" in error_lower:
        return "Invalid API key"
    elif "insufficient" in error_lower and "quota" in error_lower:
        return "Insufficient quota or credits"
    elif "quota" in error_lower:
        return "Insufficient quota or API access"
    return error_msg


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

    # Normalize provider name for google/gemini
    registry_provider = "google" if provider == "gemini" else provider

    # Check format validation
    format_validator = _KEY_FORMAT_VALIDATORS.get(provider)
    if not format_validator:
        return APIKeyTestResponse(provider=provider, valid=False, error=f"Unknown provider: {provider}")

    if not format_validator(key):
        return APIKeyTestResponse(
            provider=provider,
            valid=False,
            error=f"Key does not appear to be a valid {provider.capitalize()} API key format"
        )

    # Get validation model from registry
    from api.core.models.models_registry import get_validation_model_for_provider
    validation_model = get_validation_model_for_provider(registry_provider)
    if not validation_model:
        return APIKeyTestResponse(
            provider=provider,
            valid=False,
            error=f"No validation model configured for {provider.capitalize()} in registry"
        )

    # Make actual API call to validate
    api_logger.info(f"Testing {provider} API key with actual API call (model: {validation_model})")
    try:
        _validate_key_with_api(provider, key, validation_model)
        return APIKeyTestResponse(provider=provider, valid=True, details={"format": "valid", "api_validated": True})
    except Exception as e:
        api_logger.error(f"{provider.capitalize()} API key validation failed: {str(e)}")
        return APIKeyTestResponse(
            provider=provider,
            valid=False,
            error=f"API validation failed: {_normalize_api_error(str(e))}"
        )
