"""JSON envelope helpers for external_catalog responses."""

from __future__ import annotations

import json
from typing import Any, Dict


def make_external_catalog_invalid_arguments(message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "kind": "invalid_arguments",
            "message": message,
            "retryable": False,
            "user_action_required": None,
            "raw": {},
        },
    }


def make_external_catalog_schema_required(
    tool_name: str,
    connection_id: str,
    input_schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Corrective envelope: the model must see the tool's parameter schema first.

    Returned by the dispatcher's schema-surfacing guard when a parameterized
    tool is called before its input schema has been surfaced this run. It is a
    self-correcting handshake, not a dispatch failure: the ``input_schema`` is
    carried in ``raw`` so the model can re-issue ``action='call_tool'`` with
    valid arguments, and ``retryable`` is ``True`` because the immediate retry
    is expected to proceed.
    """
    return {
        "ok": False,
        "error": {
            "kind": "schema_required",
            "message": (
                f"Before calling '{tool_name}', inspect its parameter schema (provided in "
                "raw.input_schema) and re-issue action='call_tool' with arguments valid "
                "against it. Prefer the most specific structured parameter you hold a value "
                "for over free-text search."
            ),
            "retryable": True,
            "user_action_required": None,
            "raw": {
                "connection_id": connection_id,
                "tool_name": tool_name,
                "input_schema": input_schema,
            },
        },
    }


def make_external_catalog_auth_unavailable(token_outcome) -> Dict[str, Any]:
    """Return an accurate auth blocker without calling the remote MCP server."""
    kind = getattr(token_outcome, "kind", "auth_unavailable")
    message = getattr(token_outcome, "message", None) or "Basil could not retrieve credentials for this external service."
    action = getattr(token_outcome, "user_action_required", None)
    return {
        "ok": False,
        "error": {
            "kind": "auth_unavailable" if kind in {"token_missing", "client_unavailable", "token_response_timeout", "token_request_cancelled", "token_resolution_error"} else kind,
            "message": message,
            "retryable": kind in {"client_unavailable", "token_response_timeout", "token_request_cancelled", "token_resolution_error"},
            "user_action_required": action,
            "raw": {"token_outcome": kind},
        },
    }


def make_external_catalog_not_found(message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "kind": "not_found",
            "message": message,
            "retryable": False,
            "user_action_required": None,
            "raw": {},
        },
    }


def make_external_catalog_permission_denied(tool_name: str, reason: str) -> Dict[str, Any]:
    """Inline envelope to avoid dragging error_normalizer's import path
    into this hot module; same shape as
    ``error_normalizer.make_permission_denied``."""
    return {
        "ok": False,
        "error": {
            "kind": "permission_denied",
            "message": f"Local policy refused dispatch of '{tool_name}': {reason}",
            "retryable": False,
            "user_action_required": (
                "Adjust this tool's policy in Settings → Connections, "
                "or approve the request next time it is offered."
            ),
            "raw": {},
        },
    }


def encode_external_catalog_envelope(envelope: Dict[str, Any]) -> str:
    """JSON-encode an envelope for return to LangChain."""
    return json.dumps(envelope, ensure_ascii=False)
