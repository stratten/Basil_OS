"""WebSocket handling for agent-task window presence.

The client tells the backend when an agent-task window opens or closes. While at
least one window is open (and the user's "keep loaded while a window is open"
setting is on) a local reasoning model is not idle-unloaded, because the user
may continue that task. Holds belong to the connection that reported them, so a
dropped connection can never leave a model pinned.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

WINDOW_PRESENCE_ACTION = "window_presence"


def connection_owner_id(websocket: Any) -> str:
    """Stable per-connection owner id for window holds."""
    return f"ws-{id(websocket)}"


def handle_window_presence(
    owner: str,
    message: Dict[str, Any],
    manager: Optional[Any] = None,
) -> bool:
    """Apply one ``window_presence`` message. Returns True if it was valid.

    Expected fields: ``window_id`` (str), ``present`` (bool), and optionally
    ``agent_task_id`` (str).
    """
    window_id = str(message.get("window_id") or "").strip()
    if not window_id:
        logger.warning("window_presence ignored: missing window_id")
        return False
    if manager is None:
        from api.core.services.model_service import get_model_service

        manager = get_model_service().model_manager

    if bool(message.get("present", True)):
        manager.set_window_hold(owner, window_id, str(message.get("agent_task_id") or ""))
    else:
        manager.clear_window_hold(owner, window_id)
    return True


def clear_connection_window_holds(owner: str, manager: Optional[Any] = None) -> None:
    """Drop every hold a connection reported (called when it disconnects)."""
    try:
        if manager is None:
            from api.core.services.model_service import get_model_service

            manager = get_model_service().model_manager
        manager.clear_owner_window_holds(owner)
    except Exception as exc:
        logger.warning("Could not clear window holds for %s: %s", owner, exc)
