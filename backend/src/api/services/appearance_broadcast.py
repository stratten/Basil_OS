"""Broadcast appearance changes to connected Basil clients."""

from __future__ import annotations

from typing import Any, Dict

from api.services.websocket_connection_manager import broadcast_json_text

_appearance_revision = 0


def current_appearance_revision() -> int:
    """Return the process-local revision for appearance broadcasts."""
    return _appearance_revision


async def broadcast_appearance_update(appearance_settings: Dict[str, Any]) -> int:
    """Broadcast a complete appearance snapshot and return its revision."""
    global _appearance_revision

    _appearance_revision += 1
    await broadcast_json_text(
        {
            "event_type": "appearance_updated",
            "revision": _appearance_revision,
            "appearance_settings": appearance_settings,
        }
    )
    return _appearance_revision
