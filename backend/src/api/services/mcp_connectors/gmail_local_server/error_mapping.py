"""Map Gmail API failures to Basil's standard error envelopes.

The agent reasons about failures by envelope kind, so a Gmail failure must look
like any other connector failure. Two cases get wording of their own because the
user can fix them and the raw Google text would not tell them how: a token that
lacks the permissions a tool needs, and a Google Cloud project that has not
turned the Gmail API on.
"""

from __future__ import annotations

from typing import Any, Dict

from ..error_normalizer import (
    ERROR_KIND_AUTH_EXPIRED,
    ERROR_KIND_INVALID_ARGUMENTS,
    ERROR_KIND_NOT_FOUND,
    ERROR_KIND_PERMISSION_DENIED,
    ERROR_KIND_RATE_LIMITED,
    ERROR_KIND_SERVER_ERROR,
    make_envelope,
)
from .gmail_api import GmailApiError

RECONNECT_ACTION = "Reconnect Gmail in Settings → Connections."

_SCOPE_REASONS = {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficient_scope"}
_API_DISABLED_REASONS = {"accessNotConfigured", "SERVICE_DISABLED", "API_KEY_SERVICE_BLOCKED"}
_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED"}


def normalize_gmail_api_error(exc: GmailApiError, *, tool_name: str) -> Dict[str, Any]:
    """Return the envelope for one Gmail API failure."""
    raw = {
        "tool_name": tool_name,
        "status_code": exc.status_code,
        "reason": exc.reason,
        "message": exc.message[:500],
    }
    status = exc.status_code
    reason = exc.reason

    if status == 401:
        return make_envelope(
            kind=ERROR_KIND_AUTH_EXPIRED,
            message="Google rejected the Gmail sign-in. It has expired or been revoked.",
            retryable=False,
            user_action_required=RECONNECT_ACTION,
            raw=raw,
        )
    if status == 403 and reason in _SCOPE_REASONS:
        return make_envelope(
            kind=ERROR_KIND_PERMISSION_DENIED,
            message=f"The Gmail sign-in does not include the permission {tool_name} needs.",
            retryable=False,
            user_action_required=(
                "Reconnect Gmail in Settings → Connections and approve every permission Google lists, "
                "so Basil receives the access this tool needs."
            ),
            raw=raw,
        )
    if status == 403 and reason in _API_DISABLED_REASONS:
        return make_envelope(
            kind=ERROR_KIND_PERMISSION_DENIED,
            message="The Gmail API is not turned on for the Google Cloud project Basil signs in with.",
            retryable=False,
            user_action_required=(
                "Turn on the Gmail API for that Google Cloud project in the Google Cloud console "
                "(APIs & Services, Library, Gmail API). Signing in again will not fix it."
            ),
            raw=raw,
        )
    if status == 429 or (status == 403 and reason in _RATE_LIMIT_REASONS):
        return make_envelope(
            kind=ERROR_KIND_RATE_LIMITED,
            message=f"Gmail is rate-limiting requests: {exc.message}",
            retryable=True,
            raw={**raw, "retry_after": exc.retry_after},
        )
    if status == 403:
        return make_envelope(
            kind=ERROR_KIND_PERMISSION_DENIED,
            message=f"Gmail refused {tool_name}: {exc.message}",
            retryable=False,
            raw=raw,
        )
    if status == 404:
        return make_envelope(
            kind=ERROR_KIND_NOT_FOUND,
            message=f"Gmail could not find what {tool_name} asked for: {exc.message}",
            retryable=False,
            raw=raw,
        )
    if status in (400, 409, 412):
        return make_envelope(
            kind=ERROR_KIND_INVALID_ARGUMENTS,
            message=f"Gmail rejected the arguments for {tool_name}: {exc.message}",
            retryable=False,
            raw=raw,
        )
    return make_envelope(
        kind=ERROR_KIND_SERVER_ERROR,
        message=f"Gmail returned an error for {tool_name} (HTTP {status}): {exc.message}",
        retryable=status >= 500,
        raw=raw,
    )
