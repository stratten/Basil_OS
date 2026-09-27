"""Normalize transport-level + protocol-level MCP failures into one envelope.

Every external connector failure must surface to the agent (and to the
audit log) in the same shape, so the agent's failure-mode reasoning is
not coupled to which client library raised which exception. This module
is the single seam where ``mcp.shared.exceptions.McpError``,
``httpx`` HTTP-status errors, transport timeouts, and unexpected
exceptions are mapped to a small, stable enum of error kinds.

The kinds were chosen to match the four behaviors the agent must
distinguish at runtime:

  * ``auth_expired``       — token bad / scope missing; the user must
                              re-consent. Agent should report this
                              clearly and stop, never retry.
  * ``rate_limited``       — backoff would help; agent may retry once
                              after surfacing the limit to the user.
  * ``permission_denied``  — local policy ('never_allow' / approval
                              denied) refused dispatch. Agent should
                              tell the user, never retry.
  * ``invalid_arguments``  — caller's arguments rejected by the server;
                              agent should fix args, not retry blindly.
  * ``not_found``          — tool/resource doesn't exist on the server;
                              agent should re-list and pick a real one.
  * ``rate_limited``       — see above
  * ``server_error``       — server is broken; user should be told.
  * ``network_error``      — local connectivity / TLS / DNS issue.
  * ``timeout``            — request exceeded our local deadline.
  * ``unknown``            — fallback; logged loudly for debugging.

The envelope is a plain dict (not a Pydantic model) because it crosses
the LangChain-tool boundary, where structured returns get JSON-encoded
into the agent's transcript anyway.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

try:
    from mcp.shared.exceptions import McpError
    from mcp import types as mcp_types
except Exception:  # pragma: no cover - the SDK is a hard dep, but be defensive
    McpError = None  # type: ignore[assignment]
    mcp_types = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


ERROR_KIND_AUTH_EXPIRED = "auth_expired"
ERROR_KIND_PERMISSION_DENIED = "permission_denied"
ERROR_KIND_RATE_LIMITED = "rate_limited"
ERROR_KIND_INVALID_ARGUMENTS = "invalid_arguments"
ERROR_KIND_NOT_FOUND = "not_found"
ERROR_KIND_SERVER_ERROR = "server_error"
ERROR_KIND_NETWORK_ERROR = "network_error"
ERROR_KIND_TIMEOUT = "timeout"
ERROR_KIND_UNKNOWN = "unknown"


def make_envelope(
    *,
    kind: str,
    message: str,
    retryable: bool = False,
    user_action_required: Optional[str] = None,
    raw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the canonical error envelope returned to the agent.

    ``user_action_required`` is a short human-language sentence the
    agent can quote verbatim back to the user (e.g. "Reconnect GitHub
    in Settings → Connections."). When non-None it signals the agent
    SHOULD surface it directly rather than paraphrase.
    """
    return {
        "ok": False,
        "error": {
            "kind": kind,
            "message": message,
            "retryable": retryable,
            "user_action_required": user_action_required,
            "raw": raw or {},
        },
    }


def make_success(payload: Any) -> Dict[str, Any]:
    """Build the canonical success envelope returned to the agent."""
    return {"ok": True, "result": payload}


def normalize_exception(exc: BaseException) -> Dict[str, Any]:
    """Map any exception raised during MCP dispatch to an error envelope.

    Order of checks matters: more specific exception types are tried
    first. ``httpx`` status errors are inspected for the HTTP code so
    401/403/429/4xx/5xx map cleanly. Everything that doesn't match a
    known shape becomes ``unknown`` and is logged with a stack trace
    so the unexplained-failure path is not silent.

    The MCP SDK runs network I/O under ``anyio``, which surfaces
    transport failures as ``ExceptionGroup`` / ``BaseExceptionGroup``
    (PEP 654). We unwrap those into their leaves and classify the most
    informative leaf, otherwise a real ``httpx.ConnectError`` would
    end up classified as ``unknown`` simply because the outer wrapper
    was an unrelated type.
    """
    leaves = _flatten_exception_group(exc)

    for leaf in leaves:
        if McpError is not None and isinstance(leaf, McpError):
            return _normalize_mcp_error(leaf)

    for leaf in leaves:
        if isinstance(leaf, httpx.TimeoutException):
            return make_envelope(
                kind=ERROR_KIND_TIMEOUT,
                message=f"MCP server did not respond in time: {leaf}",
                retryable=True,
                raw={"exc_type": type(leaf).__name__},
            )
        if isinstance(leaf, httpx.HTTPStatusError):
            return _normalize_http_status(leaf)
        if isinstance(leaf, (httpx.ConnectError, httpx.NetworkError, httpx.ProtocolError)):
            return make_envelope(
                kind=ERROR_KIND_NETWORK_ERROR,
                message=f"Could not reach MCP server: {leaf}",
                retryable=True,
                user_action_required="Check your internet connection, then try again.",
                raw={"exc_type": type(leaf).__name__},
            )

    primary = leaves[0] if leaves else exc
    logger.exception("Unhandled MCP dispatch exception (mapped to 'unknown')")
    return make_envelope(
        kind=ERROR_KIND_UNKNOWN,
        message=f"Unexpected MCP failure: {type(primary).__name__}: {primary}",
        retryable=False,
        raw={"exc_type": type(primary).__name__},
    )


def _flatten_exception_group(exc: BaseException) -> list:
    """Return a flat list of leaf exceptions from any nested ExceptionGroup.

    Falls back to ``[exc]`` on Python builds where ``BaseExceptionGroup``
    isn't available, or when ``exc`` is a plain exception.
    """
    base_eg = globals().get("BaseExceptionGroup", None)
    if base_eg is None:
        try:
            base_eg = BaseExceptionGroup  # type: ignore[name-defined]  # py>=3.11
        except NameError:
            base_eg = None
    if base_eg is not None and isinstance(exc, base_eg):
        out: list = []
        for sub in exc.exceptions:
            out.extend(_flatten_exception_group(sub))
        return out or [exc]
    return [exc]


def normalize_call_tool_result(result: Any) -> Dict[str, Any]:
    """Map a ``CallToolResult`` to a success envelope or an error envelope.

    The MCP spec lets servers signal a tool failure two ways: raise a
    JSON-RPC error (caught by ``normalize_exception``) or return a
    successful response with ``isError=True`` and a content block
    describing the failure. This helper handles the latter so the agent
    sees the same envelope shape regardless of which path the server
    took.
    """
    is_error = bool(getattr(result, "isError", False))
    content_blocks = getattr(result, "content", []) or []
    text_payload = "".join(getattr(b, "text", "") for b in content_blocks)
    structured = getattr(result, "structuredContent", None)

    if not is_error:
        return make_success(
            {
                "text": text_payload,
                "structured": structured,
            }
        )

    kind, action = _classify_tool_failure_text(text_payload)

    return make_envelope(
        kind=kind,
        message=text_payload or "Tool reported a failure.",
        retryable=kind in {ERROR_KIND_RATE_LIMITED, ERROR_KIND_SERVER_ERROR, ERROR_KIND_TIMEOUT},
        user_action_required=action,
        raw={"structured": structured},
    )


def _classify_tool_failure_text(text: str) -> tuple:
    """Bucket a server-returned failure message into one of the kinds.

    The server can express failures in arbitrary prose, so we use a
    short ordered list of phrase tests. Order matters: more specific
    phrases ("missing required argument") come before more general
    ones ("invalid"). Anything we don't recognize falls through to
    ``server_error``, which is the right default for "we don't know,
    but the server told us something went wrong."
    """
    if not text:
        return ERROR_KIND_SERVER_ERROR, None
    lower = text.lower()

    auth_phrases = ("unauthorized", "auth", "token", "expired", "invalid_token", "401")
    if any(p in lower for p in auth_phrases):
        return ERROR_KIND_AUTH_EXPIRED, "Reconnect this server in Settings → Connections."

    if "rate" in lower and "limit" in lower:
        return ERROR_KIND_RATE_LIMITED, None
    if "429" in lower:
        return ERROR_KIND_RATE_LIMITED, None

    permission_phrases = ("permission", "forbidden", "not allowed", "403")
    if any(p in lower for p in permission_phrases):
        return ERROR_KIND_PERMISSION_DENIED, None

    not_found_phrases = ("unknown tool", "no such tool", "tool not found", "not found", "no such")
    if any(p in lower for p in not_found_phrases):
        return ERROR_KIND_NOT_FOUND, None

    invalid_phrases = (
        "missing required argument",
        "missing argument",
        "validation error",
        "invalid argument",
        "invalid parameter",
        "missing parameter",
        "is required",
    )
    if any(p in lower for p in invalid_phrases):
        return ERROR_KIND_INVALID_ARGUMENTS, None

    if "timeout" in lower or "timed out" in lower:
        return ERROR_KIND_TIMEOUT, None

    return ERROR_KIND_SERVER_ERROR, None


def make_permission_denied(tool_name: str, reason: str) -> Dict[str, Any]:
    """Build the envelope returned when local policy refuses dispatch.

    Used by the ``external_catalog`` tool when a per-tool policy is
    ``never_allow`` or when the user denies an ``always_ask`` prompt.
    Kept here so the audit-log writer and the agent-facing tool both
    surface refusals identically.
    """
    return make_envelope(
        kind=ERROR_KIND_PERMISSION_DENIED,
        message=f"Local policy refused dispatch of '{tool_name}': {reason}",
        retryable=False,
        user_action_required=(
            "Adjust this tool's policy in Settings → Connections, "
            "or approve the request next time it is offered."
        ),
    )


def _normalize_mcp_error(exc: "McpError") -> Dict[str, Any]:
    """Map a JSON-RPC-level MCP error to the envelope.

    The JSON-RPC 2.0 reserved range is -32000..-32099 for server
    application errors; -32600..-32603 are the spec-defined parse /
    invalid-request / method-not-found / internal codes. MCP servers
    may layer their own application codes on top, so we treat anything
    we don't explicitly recognize as ``server_error``.
    """
    err = getattr(exc, "error", None)
    code = getattr(err, "code", 0) if err is not None else 0
    message = getattr(err, "message", str(exc)) if err is not None else str(exc)
    data = getattr(err, "data", None) if err is not None else None

    if mcp_types is not None:
        if code == getattr(mcp_types, "INVALID_PARAMS", -32602):
            return make_envelope(
                kind=ERROR_KIND_INVALID_ARGUMENTS,
                message=message,
                retryable=False,
                raw={"code": code, "data": data},
            )
        if code == getattr(mcp_types, "METHOD_NOT_FOUND", -32601):
            return make_envelope(
                kind=ERROR_KIND_NOT_FOUND,
                message=message,
                retryable=False,
                raw={"code": code, "data": data},
            )

    return make_envelope(
        kind=ERROR_KIND_SERVER_ERROR,
        message=message,
        retryable=False,
        raw={"code": code, "data": data},
    )


def _normalize_http_status(exc: httpx.HTTPStatusError) -> Dict[str, Any]:
    """Map HTTP status codes returned by the streamable transport.

    The MCP server uses regular HTTP for the SSE/streamable transport,
    so authentication failures, rate limits, and server errors arrive
    as ordinary status codes that we must classify before the agent
    sees them.
    """
    status = exc.response.status_code if exc.response is not None else 0
    body_excerpt = ""
    if exc.response is not None:
        try:
            body_excerpt = exc.response.text[:300]
        except Exception:
            body_excerpt = ""

    if status in (401, 407):
        return make_envelope(
            kind=ERROR_KIND_AUTH_EXPIRED,
            message=f"MCP server returned {status}: token rejected",
            retryable=False,
            user_action_required="Reconnect this server in Settings → Connections.",
            raw={"status": status, "body": body_excerpt},
        )
    if status == 403:
        return make_envelope(
            kind=ERROR_KIND_PERMISSION_DENIED,
            message=f"MCP server refused the request (HTTP 403): {body_excerpt}",
            retryable=False,
            raw={"status": status, "body": body_excerpt},
        )
    if status == 404:
        return make_envelope(
            kind=ERROR_KIND_NOT_FOUND,
            message=f"MCP endpoint not found (HTTP 404): {body_excerpt}",
            retryable=False,
            raw={"status": status, "body": body_excerpt},
        )
    if status == 429:
        return make_envelope(
            kind=ERROR_KIND_RATE_LIMITED,
            message=f"MCP server is rate-limiting requests (HTTP 429): {body_excerpt}",
            retryable=True,
            raw={"status": status, "body": body_excerpt},
        )
    if 500 <= status < 600:
        return make_envelope(
            kind=ERROR_KIND_SERVER_ERROR,
            message=f"MCP server error (HTTP {status}): {body_excerpt}",
            retryable=True,
            raw={"status": status, "body": body_excerpt},
        )
    return make_envelope(
        kind=ERROR_KIND_UNKNOWN,
        message=f"Unexpected HTTP status {status} from MCP server: {body_excerpt}",
        retryable=False,
        raw={"status": status, "body": body_excerpt},
    )
