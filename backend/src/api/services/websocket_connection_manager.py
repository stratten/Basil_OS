"""Shared WebSocket connection registry and broadcast helpers."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Store active connections for backend services that need to broadcast events.
active_connections: Set[WebSocket] = set()

# Connections that asked for backend liveness heartbeats; the native client never subscribes, so its generic logger stays quiet.
heartbeat_subscribers: Set[WebSocket] = set()


def add_connection(websocket: WebSocket) -> None:
    active_connections.add(websocket)
    logger.info(
        f"[CONNECTIONS] Client connected: id={id(websocket)}. "
        f"Total active: {len(active_connections)}"
    )


def subscribe_heartbeat(websocket: WebSocket) -> None:
    if websocket in active_connections:
        heartbeat_subscribers.add(websocket)


def remove_connection(websocket: WebSocket) -> None:
    heartbeat_subscribers.discard(websocket)
    if websocket in active_connections:
        active_connections.remove(websocket)
        logger.info(
            f"[CONNECTIONS] Client disconnected: id={id(websocket)}. "
            f"Total active: {len(active_connections)}"
        )


async def broadcast_json_text(payload: Dict[str, Any], *, log: logging.Logger | None = None) -> int:
    """Send a JSON text payload to every live websocket connection."""
    event_logger = log or logger
    encoded = json.dumps(payload)
    dead = []
    sent = 0
    for websocket in list(active_connections):
        try:
            await websocket.send_text(encoded)
            sent += 1
        except Exception as exc:
            event_logger.warning(
                "Failed to push websocket message to id=%s: %s",
                id(websocket),
                exc,
            )
            dead.append(websocket)
    for websocket in dead:
        active_connections.discard(websocket)
    return sent


async def broadcast_heartbeat(payload: Dict[str, Any], *, log: logging.Logger | None = None) -> int:
    """Send a liveness heartbeat to the connections that subscribed to it."""
    event_logger = log or logger
    encoded = json.dumps(payload)
    sent = 0
    for websocket in list(heartbeat_subscribers):
        try:
            await websocket.send_text(encoded)
            sent += 1
        except Exception as exc:
            event_logger.debug("Heartbeat send failed for id=%s: %s", id(websocket), exc)
            heartbeat_subscribers.discard(websocket)
            active_connections.discard(websocket)
    return sent
