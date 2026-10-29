"""Shared provider API-key validation logic.

Used by both the Settings API-models routes and the Setup Assistant
model-access routes so a key is confirmed against the real provider
API in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

# Known key shapes per provider. A key that does not match is never rejected for that reason alone: providers change their key formats without notice, so the live API call is the only authority on validity. A mismatch only adds a hint to the error message when that call fails.
KEY_FORMAT_VALIDATORS: Dict[str, Callable[[str], bool]] = {
    "anthropic": lambda k: k.startswith("sk-ant-") and len(k) > 20,
    "openai": lambda k: k.startswith("sk-") and len(k) > 20,
    "google": lambda k: k.startswith(("AI", "AQ.")) and len(k) > 20,
    "gemini": lambda k: k.startswith(("AI", "AQ.")) and len(k) > 20,
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


_QUOTA_LIMITED_NOTE = "The key was accepted, but this provider reported a rate or quota limit when it was tested, so requests may be limited until quota is available."


def _is_rate_limited(exc: Exception) -> bool:
    """True when ``exc`` is a provider 429 response, which is only returned to a key the provider accepted."""
    for attribute in ("status_code", "code"):
        if getattr(exc, attribute, None) == 429:
            return True
    message = str(exc).upper()
    return "RESOURCE_EXHAUSTED" in message or "RATE_LIMIT" in message or "RATE LIMIT" in message


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
        # The validation model is a GPT-5-class reasoning model, which needs the Responses API. Its 16 is the API's minimum output budget; an incomplete reply still proves the key works.
        client.responses.create(
            model=validation_model,
            input="Hello",
            max_output_tokens=16,
        )
    elif provider in ("google", "gemini"):
        from google import genai

        client = genai.Client(api_key=key)
        try:
            client.models.generate_content(
                model=validation_model,
                contents="Hi",
                config={
                    "max_output_tokens": 1,
                    "automatic_function_calling": {"disable": True},
                },
            )
        finally:
            client.close()
    else:
        raise ValueError(f"No API validation logic for provider: {provider}")


@dataclass(frozen=True)
class KeyDiagnosis:
    """The outcome of testing a provider key, in categories a person can act on.

    ``category`` is one of: valid, rate_limited, invalid_key, no_credit, model_access, network, unknown. ``valid`` is True only for categories
    where the key is accepted and usable (valid, rate_limited). ``message`` is the technical summary and ``next_step`` is the plain-language
    thing to do about it. Neither ever contains the key.
    """

    category: str
    valid: bool
    message: Optional[str]
    next_step: str


_NEXT_STEPS: Dict[str, str] = {
    "valid": "The key works. Enable the provider's models in Settings to start using them.",
    "rate_limited": "The key is accepted, but the provider is limiting requests right now. It should work once the limit clears.",
    "invalid_key": "Copy the key again from the provider's API keys page, paste the whole key, and make sure it belongs to this provider.",
    "no_credit": (
        "The key is real but the account has no usable credit. Add a payment method or buy credits on the provider's billing page, "
        "wait a minute for it to apply, then test again. A brand-new key often needs credit before it can make any request."
    ),
    "model_access": (
        "The key is real but its project cannot use the model Basil tests with. Check the project's model access on the provider's "
        "dashboard, or use a key from a project that has access."
    ),
    "network": "Basil could not reach the provider. Check the internet connection, VPN, or firewall, then test again.",
    "unknown": "The provider returned an error Basil does not recognize. Test again, and check the provider's status page if it persists.",
}

_NO_CREDIT_MARKERS = ("insufficient_quota", "credit balance", "billing_hard_limit", "purchase credits")
_INVALID_KEY_MARKERS = (
    "invalid api key",
    "incorrect api key",
    "invalid x-api-key",
    "api_key_invalid",
    "api key not valid",
    "unauthorized",
    "authentication",
)
_MODEL_ACCESS_MARKERS = ("model_not_found", "does not have access to model", "not_found_error", "model not found", "you do not have access")
_NETWORK_MARKERS = ("connection", "timed out", "timeout", "name or service not known", "nodename nor servname", "network is unreachable")


def _status_of(exc: Exception) -> Optional[int]:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    return None


def classify_provider_error(exc: Exception) -> str:
    """Map a provider SDK exception to a diagnosis category. Order matters: a 429 can mean rate limit or no credit."""
    text = str(exc).lower()
    code_text = str(getattr(exc, "code", "") or "").lower()
    status = _status_of(exc)
    if any(marker in text or marker in code_text for marker in _NO_CREDIT_MARKERS):
        return "no_credit"
    if _is_rate_limited(exc):
        return "rate_limited"
    if status == 401 or any(marker in text for marker in _INVALID_KEY_MARKERS):
        return "invalid_key"
    if status == 404 or any(marker in text for marker in _MODEL_ACCESS_MARKERS):
        return "model_access"
    if status == 403:
        return "model_access"
    class_name = type(exc).__name__.lower()
    if "connection" in class_name or "timeout" in class_name or any(marker in text for marker in _NETWORK_MARKERS):
        return "network"
    return "unknown"


def diagnose_provider_api_key(provider: str, key: str) -> KeyDiagnosis:
    """Test ``key`` for ``provider`` with a real API call and say what is wrong in actionable terms. An unfamiliar key format never blocks the attempt."""
    if not key:
        return KeyDiagnosis("invalid_key", False, "No API key was provided.", "Paste an API key first.")

    format_validator = KEY_FORMAT_VALIDATORS.get(provider)
    if not format_validator:
        return KeyDiagnosis("unknown", False, f"Unknown provider: {provider}", "Use anthropic, openai, or gemini.")

    format_is_familiar = format_validator(key)

    from api.core.models.models_registry import get_validation_model_for_provider

    registry_provider = "google" if provider == "gemini" else provider
    validation_model = get_validation_model_for_provider(registry_provider)
    if not validation_model:
        return KeyDiagnosis(
            "unknown", False, f"No validation model configured for {provider.capitalize()} in registry", _NEXT_STEPS["unknown"]
        )

    try:
        call_provider_with_key(provider, key, validation_model)
        return KeyDiagnosis("valid", True, None, _NEXT_STEPS["valid"])
    except Exception as exc:
        category = classify_provider_error(exc)
        if category == "rate_limited":
            return KeyDiagnosis(category, True, _QUOTA_LIMITED_NOTE, _NEXT_STEPS[category])
        message = f"API validation failed: {normalize_api_error(str(exc))}"
        if not format_is_familiar:
            message += (
                f". This key's format is not one Basil recognizes for {provider.capitalize()}, "
                "so check that it was copied completely and belongs to that provider."
            )
        return KeyDiagnosis(category, False, message, _NEXT_STEPS[category])


def validate_provider_api_key(provider: str, key: str) -> Tuple[bool, Optional[str]]:
    """Validate ``key`` for ``provider`` with a real API call. An unfamiliar key format never blocks the attempt.

    Returns ``(valid, message)``. ``message`` is a user-facing error when ``valid`` is False. When ``valid`` is True it is ``None``, except
    that a provider rate limit (429 without a billing problem) still counts as valid, because only an accepted key gets one, and carries a
    note about the limit. A 429 that reports no remaining credit (OpenAI ``insufficient_quota``) is not valid: such a key fails every real request.
    """
    diagnosis = diagnose_provider_api_key(provider, key)
    return diagnosis.valid, diagnosis.message
