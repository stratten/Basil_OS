"""Auth, preference, and MCP client helpers for external_catalog."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_token_resolver_lock = asyncio.Lock()


def _get_run_token_cache(context: Dict[str, Any]) -> Dict[str, str]:
    cache = context.get("mcp_token_cache")
    if not isinstance(cache, dict):
        cache = {}
        context["mcp_token_cache"] = cache
    return cache


def invalidate_cached_access_token(connection_id: str) -> None:
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        context = get_current_agent_context()
        if isinstance(context, dict):
            cache = context.get("mcp_token_cache")
            if isinstance(cache, dict):
                cache.pop(connection_id, None)
    except Exception:
        return


def invalidate_cached_access_token_on_auth_error(connection_id: str, envelope: Dict[str, Any]) -> None:
    if envelope.get("ok") is not False:
        return
    error = envelope.get("error") or {}
    if error.get("kind") in {"auth_expired", "auth_unavailable"}:
        invalidate_cached_access_token(connection_id)


def record_connection_auth_rejection(connection_id: str, envelope: Dict[str, Any]) -> None:
    """Mark the connection as needing reconnect when the final dispatch result is still a rejected credential."""
    if envelope.get("ok") is not False:
        return
    error = envelope.get("error") or {}
    if error.get("kind") != "auth_expired":
        return
    try:
        from api.services.mcp_connectors.connection_status_service import (
            mark_connection_needs_reconnect,
        )

        mark_connection_needs_reconnect(
            connection_id,
            error.get("message") or "The server rejected this connection's credentials.",
        )
    except Exception as exc:
        logger.warning("Could not record reconnect status for %s: %s", connection_id, exc)


async def resolve_external_catalog_access_token(connection_id: str):
    """Ask the Swift client (via the WebSocket bridge) for the token.

    Returns an explicit token outcome so callers never need to make an
    unauthenticated request just to discover token retrieval failed.
    """
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
        from api.services.mcp_connectors.swift_token_bridge import (
            MCPTokenRequestOutcome,
            _request_access_token_from_swift,
        )

        context = get_current_agent_context()
        agent_task_id = context.get("agent_task_id")
        # Same per-task cancellation Event the executor's ainvoke race watches;
        # passing it lets a stalled Keychain wait abandon promptly on user cancel
        # instead of parking until the token round-trip's 180s timeout.
        cancel_event = context.get("cancel_event") if isinstance(context, dict) else None
        token_cache = _get_run_token_cache(context) if isinstance(context, dict) else {}
        cached_token = token_cache.get(connection_id)
        if cached_token:
            return MCPTokenRequestOutcome(kind="token_available", access_token=cached_token)

        async with _token_resolver_lock:
            cached_token = token_cache.get(connection_id)
            if cached_token:
                return MCPTokenRequestOutcome(kind="token_available", access_token=cached_token)

            outcome = await _request_access_token_from_swift(
                connection_id,
                agent_task_id=agent_task_id,
                cancel_event=cancel_event,
            )
            if getattr(outcome, "access_token", None):
                token_cache[connection_id] = outcome.access_token
            return outcome
    except Exception as exc:
        logger.warning("Could not resolve access token for %s: %s", connection_id, exc)
        try:
            return MCPTokenRequestOutcome(
                kind="token_resolution_error",
                message=f"Could not resolve access token: {exc}",
                user_action_required="Try again or reconnect this service in Settings → Connections.",
            )
        except Exception:
            class _FallbackOutcome:
                kind = "token_resolution_error"
                access_token = None
                message = f"Could not resolve access token: {exc}"
                user_action_required = "Try again or reconnect this service in Settings → Connections."
            return _FallbackOutcome()


def get_external_catalog_mcp_client():
    """Return the process-shared MCP client.

    Imported lazily so this module stays importable in tests that
    don't bring up the full agent stack.
    """
    from api.services.mcp_connectors.mcp_client_service import MCPClientService

    global _shared_client
    try:
        return _shared_client  # type: ignore[name-defined]
    except NameError:
        pass
    _shared_client = MCPClientService()
    return _shared_client


def load_external_catalog_preferences():
    from api.core.models.preferences import Preferences

    return Preferences.load()


def find_external_catalog_connection(prefs, connection_id: str):
    for r in prefs.connections.mcp_connections:
        if r.id == connection_id:
            return r
    return None


def default_external_catalog_policy_for_tool(record, tool_name: str) -> str:
    """Default read-only tools to auto-allow; ask for mutating/unknown tools."""
    for tool in record.cached_tools:
        if tool.name == tool_name:
            return "always_allow" if tool.is_read_only_hint else "always_ask"
    return "always_ask"


async def try_slack_refresh_and_retry(
    *,
    record,
    envelope: Dict[str, Any],
    redo: Callable[[str], Awaitable[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Refresh a Slack PKCE token once after auth_expired, then retry.

    The MCP client deliberately stays stateless and token-agnostic. This
    catalog layer knows the connection id and can therefore ask the Swift
    Keychain bridge for the Slack refresh token, rotate through Slack, and
    repeat the original dispatch once with the new access token.
    """
    if envelope.get("ok") is not False:
        return None
    error = envelope.get("error") or {}
    if error.get("kind") not in {"auth_expired", "auth_unavailable"}:
        return None

    try:
        from api.services.mcp_connectors.slack_local_server import LOCAL_SLACK_SENTINEL_URL
        from api.services.mcp_connectors.slack_pkce_coordinator import (
            SLACK_MCP_SERVER_URL,
            SlackPKCECoordinator,
        )
        from api.services.mcp_connectors.slack_token_service import refresh_slack_token
    except Exception as exc:
        logger.warning("Slack refresh support unavailable: %s", exc)
        return None

    raw_url = (getattr(record, "server_url", "") or "").rstrip("/")
    if raw_url not in {LOCAL_SLACK_SENTINEL_URL.rstrip("/"), SLACK_MCP_SERVER_URL.rstrip("/")}:
        return None

    agent_task_id = None
    try:
        from api.services.agent_processing.shared.agent_runtime_context import (
            get_current_agent_context,
        )

        context = get_current_agent_context()
        agent_task_id = context.get("agent_task_id") if isinstance(context, dict) else None
    except Exception:
        context = {}

    outcome = await refresh_slack_token(
        connection_id=record.id,
        coordinator=SlackPKCECoordinator(),
        agent_task_id=agent_task_id,
    )
    if outcome.kind != "refreshed" or not outcome.access_token:
        logger.info(
            "Slack token refresh did not produce a retryable token for %s: kind=%s code=%s message=%s",
            record.id,
            outcome.kind,
            outcome.error_code,
            outcome.message,
        )
        return None

    if isinstance(context, dict):
        token_cache = _get_run_token_cache(context)
        token_cache[record.id] = outcome.access_token

    logger.info("Slack token refreshed for %s; retrying external_catalog dispatch once", record.id)
    retry_envelope = await redo(outcome.access_token)
    invalidate_cached_access_token_on_auth_error(record.id, retry_envelope)
    return retry_envelope


async def try_generic_oauth_refresh_and_retry(
    *,
    record,
    envelope: Dict[str, Any],
    redo: Callable[[str], Awaitable[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Refresh a generic (non-Slack) OAuth token once after auth_expired, then retry.

    Mirrors ``try_slack_refresh_and_retry`` exactly, but for connections that
    went through dynamic client registration or a static OAuth app (Linear,
    GitHub, etc.) rather than Slack's PKCE flow. ``refresh_generic_oauth_access_token``
    is safe to call unconditionally - it is a no-op (returns ``None``) for a
    Slack connection - so this function never needs to pre-check the connection
    kind itself.
    """
    if envelope.get("ok") is not False:
        return None
    error = envelope.get("error") or {}
    if error.get("kind") not in {"auth_expired", "auth_unavailable"}:
        return None

    try:
        from api.services.mcp_connectors.generic_oauth_token_refresh import (
            refresh_generic_oauth_access_token,
        )
    except Exception as exc:
        logger.warning("Generic OAuth refresh support unavailable: %s", exc)
        return None

    agent_task_id = None
    cancel_event = None
    try:
        from api.services.agent_processing.shared.agent_runtime_context import (
            get_current_agent_context,
        )

        context = get_current_agent_context()
        if isinstance(context, dict):
            agent_task_id = context.get("agent_task_id")
            cancel_event = context.get("cancel_event")
    except Exception:
        context = {}

    new_token = await refresh_generic_oauth_access_token(
        record,
        agent_task_id=agent_task_id,
        cancel_event=cancel_event,
    )
    if not new_token:
        logger.info("Generic OAuth refresh did not produce a retryable token for %s", record.id)
        return None

    if isinstance(context, dict):
        token_cache = _get_run_token_cache(context)
        token_cache[record.id] = new_token

    logger.info(
        "Generic OAuth token refreshed for %s; retrying external_catalog dispatch once",
        record.id,
    )
    retry_envelope = await redo(new_token)
    invalidate_cached_access_token_on_auth_error(record.id, retry_envelope)
    return retry_envelope
