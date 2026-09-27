"""Swift WebSocket bridge for MCP connection tokens.

Three responsibilities:

  * Push tokens to Swift after the backend completes an OAuth flow so
    they land in Keychain (``mcp_token_store``).
  * Ask Swift for the current access token (and optionally the
    refresh token) before dispatching an MCP tool call or running a
    refresh (``mcp_token_request`` -> ``mcp_token_response``).
  * Tell Swift to purge a connection's Keychain entries
    (``mcp_token_delete``).

The bundle-request path was added to support Slack PKCE refresh
rotation: Slack issues rotating user tokens, so Python sometimes
needs the refresh token to mint a new access token through the
Slack token endpoint without forcing the user to re-consent.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from api.services.websocket_connection_manager import broadcast_json_text

logger = logging.getLogger(__name__)

# Bounds how long the backend waits for the Swift client to answer an
# ``mcp_token_request`` before degrading. Mirrors AUTH_TOKEN_REQUEST_TIMEOUT_SECONDS
# (180s) used by model_service.py for the auth-token round-trip, so a stalled
# Keychain response can no longer park the coroutine until the executor's
# 20-minute cap.
MCP_TOKEN_REQUEST_TIMEOUT_SECONDS = 180.0

_token_response_waiters: dict[str, asyncio.Future] = {}
_token_request_contexts: dict[str, dict[str, Any]] = {}


@dataclass
class MCPTokenRequestOutcome:
    """Result of asking the Swift client for an MCP access token."""

    kind: str
    access_token: Optional[str] = None
    message: Optional[str] = None
    user_action_required: Optional[str] = None


@dataclass
class MCPTokenBundleOutcome:
    """Result of asking Swift for both access + refresh tokens.

    Used when Python needs the refresh token in order to rotate an
    access token (Slack PKCE) rather than just sign a single request.
    """

    kind: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    message: Optional[str] = None
    user_action_required: Optional[str] = None


async def _push_token_to_swift(
    *,
    connection_id: str,
    access_token: str,
    refresh_token: Optional[str],
    expires_in: Optional[int],
) -> None:
    payload = {
        "type": "mcp_token_store",
        "connection_id": connection_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
    }
    await _broadcast_to_active_connections(payload)


async def _push_token_delete_to_swift(connection_id: str) -> None:
    payload = {
        "type": "mcp_token_delete",
        "connection_id": connection_id,
    }
    await _broadcast_to_active_connections(payload)


async def _ask_swift_for_credentials(
    *,
    connection_id: str,
    timeout_s: Optional[float],
    agent_task_id: Optional[str],
    include_refresh_token: bool,
    cancel_event: Optional[Any] = None,
) -> Dict[str, Any]:
    """Round-trip a ``mcp_token_request`` to Swift and return the raw response.

    Returns a dict with at minimum ``kind`` (``token_available``,
    ``token_missing``, ``client_unavailable``, ``token_response_timeout``,
    ``token_request_cancelled``), plus ``access_token`` and (when
    requested) ``refresh_token``, and the user-facing ``message`` /
    ``user_action_required`` strings if the request failed.
    """
    correlation_id = f"mcp-token-req-{connection_id}-{int(datetime.utcnow().timestamp() * 1000)}"
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _token_response_waiters[correlation_id] = future
    _token_request_contexts[correlation_id] = {
        "agent_task_id": agent_task_id,
        "connection_id": connection_id,
    }

    payload: Dict[str, Any] = {
        "type": "mcp_token_request",
        "correlation_id": correlation_id,
        "connection_id": connection_id,
    }
    if include_refresh_token:
        payload["include_refresh_token"] = True

    try:
        if agent_task_id:
            await _broadcast_to_active_connections({
                "event_type": "agent_task_blocker_waiting",
                "agent_task_id": agent_task_id,
                "kind": "external_service_token",
                "message": "Waiting for Keychain access for an external service connection...",
                "connection_id": connection_id,
            })
        recipients = await _broadcast_to_active_connections(payload)
        logger.info(
            "mcp_token_request sent connection_id=%s correlation_id=%s recipients=%s include_refresh=%s",
            connection_id,
            correlation_id,
            recipients,
            include_refresh_token,
        )
        if recipients == 0:
            if agent_task_id:
                await _broadcast_to_active_connections({
                    "event_type": "agent_task_blocker_resolved",
                    "agent_task_id": agent_task_id,
                    "kind": "client_unavailable",
                    "message": "No Basil client is connected to provide the external service token.",
                    "connection_id": connection_id,
                })
            return {
                "kind": "client_unavailable",
                "message": "No Basil client is connected to provide the external service token.",
                "user_action_required": "Open Basil and try again.",
            }

        # Deferred import: pulling the agent_processing.shared package at module
        # load time would trigger its heavy __init__ cascade and risk a circular
        # import, since this low-level bridge is imported early during route setup.
        from api.services.agent_processing.shared.cancellable_wait import (
            await_future_with_cancellation,
        )

        wait_kind, response = await await_future_with_cancellation(
            future, timeout_s=timeout_s, cancel_event=cancel_event
        )
        if wait_kind == "timeout":
            logger.warning(
                "Swift client did not respond with MCP token for connection %s within %ss",
                connection_id,
                timeout_s,
            )
            if agent_task_id:
                await _broadcast_to_active_connections({
                    "event_type": "agent_task_blocker_resolved",
                    "agent_task_id": agent_task_id,
                    "kind": "token_response_timeout",
                    "message": "Timed out waiting for Keychain access for an external service connection.",
                    "connection_id": connection_id,
                })
            return {
                "kind": "token_response_timeout",
                "message": "Timed out waiting for the Basil client to provide the external service token.",
                "user_action_required": "Grant Keychain access, then retry.",
            }
        if wait_kind == "cancelled":
            logger.info(
                "MCP token request for connection %s cancelled before a response arrived",
                connection_id,
            )
            if agent_task_id:
                await _broadcast_to_active_connections({
                    "event_type": "agent_task_blocker_resolved",
                    "agent_task_id": agent_task_id,
                    "kind": "token_request_cancelled",
                    "message": "External service token request was cancelled.",
                    "connection_id": connection_id,
                })
            return {
                "kind": "token_request_cancelled",
                "message": "The external service token request was cancelled.",
            }
        access_token = response.get("access_token") if isinstance(response, dict) else response
        refresh_token = (
            response.get("refresh_token") if isinstance(response, dict) else None
        )
        if access_token:
            if agent_task_id:
                await _broadcast_to_active_connections({
                    "event_type": "agent_task_blocker_resolved",
                    "agent_task_id": agent_task_id,
                    "kind": "token_available",
                    "message": "External service access is available. Continuing...",
                    "connection_id": connection_id,
                })
            return {
                "kind": "token_available",
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
        if agent_task_id:
            await _broadcast_to_active_connections({
                "event_type": "agent_task_blocker_resolved",
                "agent_task_id": agent_task_id,
                "kind": "token_missing",
                "message": "Basil could not read this external service token from Keychain.",
                "connection_id": connection_id,
            })
        return {
            "kind": "token_missing",
            "access_token": None,
            "refresh_token": refresh_token,
            "message": "Basil could not read an access token for this connection from Keychain.",
            "user_action_required": (
                "Grant Keychain access or reconnect this service in "
                "Settings -> Connections."
            ),
        }
    except asyncio.CancelledError:
        # Task-level teardown (the outer ainvoke/cancel race or shutdown threw
        # CancelledError into this coroutine). Do NOT swallow it: re-raise so the
        # run actually aborts. Cooperative cancellation via ``cancel_event`` is
        # handled above and returns a clean outcome; this path is the hard stop.
        # We deliberately do not await a broadcast here because the surrounding
        # task is already being cancelled — the UI blocker is cleared by the
        # orchestrator's agent_task_cancelled event.
        raise
    finally:
        _token_response_waiters.pop(correlation_id, None)
        _token_request_contexts.pop(correlation_id, None)


async def _request_access_token_from_swift(
    connection_id: str,
    timeout_s: Optional[float] = MCP_TOKEN_REQUEST_TIMEOUT_SECONDS,
    agent_task_id: Optional[str] = None,
    cancel_event: Optional[Any] = None,
) -> MCPTokenRequestOutcome:
    """Ask the Swift client for the access token currently in Keychain.

    ``timeout_s`` defaults to :data:`MCP_TOKEN_REQUEST_TIMEOUT_SECONDS` so every
    caller (agent tools, Settings connection refresh, Slack refresh) is bounded;
    pass an explicit value to override. ``cancel_event`` lets an in-flight agent
    run abandon the wait promptly when the user cancels.
    """
    response = await _ask_swift_for_credentials(
        connection_id=connection_id,
        timeout_s=timeout_s,
        agent_task_id=agent_task_id,
        include_refresh_token=False,
        cancel_event=cancel_event,
    )
    return MCPTokenRequestOutcome(
        kind=response.get("kind", "token_missing"),
        access_token=response.get("access_token"),
        message=response.get("message"),
        user_action_required=response.get("user_action_required"),
    )


async def _request_token_bundle_from_swift(
    connection_id: str,
    timeout_s: Optional[float] = MCP_TOKEN_REQUEST_TIMEOUT_SECONDS,
    agent_task_id: Optional[str] = None,
    cancel_event: Optional[Any] = None,
) -> MCPTokenBundleOutcome:
    """Ask Swift for both the access and refresh tokens for a connection.

    Used by the Slack refresh path. Outcomes mirror
    :func:`_request_access_token_from_swift`; the bundle outcome
    carries the refresh token whenever Swift returned one, even on
    the ``token_missing`` path (so callers can still attempt refresh
    when the access slot is empty but the refresh slot is populated).
    """
    response = await _ask_swift_for_credentials(
        connection_id=connection_id,
        timeout_s=timeout_s,
        agent_task_id=agent_task_id,
        include_refresh_token=True,
        cancel_event=cancel_event,
    )
    return MCPTokenBundleOutcome(
        kind=response.get("kind", "token_missing"),
        access_token=response.get("access_token"),
        refresh_token=response.get("refresh_token"),
        message=response.get("message"),
        user_action_required=response.get("user_action_required"),
    )


def resolve_pending_token_response(
    correlation_id: str,
    access_token: Optional[str],
    refresh_token: Optional[str] = None,
) -> bool:
    """Resolve a pending token request from the WebSocket dispatcher.

    ``refresh_token`` is only populated for bundle requests; callers
    that only asked for the access token pass ``None`` and the
    consumer simply ignores the refresh slot.
    """
    future = _token_response_waiters.get(correlation_id)
    if future is None or future.done():
        return False
    future.set_result({
        "access_token": access_token,
        "refresh_token": refresh_token,
    })
    return True


async def broadcast_token_user_action_waiting(
    correlation_id: str,
    connection_id: Optional[str] = None,
    message: Optional[str] = None,
) -> bool:
    """Surface a Swift-side Keychain prompt as AgentTask user input."""
    context = _token_request_contexts.get(correlation_id)
    if not context:
        logger.warning(
            "mcp_token_user_action_waiting had no pending request for correlation_id=%s",
            correlation_id,
        )
        return False

    agent_task_id = context.get("agent_task_id")
    if not agent_task_id:
        return False

    connection_id = connection_id or context.get("connection_id")
    await _broadcast_to_active_connections({
        "event_type": "agent_task_blocker_waiting",
        "agent_task_id": agent_task_id,
        "kind": "external_service_token",
        "message": message or "Keychain access required",
        "connection_id": connection_id,
        "user_action_required": True,
    })
    return True


async def _broadcast_to_active_connections(payload: dict) -> int:
    """Send a JSON payload to every live websocket; tolerate per-connection errors."""
    return await broadcast_json_text(payload, log=logger)


__all__ = [
    "MCP_TOKEN_REQUEST_TIMEOUT_SECONDS",
    "MCPTokenBundleOutcome",
    "MCPTokenRequestOutcome",
    "_push_token_delete_to_swift",
    "_push_token_to_swift",
    "_request_access_token_from_swift",
    "_request_token_bundle_from_swift",
    "broadcast_token_user_action_waiting",
    "resolve_pending_token_response",
]
