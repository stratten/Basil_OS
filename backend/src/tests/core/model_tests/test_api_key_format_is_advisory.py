"""An unfamiliar API key format must never stop Basil from trying the key against the provider."""

from unittest.mock import patch

import pytest

from api.core.services import api_key_validation
from api.core.services.api_key_validation import KEY_FORMAT_VALIDATORS, validate_provider_api_key

UNFAMILIAR_KEYS = {
    "google": "ZZ.unfamiliar-key-format-0123456789",
    "gemini": "ZZ.unfamiliar-key-format-0123456789",
    "openai": "unfamiliar-key-format-0123456789",
    "anthropic": "unfamiliar-key-format-0123456789",
}


@pytest.mark.parametrize("provider", sorted(UNFAMILIAR_KEYS))
def test_unfamiliar_key_format_is_still_sent_to_the_provider(provider):
    key = UNFAMILIAR_KEYS[provider]
    assert KEY_FORMAT_VALIDATORS[provider](key) is False

    with patch.object(api_key_validation, "call_provider_with_key") as call:
        assert validate_provider_api_key(provider, key) == (True, None)

    call.assert_called_once()
    assert call.call_args.args[:2] == (provider, key)


@pytest.mark.parametrize("provider", sorted(UNFAMILIAR_KEYS))
def test_failed_call_with_unfamiliar_format_adds_a_hint(provider):
    key = UNFAMILIAR_KEYS[provider]

    with patch.object(api_key_validation, "call_provider_with_key", side_effect=RuntimeError("API_KEY_INVALID")):
        valid, error = validate_provider_api_key(provider, key)

    assert valid is False
    assert error.startswith("API validation failed: Invalid API key")
    assert "format is not one Basil recognizes" in error
    assert "does not appear to be a valid" not in error


def test_failed_call_with_familiar_format_has_no_format_hint():
    with patch.object(api_key_validation, "call_provider_with_key", side_effect=RuntimeError("API_KEY_INVALID")):
        valid, error = validate_provider_api_key("google", "AIzaSyExampleExampleExampleExample123")

    assert valid is False
    assert error == "API validation failed: Invalid API key"


@pytest.mark.parametrize("key", ["AIzaSyExampleExampleExampleExample123", "AQ.ExampleExampleExampleExample123"])
def test_both_google_key_shapes_are_familiar(key):
    assert KEY_FORMAT_VALIDATORS["google"](key) is True
    assert KEY_FORMAT_VALIDATORS["gemini"](key) is True


def test_unknown_provider_and_empty_key_are_still_rejected_without_a_call():
    with patch.object(api_key_validation, "call_provider_with_key") as call:
        assert validate_provider_api_key("google", "") == (False, "No API key was provided.")
        assert validate_provider_api_key("nonexistent", "abc") == (False, "Unknown provider: nonexistent")

    call.assert_not_called()


class _StatusError(Exception):
    def __init__(self, message, *, status_code=None, code=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@pytest.mark.parametrize(
    "error",
    [
        _StatusError("rate limited", status_code=429),
        _StatusError("quota exceeded", code=429),
        RuntimeError("429 RESOURCE_EXHAUSTED. You exceeded your current quota"),
    ],
)
def test_rate_limit_response_counts_as_a_valid_key_with_a_note(error):
    with patch.object(api_key_validation, "call_provider_with_key", side_effect=error):
        valid, note = validate_provider_api_key("google", "AQ.ExampleExampleExampleExample123")

    assert valid is True
    assert "rate or quota limit" in note


@pytest.mark.parametrize(
    "error",
    [
        _StatusError("API_KEY_INVALID", status_code=400),
        _StatusError("unauthorized", status_code=401),
        _StatusError("API key not valid", code=400),
        RuntimeError("connection reset"),
    ],
)
def test_other_failures_are_still_rejected(error):
    with patch.object(api_key_validation, "call_provider_with_key", side_effect=error):
        valid, message = validate_provider_api_key("google", "AQ.ExampleExampleExampleExample123")

    assert valid is False
    assert message.startswith("API validation failed:")


def test_settings_route_exposes_the_rate_limit_note_on_a_valid_key():
    from api.core.services.api_key_validation import KeyDiagnosis
    from api.routes.settings_routes.api_models import api_key_routes
    from api.routes.settings_routes.api_models.schemas import APIKeyTestRequest

    import asyncio

    with patch.object(api_key_routes, "diagnose_provider_api_key", return_value=KeyDiagnosis("rate_limited", True, "limited", "wait")):
        response = asyncio.run(api_key_routes.test_api_key(APIKeyTestRequest(provider="google", key="AQ.x")))
    assert response.valid is True
    assert response.details == {"format": "valid", "api_validated": True, "note": "limited"}
    assert response.diagnosis == {"category": "rate_limited", "next_step": "wait"}

    with patch.object(api_key_routes, "diagnose_provider_api_key", return_value=KeyDiagnosis("valid", True, None, "ok")):
        response = asyncio.run(api_key_routes.test_api_key(APIKeyTestRequest(provider="google", key="AQ.x")))
    assert response.details == {"format": "valid", "api_validated": True}
