"""Ask the Basil app to collect a connection token from the user in Paprika's overlay, so the token never passes through chat or the model.

Wire protocol:

* ``connection_secret_request`` is sent to the app on the host connection and also broadcast to the current agent task. It carries ``request_id``, ``server_url``, ``host``, ``friendly_name`` and ``description`` (both prefilled suggestions the user can edit), ``existing_names`` (the names of connections already saved, so the overlay can refuse a duplicate name) and ``already_connected_as`` (the name of a connection that already uses this address, or null). The payload never includes a token.
* ``connection_secret_result`` (app to backend, host connection only) carries the same ``request_id`` and a ``status`` of ``connected``, ``canceled`` or ``failed``. A ``connected`` result adds ``connection_id``, ``tool_count`` and the ``friendly_name`` and ``description`` the user settled on; a ``failed`` result adds ``message``. The result never carries the token.
* ``connection_secret_cancel`` closes the overlay when the agent stops waiting.

The app registers the connection, stores the token in its Keychain vault and checks it by fetching the service's tool list before it answers, so a ``connected`` status means the service accepted the token.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from urllib.parse import urlparse

from api.services.host_connection_channel import send_json_to_host_connections

logger = logging.getLogger(__name__)

REQUEST_TYPE = "connection_secret_request"
RESULT_TYPE = "connection_secret_result"
CANCEL_TYPE = "connection_secret_cancel"

WAIT_TIMEOUT_SECONDS = 600.0
MAX_MESSAGE_CHARACTERS = 300
MAX_NAME_CHARACTERS = 80
MAX_DESCRIPTION_CHARACTERS = 500
VALID_STATUSES = frozenset({"connected", "canceled", "failed"})

NOT_CONNECTED_MESSAGE = "The Basil app is not connected, so it cannot show the token form. Add the connection in Settings, then Connections instead."
TIMED_OUT_MESSAGE = "The token form was left open without an answer. Ask the user whether they still want to connect, then try again."

_waiters: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}
_overlay_targets: Dict[str, Dict[str, Any]] = {}


def handle_connection_secret_result(message: Dict[str, Any]) -> bool:
    """Resolve the waiter for a ``connection_secret_result``. The caller must only pass messages received on a host connection. Returns whether a waiter was resolved."""
    request_id = message.get("request_id")
    if not isinstance(request_id, str):
        return False
    future = _waiters.get(request_id)
    if future is None or future.done():
        return False
    future.set_result(message)
    return True


def _clean_text(value: Any, limit: int) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()[:limit]
    return None


def _clean_outcome(raw: Dict[str, Any]) -> Dict[str, Any]:
    status = raw.get("status")
    outcome: Dict[str, Any] = {"status": status if status in VALID_STATUSES else "failed"}
    if outcome["status"] == "connected":
        connection_id = raw.get("connection_id")
        outcome["connection_id"] = connection_id if isinstance(connection_id, str) else None
        tool_count = raw.get("tool_count")
        outcome["tool_count"] = tool_count if isinstance(tool_count, int) and tool_count >= 0 else None
        outcome["friendly_name"] = _clean_text(raw.get("friendly_name"), MAX_NAME_CHARACTERS)
        outcome["description"] = _clean_text(raw.get("description"), MAX_DESCRIPTION_CHARACTERS)
    message = _clean_text(raw.get("message"), MAX_MESSAGE_CHARACTERS)
    if message:
        outcome["message"] = message
    elif outcome["status"] == "failed":
        outcome["message"] = "The Basil app could not finish the connection."
    return outcome


async def request_token_entry(
    *,
    server_url: str,
    friendly_name: str,
    description: Optional[str] = None,
    existing_names: Optional[List[str]] = None,
    already_connected_as: Optional[str] = None,
    timeout: float = WAIT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Show the token form in Paprika and wait for the user's answer. The returned outcome never contains the token."""
    request_id = uuid.uuid4().hex
    future: "asyncio.Future[Dict[str, Any]]" = asyncio.get_running_loop().create_future()
    _waiters[request_id] = future
    try:
        payload = {
            "type": REQUEST_TYPE,
            "request_id": request_id,
            "server_url": server_url,
            "host": urlparse(server_url).hostname or server_url,
            "friendly_name": friendly_name,
            "description": description,
            "existing_names": list(existing_names or []),
            "already_connected_as": already_connected_as,
        }
        sent = await send_json_to_host_connections(payload)
        if sent == 0:
            return {"status": "failed", "message": NOT_CONNECTED_MESSAGE}
        await _publish_agent_overlay(request_id, payload)
        await _record_token_connect_asked(request_id, payload)
        try:
            reply = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            await send_json_to_host_connections({"type": CANCEL_TYPE, "request_id": request_id})
            await _publish_agent_overlay_cancel(request_id)
            timed_out = {"status": "failed", "message": TIMED_OUT_MESSAGE}
            await _record_token_connect_resolved(request_id, timed_out)
            return timed_out
        outcome = _clean_outcome(reply)
        await _record_token_connect_resolved(request_id, outcome)
        return outcome
    finally:
        _waiters.pop(request_id, None)
        _overlay_targets.pop(request_id, None)


async def _publish_agent_overlay(request_id: str, payload: Dict[str, Any]) -> None:
    """Show the token form inside the current Paprika overlay, the same way command approval does. The payload has no token."""
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        context = get_current_agent_context()
        manager = context.get("websocket_manager")
        agent_task_id = context.get("agent_task_id")
        if manager is None or not isinstance(agent_task_id, str) or not agent_task_id.strip():
            return
        _overlay_targets[request_id] = {"websocket_manager": manager, "agent_task_id": agent_task_id}
        await manager.broadcast({
            **payload,
            "event_type": REQUEST_TYPE,
            "agent_task_id": agent_task_id,
        })
    except Exception:
        logger.exception("Could not show the token form in the agent window")


async def _publish_agent_overlay_cancel(request_id: str) -> None:
    """Hide the token form when the agent stops waiting."""
    target = _overlay_targets.get(request_id)
    if not target:
        return
    try:
        await target["websocket_manager"].broadcast({
            "event_type": CANCEL_TYPE,
            "type": CANCEL_TYPE,
            "request_id": request_id,
            "agent_task_id": target["agent_task_id"],
        })
    except Exception:
        logger.exception("Could not hide the token form in the agent window")


def _exchange_prompt(payload: Dict[str, Any]) -> str:
    name = payload.get("friendly_name") or payload.get("host") or "this service"
    host = payload.get("host")
    server_url = payload.get("server_url")
    parts = [f"Connect {name}" + (f" at {host}" if host else "") + "."]
    if server_url:
        parts.append(f"Basil will send the token only to {server_url}.")
    already = payload.get("already_connected_as")
    if already:
        parts.append(f"You already have {already} connected at this address. This adds a second connection.")
    return " ".join(str(part) for part in parts)


def _exchange_resolution(outcome: Dict[str, Any]) -> tuple[str, Optional[str]]:
    status = outcome.get("status")
    if status == "connected":
        name = outcome.get("friendly_name") or "The service"
        tool_count = outcome.get("tool_count")
        if isinstance(tool_count, int):
            return "approved", f"{name} is connected. The service accepted the token ({tool_count} tools)."
        return "approved", f"{name} is connected. The service accepted the token."
    if status == "canceled":
        return "dismissed", None
    message = outcome.get("message")
    if message == TIMED_OUT_MESSAGE:
        return "timed_out", None
    if isinstance(message, str) and message.strip():
        return "resolved", message.strip()[:MAX_MESSAGE_CHARACTERS]
    return "resolved", "The connection could not be completed."


def _agent_exchange_target() -> Optional[Dict[str, Any]]:
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        context = get_current_agent_context()
    except Exception:
        return None
    manager = context.get("websocket_manager")
    agent_task_id = context.get("agent_task_id")
    if manager is None or not isinstance(agent_task_id, str) or not agent_task_id.strip():
        return None
    return {"websocket_manager": manager, "agent_task_id": agent_task_id}


async def _record_token_connect_asked(request_id: str, payload: Dict[str, Any]) -> None:
    """Leave a durable ask in the task thread, the same way command approval does. The prompt never includes a token."""
    target = _agent_exchange_target()
    if not target:
        return
    try:
        from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import record_user_interaction_asked

        await record_user_interaction_asked(
            target["agent_task_id"],
            interaction_id=request_id,
            kind="connection_token",
            prompt=_exchange_prompt(payload),
            broadcast=target["websocket_manager"].broadcast,
        )
    except Exception:
        logger.exception("Could not record the token-connect request in the task thread")


async def _record_token_connect_resolved(request_id: str, outcome: Dict[str, Any]) -> None:
    """Update the thread with whether the user entered a token and whether the service accepted it. Never stores the token."""
    target = _agent_exchange_target()
    if not target:
        return
    status, response = _exchange_resolution(outcome)
    try:
        from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import record_user_interaction_resolved

        await record_user_interaction_resolved(
            target["agent_task_id"],
            interaction_id=request_id,
            status=status,
            response=response,
            broadcast=target["websocket_manager"].broadcast,
        )
    except Exception:
        logger.exception("Could not record the token-connect result in the task thread")


def pending_request_count() -> int:
    """Number of token forms still waiting for an answer (used by tests)."""
    return len(_waiters)
