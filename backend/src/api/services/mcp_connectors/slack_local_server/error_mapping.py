"""Map ``slack_sdk.SlackApiError`` responses to standard MCP envelopes.

Slack's Web API returns ``{"ok": false, "error": "..."}`` with HTTP 200,
and ``slack_sdk`` wraps that as a ``SlackApiError`` whose ``response.data``
carries the dict. We bucket the documented error strings into the same
small set of error kinds the rest of the connector layer uses, so the
agent's failure-mode reasoning is identical regardless of whether the
failure came from a remote MCP server or this embedded one.

Sources for each bucket: the per-endpoint error tables in Slack's API
reference at ``docs.slack.dev/reference/methods/<method>``. Only the
codes that are likely to be surfaced by the twelve tools we expose are
listed; anything unrecognized falls through to ``server_error``, which
is the right default for "we don't know exactly, but Slack told us
something went wrong."
"""

from __future__ import annotations

from typing import Any, Dict

from slack_sdk.errors import SlackApiError

from ..error_normalizer import (
    ERROR_KIND_AUTH_EXPIRED,
    ERROR_KIND_INVALID_ARGUMENTS,
    ERROR_KIND_NOT_FOUND,
    ERROR_KIND_PERMISSION_DENIED,
    ERROR_KIND_RATE_LIMITED,
    ERROR_KIND_SERVER_ERROR,
    make_envelope,
)


_AUTH_ERROR_CODES = {
    "invalid_auth",
    "not_authed",
    "token_expired",
    "token_revoked",
    "account_inactive",
    "missing_scope",
}
_PERMISSION_ERROR_CODES = {
    "no_permission",
    "user_not_visible",
    "is_archived",
    "method_disabled",
    "restricted_action",
    "ekm_access_denied",
}
_NOT_FOUND_CODES = {
    "channel_not_found",
    "thread_not_found",
    "message_not_found",
    "user_not_found",
    "file_not_found",
    "canvas_not_found",
}
_INVALID_ARG_CODES = {
    "invalid_arguments",
    "invalid_arg_name",
    "invalid_array_arg",
    "invalid_charset",
    "invalid_form_data",
    "invalid_post_type",
    "missing_post_type",
    "name_taken",
    "invalid_name",
    "invalid_name_required",
    "invalid_name_punctuation",
    "invalid_name_specials",
    "invalid_name_maxlength",
}


def normalize_slack_api_error(exc: SlackApiError, *, tool_name: str) -> Dict[str, Any]:
    """Return the standard error envelope for a ``SlackApiError``."""
    response = getattr(exc, "response", None)
    body: Dict[str, Any] = {}
    error_code = ""
    if response is not None:
        try:
            body = dict(response.data or {})
        except Exception:
            body = {}
        error_code = str(body.get("error") or "").strip()

    raw = {"slack_error": error_code, "tool": tool_name, "body": body}

    if error_code in {"ratelimited", "rate_limited"}:
        retry_after = None
        if response is not None and getattr(response, "headers", None):
            retry_after = response.headers.get("Retry-After") or response.headers.get(
                "retry-after"
            )
        return make_envelope(
            kind=ERROR_KIND_RATE_LIMITED,
            message=(
                f"Slack rate limited the {tool_name} request. "
                f"Retry after {retry_after or 'a short delay'}."
            ),
            retryable=True,
            raw={**raw, "retry_after": retry_after},
        )
    if error_code in _AUTH_ERROR_CODES:
        return make_envelope(
            kind=ERROR_KIND_AUTH_EXPIRED,
            message=(
                f"Slack rejected the call ({error_code}). Reconnect Slack "
                "to refresh credentials and scopes."
            ),
            retryable=False,
            user_action_required="Reconnect this server in Settings → Connections.",
            raw=raw,
        )
    if error_code in _NOT_FOUND_CODES:
        return make_envelope(
            kind=ERROR_KIND_NOT_FOUND,
            message=f"Slack reported {error_code} for {tool_name}.",
            retryable=False,
            raw=raw,
        )
    if error_code in _PERMISSION_ERROR_CODES:
        return make_envelope(
            kind=ERROR_KIND_PERMISSION_DENIED,
            message=f"Slack refused {tool_name}: {error_code}.",
            retryable=False,
            raw=raw,
        )
    if error_code in _INVALID_ARG_CODES:
        return make_envelope(
            kind=ERROR_KIND_INVALID_ARGUMENTS,
            message=f"Slack rejected arguments for {tool_name}: {error_code}.",
            retryable=False,
            raw=raw,
        )
    return make_envelope(
        kind=ERROR_KIND_SERVER_ERROR,
        message=f"Slack error during {tool_name}: {error_code or str(exc)}",
        retryable=False,
        raw=raw,
    )


__all__ = ["normalize_slack_api_error"]
