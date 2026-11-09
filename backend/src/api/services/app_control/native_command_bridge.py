"""Sends one allowed command to the Mac app over the WebSocket and waits for its answer.

It follows the calendar and audio probe bridges: the backend sends an event with a request id, the Mac app does the work and posts the outcome to /app-control/native-command/result, and that resolves the waiting Future.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Mapping, Optional

from api.services.websocket_connection_manager import active_connections

from .native_commands import NativeCommandError, validate_native_command

logger = logging.getLogger(__name__)

NATIVE_COMMAND_TIMEOUT_SECONDS = 5.0

pending_native_commands: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}


def _failure(message: str) -> Dict[str, Any]:
    return {"ok": False, "error": message}


async def send_native_command(verb: str, params: Optional[Mapping[str, Any]] = None, timeout: float = NATIVE_COMMAND_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Validate and send a command, and return {"ok": True, ...} only when the Mac app reports it done."""
    try:
        verb, cleaned = validate_native_command(verb, params)
    except NativeCommandError as exc:
        return _failure(str(exc))
    if not active_connections:
        return _failure("The Basil app is not connected, so it could not be asked to do that.")

    request_id = str(uuid.uuid4())
    future: "asyncio.Future[Dict[str, Any]]" = asyncio.get_running_loop().create_future()
    pending_native_commands[request_id] = future
    event = {"event_type": "native_command", "request_id": request_id, "timestamp": int(time.time() * 1000), "verb": verb, "params": cleaned}
    sent = 0
    for connection in list(active_connections):
        try:
            await connection.send_json(event)
            sent += 1
        except Exception as exc:
            logger.warning("Could not send a native command to one connection: %s", exc)
    try:
        if sent == 0:
            return _failure("The command could not be delivered to the Basil app.")
        outcome = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        return _failure("The Basil app did not answer in time, so it is not known whether that happened.")
    finally:
        pending_native_commands.pop(request_id, None)
    if outcome.get("success") is True:
        return {"ok": True, "verb": verb, "params": cleaned}
    return _failure(str(outcome.get("error") or "The Basil app could not do that."))


def deliver_native_command_result(result: Mapping[str, Any]) -> bool:
    """Resolve the waiting command. Returns False for an unknown or already finished request."""
    request_id = result.get("request_id")
    future = pending_native_commands.get(request_id) if isinstance(request_id, str) else None
    if future is None or future.done():
        return False
    future.set_result(dict(result))
    return True
