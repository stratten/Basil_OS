"""Shared provider API-key validation logic.

Used by both the Settings API-models routes and the Setup Assistant
model-access routes so a key is confirmed against the real provider
API in exactly one place.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

# Format validation patterns per provider - a cheap pre-check before making a live API call.
KEY_FORMAT_VALIDATORS: Dict[str, Callable[[str], bool]] = {
    "anthropic": lambda k: k.startswith("sk-ant-") and len(k) > 20,
    "openai": lambda k: k.startswith("sk-") and len(k) > 20,
    "google": lambda k: k.startswith("AI") and len(k) > 20,
    "gemini": lambda k: k.startswith("AI") and len(k) > 20,
}


def normalize_api_error(error_msg: str) -> str:
    """Normalize common provider error messages for user-friendly display."""
    error_lower = error_msg.lower()
    if "invalid api key" in error_lower or "unauthorized" in error_lower or "api_key_invalid" in error_lower:
        return "Invalid API key"
    elif "insufficient" in error_lower and "quota" in error_lower:
        return "Insufficient quota or credits"
    elif "quota" in error_lower:
        return "Insufficient quota or API access"
    return error_msg


def call_provider_with_key(provider: str, key: str, validation_model: str) -> None:
    """Make a minimal live API call to confirm the key works. Raises on failure."""
    if provider == "anthropic":
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        client.messages.create(
            model=validation_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "Hello"}],
        )
    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=key)
        client.chat.completions.create(
            model=validation_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "Hello"}],
        )
    elif provider in ("google", "gemini"):
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel(validation_model)
        model.generate_content("Hi", generation_config={"max_output_tokens": 1})
    else:
        raise ValueError(f"No API validation logic for provider: {provider}")


def validate_provider_api_key(provider: str, key: str) -> Tuple[bool, Optional[str]]:
    """Validate ``key`` for ``provider`` with a format check plus a real API call.

    Returns ``(valid, error)`` where ``error`` is a user-facing message when
    ``valid`` is False, and ``None`` when ``valid`` is True.
    """
    if not key:
        return False, "No API key was provided."

    format_validator = KEY_FORMAT_VALIDATORS.get(provider)
    if not format_validator:
        return False, f"Unknown provider: {provider}"

    if not format_validator(key):
        return False, f"Key does not appear to be a valid {provider.capitalize()} API key format"

    from api.core.models.models_registry import get_validation_model_for_provider

    registry_provider = "google" if provider == "gemini" else provider
    validation_model = get_validation_model_for_provider(registry_provider)
    if not validation_model:
        return False, f"No validation model configured for {provider.capitalize()} in registry"

    try:
        call_provider_with_key(provider, key, validation_model)
        return True, None
    except Exception as exc:
        return False, f"API validation failed: {normalize_api_error(str(exc))}"
