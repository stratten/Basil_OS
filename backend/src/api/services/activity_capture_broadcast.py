"""Tell connected Basil clients that activity capture settings changed outside the Settings window."""

from __future__ import annotations

from api.services.websocket_connection_manager import broadcast_json_text


async def broadcast_activity_capture_updated() -> None:
    """Ask clients to re-read activity capture state so the menu item and status icon update live."""
    await broadcast_json_text({"event_type": "activity_capture_updated"})
