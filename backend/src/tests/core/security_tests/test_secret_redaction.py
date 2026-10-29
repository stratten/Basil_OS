from __future__ import annotations

import pytest

from api.core.security.secret_redaction import REDACTED_PLACEHOLDER, redact_secrets

SECRET = "amn_FAKEfixtureTOKEN0123456789abcdef"


@pytest.mark.parametrize(
    "text",
    [
        f"curl -H 'Authorization: Bearer {SECRET}' https://example.test",
        f'curl -H "authorization: bearer {SECRET}" https://example.test',
        f"Authorization: Basic {SECRET}==",
        f"curl -H 'x-api-key: {SECRET}' https://example.test",
        f"echo Bearer {SECRET}",
        f"api_key={SECRET}",
        "export OPENAI=sk-abcdefghijklmnop12345",
    ],
)
def test_credentials_are_replaced(text):
    redacted = redact_secrets(text)

    assert SECRET not in redacted
    assert "sk-abcdefghijklmnop12345" not in redacted
    assert REDACTED_PLACEHOLDER in redacted


@pytest.mark.parametrize(
    "text",
    [
        "",
        "ls -la ~/Documents",
        "The bearer of this message is Alex.",
        "Authorization was granted by the user.",
        "curl https://example.test/v1/changes?since=111",
    ],
)
def test_ordinary_text_is_unchanged(text):
    assert redact_secrets(text) == text


def test_the_original_string_is_not_modified():
    original = f"Authorization: Bearer {SECRET}"
    redact_secrets(original)

    assert SECRET in original
