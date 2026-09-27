"""Compatibility imports for the shared WebSocket connection registry."""

from api.services.websocket_connection_manager import (
    active_connections,
    add_connection,
    remove_connection,
)

__all__ = ["active_connections", "add_connection", "remove_connection"]