"""Shared redaction of credentials that appear inside free-form text such as command lines and tool-call logs."""

from __future__ import annotations

import re

REDACTED_PLACEHOLDER = "[REDACTED]"

_SECRET_PATTERNS = (
    # Provider keys such as sk-... .
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    # key=value pairs that name an API key.
    re.compile(r"(?i)api_key=[^\s]+"),
    # Whole HTTP credential headers, for any scheme (Bearer, Basic, Token).
    re.compile(r"(?i)authorization:\s*[A-Za-z]+\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bx-api-key:\s*[A-Za-z0-9._~+/=-]+"),
    # A bearer credential that is not preceded by a header name, for example inside a quoted argument.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
)


def redact_secrets(text: str) -> str:
    """Return the text with credentials replaced by a placeholder; the original string is not modified."""
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED_PLACEHOLDER, redacted)
    return redacted
