"""Send secret-bearing JSON only to the native app's websocket connections.

The websocket registry holds every connection, including connections authenticated with the webview credential. Provider keys and connector tokens must never reach a webview, so messages that carry or request secrets go through ``send_json_to_host_connections``, which skips every connection that was not authenticated with the host credential.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import WebSocket

from api.services.websocket_connection_manager import active_connections

logger = logging.getLogger(__name__)

# Mirrors ``api.core.security.backend_request_guard.CREDENTIAL_SCOPE_KEY``; a test asserts the two are equal.
CREDENTIAL_SCOPE_KEY = "basil.credential_type"
HOST_CREDENTIAL_TYPE = "host"


def is_host_connection(websocket: Any) -> bool:
    """Whether the connection was authenticated with the host (native app) credential."""
    scope = getattr(websocket, "scope", None)
    return isinstance(scope, dict) and scope.get(CREDENTIAL_SCOPE_KEY) == HOST_CREDENTIAL_TYPE


def host_connections() -> List[WebSocket]:
    return [websocket for websocket in list(active_connections) if is_host_connection(websocket)]


async def send_json_to_host_connections(payload: Dict[str, Any], *, log: logging.Logger | None = None) -> int:
    """Send a JSON text payload to every live host connection; returns how many received it. The payload is never logged."""
    event_logger = log or logger
    encoded = json.dumps(payload)
    sent = 0
    for websocket in host_connections():
        try:
            await websocket.send_text(encoded)
            sent += 1
        except Exception as exc:
            event_logger.warning("Failed to push a host-only websocket message to id=%s: %s", id(websocket), exc)
            active_connections.discard(websocket)
    return sent
