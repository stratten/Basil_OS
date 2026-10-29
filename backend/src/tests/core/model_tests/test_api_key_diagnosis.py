"""Provider key diagnosis: a brand-new key with no credit must not be reported as valid."""

from unittest.mock import patch

import pytest

from api.core.services import api_key_validation
from api.core.services.api_key_validation import classify_provider_error, diagnose_provider_api_key, validate_provider_api_key

OPENAI_KEY = "sk-" + "a" * 40


class _ProviderError(Exception):
    def __init__(self, message, *, status_code=None, code=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (_ProviderError("Error code: 429 - {'error': {'code': 'insufficient_quota'}}", status_code=429, code="insufficient_quota"), "no_credit"),
        (_ProviderError("Your credit balance is too low to access the Anthropic API.", status_code=400), "no_credit"),
        (_ProviderError("rate limit reached for requests", status_code=429), "rate_limited"),
        (RuntimeError("429 RESOURCE_EXHAUSTED. You exceeded your current quota"), "rate_limited"),
        (_ProviderError("Incorrect API key provided", status_code=401), "invalid_key"),
        (RuntimeError("API_KEY_INVALID"), "invalid_key"),
        (_ProviderError("The model `gpt-x` does not exist or you do not have access to it", status_code=404, code="model_not_found"), "model_access"),
        (_ProviderError("forbidden", status_code=403), "model_access"),
        (ConnectionError("Connection refused"), "network"),
        (TimeoutError("timed out"), "network"),
        (RuntimeError("something odd"), "unknown"),
    ],
)
def test_provider_errors_are_classified_into_actionable_categories(error, category):
    assert classify_provider_error(error) == category


def test_an_insufficient_quota_429_is_no_longer_reported_as_a_valid_key():
    error = _ProviderError("You exceeded your current quota (insufficient_quota)", status_code=429, code="insufficient_quota")

    with patch.object(api_key_validation, "call_provider_with_key", side_effect=error):
        valid, message = validate_provider_api_key("openai", OPENAI_KEY)
        diagnosis = diagnose_provider_api_key("openai", OPENAI_KEY)

    assert valid is False
    assert message.startswith("API validation failed:")
    assert diagnosis.category == "no_credit"
    assert "payment method" in diagnosis.next_step


def test_a_plain_rate_limit_is_still_a_valid_key_with_a_note():
    with patch.object(api_key_validation, "call_provider_with_key", side_effect=_ProviderError("slow down", status_code=429)):
        diagnosis = diagnose_provider_api_key("openai", OPENAI_KEY)

    assert diagnosis.valid is True
    assert diagnosis.category == "rate_limited"


def test_a_working_key_has_a_valid_diagnosis():
    with patch.object(api_key_validation, "call_provider_with_key"):
        diagnosis = diagnose_provider_api_key("openai", OPENAI_KEY)

    assert (diagnosis.category, diagnosis.valid, diagnosis.message) == ("valid", True, None)


def test_the_diagnosis_never_contains_the_key():
    secret_bearing = _ProviderError("Incorrect API key provided: " + OPENAI_KEY[:8] + "...", status_code=401)

    with patch.object(api_key_validation, "call_provider_with_key", side_effect=secret_bearing):
        diagnosis = diagnose_provider_api_key("openai", OPENAI_KEY)

    assert OPENAI_KEY not in (diagnosis.message or "")
    assert OPENAI_KEY not in diagnosis.next_step
