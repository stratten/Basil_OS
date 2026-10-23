"""Isolated validator and handler for `todo_workspace_message`."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

_MAX_SELECTION = 100
_MAX_TRANSCRIPT_MESSAGES = 20
_MAX_TRANSCRIPT_CHARS = 16000


async def handle_todo_workspace_message(websocket, msg_data: Dict[str, Any], *, turn_manager) -> None:
    workspace_id = _nonblank_str(msg_data.get("workspace_id"))
    request_id = _nonblank_str(msg_data.get("request_id"))
    message = _nonblank_str(msg_data.get("message"))
    selected_todo_ids = msg_data.get("selected_todo_ids")
    transcript = msg_data.get("transcript") or []
    reference_paths = msg_data.get("reference_paths", [])
    model_id = msg_data.get("model_id")

    validation_error = _validate(workspace_id, request_id, message, selected_todo_ids, reference_paths, transcript)
    if validation_error:
        await websocket.send_json({
            "event_type": "todo_workspace_error",
            "workspace_id": workspace_id,
            "request_id": request_id,
            "message": validation_error,
        })
        return

    try:
        result = await turn_manager.submit_turn(
            workspace_id=workspace_id, request_id=request_id, message=message,
            transcript=transcript, selected_todo_ids=selected_todo_ids, reference_paths=reference_paths, model_id=model_id,
        )
        await websocket.send_json({
            "event_type": "todo_workspace_accepted",
            "workspace_id": workspace_id,
            "request_id": request_id,
            "agent_task_id": result["agent_task_id"],
        })
    except Exception as exc:
        logger.error("To-Do workspace turn failed: %s", exc, exc_info=True)
        await websocket.send_json({
            "event_type": "todo_workspace_error",
            "workspace_id": workspace_id,
            "request_id": request_id,
            "message": str(exc),
        })


def _nonblank_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _validate(workspace_id, request_id, message, selected_todo_ids, reference_paths, transcript) -> str:
    if not workspace_id or not request_id or not message:
        return "workspace_id, request_id, and message must be nonblank"
    if not isinstance(selected_todo_ids, list) or len(selected_todo_ids) > _MAX_SELECTION:
        return f"selected_todo_ids must contain 0 to {_MAX_SELECTION} unique nonblank ids"
    if not all(isinstance(item, str) and item.strip() for item in selected_todo_ids):
        return "selected_todo_ids must contain only nonblank strings"
    if len(set(selected_todo_ids)) != len(selected_todo_ids):
        return "selected_todo_ids must not contain duplicates"
    if (
        not isinstance(reference_paths, list)
        or len(reference_paths) > _MAX_SELECTION
        or not all(isinstance(path, str) and path.strip() and os.path.isabs(path) for path in reference_paths)
        or len(set(reference_paths)) != len(reference_paths)
    ):
        return f"reference_paths must contain 0 to {_MAX_SELECTION} unique nonblank absolute paths"
    if not isinstance(transcript, list) or len(transcript) > _MAX_TRANSCRIPT_MESSAGES:
        return f"transcript must contain at most {_MAX_TRANSCRIPT_MESSAGES} messages"
    total_chars = 0
    for entry in transcript:
        if not isinstance(entry, dict) or entry.get("role") not in ("user", "assistant"):
            return "each transcript entry must have role 'user' or 'assistant'"
        content = entry.get("content")
        if not isinstance(content, str) or len(content) > 4000:
            return "each transcript entry's content must be a string of at most 4000 characters"
        total_chars += len(content)
    if total_chars > _MAX_TRANSCRIPT_CHARS:
        return f"aggregate transcript content must be at most {_MAX_TRANSCRIPT_CHARS} characters"
    return ""
