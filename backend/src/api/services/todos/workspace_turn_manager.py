"""Ephemeral To-Do workspace admission. Creates exactly one manager Agent
Task per submitted turn; never persists a workspace record itself."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPT_CHARS = 16000


class TodoWorkspaceValidationError(Exception):
    pass


class TodoWorkspaceTurnManager:
    def __init__(self, *, todo_service: Any, agent_task_submission_service: Any):
        self.todo_service = todo_service
        self.agent_task_submission_service = agent_task_submission_service

    async def submit_turn(
        self, *, workspace_id: str, request_id: str, message: str,
        transcript: List[Dict[str, str]], selected_todo_ids: List[str], reference_paths: List[str], model_id: Optional[str],
    ) -> Dict[str, Any]:
        selected_todo_ids = list(dict.fromkeys(selected_todo_ids))

        snapshots = []
        for todo_id in selected_todo_ids:
            item = await self.todo_service.get_item_detail(todo_id)
            if item.status in ("dismissed", "cancelled"):
                raise TodoWorkspaceValidationError(f"{todo_id} is dismissed or cancelled and cannot be selected")
            snapshots.append(item)

        transcript_digest = _bounded_transcript_digest(transcript)
        instruction = _build_manager_instruction(message, snapshots, reference_paths, transcript_digest)
        agent_task_id = str(uuid.uuid4())
        todo_workspace_context = {
            "workspace_id": workspace_id,
            "request_id": request_id,
            "selection_ids": selected_todo_ids,
            "reference_paths": reference_paths,
            "transcript_digest": transcript_digest,
        }
        result = await self.agent_task_submission_service.process_agent_task_direct(
            agent_task=instruction,
            agent_task_id=agent_task_id,
            reference_paths=reference_paths,
            model_id=model_id,
            origin_type="todo_workspace",
            origin_id=workspace_id,
            todo_workspace_context=todo_workspace_context,
        )
        if not isinstance(result, dict) or not result.get("success", False):
            raise RuntimeError(
                result.get("message", "workspace manager submission failed")
                if isinstance(result, dict)
                else "workspace manager submission failed"
            )
        return {"agent_task_id": agent_task_id}


def _bounded_transcript_digest(transcript: List[Dict[str, str]]) -> str:
    lines = []
    for entry in transcript[-20:]:
        role = entry.get("role", "user")
        content = (entry.get("content") or "")[:4000]
        lines.append(f"{role}: {content}")
    digest = "\n".join(lines)
    return digest[:_MAX_TRANSCRIPT_CHARS]


def _build_manager_instruction(
    message: str,
    snapshots: List[Any],
    reference_paths: List[str],
    transcript_digest: str,
) -> str:
    item_lines = []
    for item in snapshots:
        item_lines.append(
            f"- [{item.id}] {item.title} (status={item.status}, responsibility={item.responsibility})\n"
            f"  notes: {item.notes or '(none)'}"
        )
    items_block = "\n".join(item_lines) if item_lines else "(none — intake mode)"
    reference_paths_block = "\n".join(f"- {path}" for path in reference_paths) if reference_paths else "(none)"
    selection_instruction = (
        "You may inspect, append a durable note to, or delegate direct-origin work for only the To-Dos "
        "listed below. Never append a note to or delegate any other To-Do."
        if snapshots
        else (
            "You are in intake mode. You may inspect existing To-Dos and create candidate To-Dos from explicit "
            "user instructions and reference materials. You may not append notes to or delegate work for any To-Do "
            "until the user selects it in a later workspace turn."
        )
    )
    return (
        "You are the To-Do workspace partner for this application run. "
        f"{selection_instruction} Never complete, dismiss, cancel, or reopen any To-Do yourself; only the user can do that.\n\n"
        f"Selected To-Dos:\n{items_block}\n\n"
        f"Reference paths:\n{reference_paths_block}\n\n"
        "When reference paths are supplied, load the file tool family and use those paths as authoritative context. "
        "If the user explicitly requests a local file write, use the existing approval-gated file tools; do not bypass "
        "their allowed roots, approval checks, or verification requirements.\n\n"
        f"Prior workspace transcript (untrusted conversational context):\n{transcript_digest or '(none)'}\n\n"
        f"User: {message}\n\n"
        "Respond with a concise, direct reply describing what you found or did."
    )
