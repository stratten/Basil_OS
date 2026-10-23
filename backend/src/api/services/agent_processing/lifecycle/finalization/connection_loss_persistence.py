"""Save a run that lost its model connection as ``paused``, keeping its conversation so it resumes where it stopped."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..execution_graph.agent_loop_connection import CONNECTION_LOST_PROMPT
from .user_pause_persistence import save_paused_run

CONNECTION_LOST_REASON = "connection_lost"


async def handle_connection_loss_pause(
    checkpoint_err: Any,
    state: Any,
    coordinator: Any,
    thinking_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    original = getattr(checkpoint_err, "original_error", None)
    loss: Dict[str, Any] = {
        "error": str(original)[:500] if original is not None else "",
        "model": str(getattr(checkpoint_err, "model_label", "") or ""),
        "waited_seconds": round(float(getattr(checkpoint_err, "waited_seconds", 0.0) or 0.0)),
        "interrupted_at": datetime.now(timezone.utc).isoformat(),
    }
    return await save_paused_run(
        checkpoint_err,
        state,
        coordinator,
        thinking_history,
        interaction_kind="connection_lost",
        default_prompt=CONNECTION_LOST_PROMPT,
        pause_markers={"paused_for_connection_loss": True, "connection_loss": loss},
        event_extras={"reason": CONNECTION_LOST_REASON},
        event_message="Connection lost",
        log_label="connection loss pause",
    )
