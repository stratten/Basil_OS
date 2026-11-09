"""The capped working-notes document that belongs to one agent checklist."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Dict, Optional

from ..infrastructure.connection import get_sync_connection, run_in_worker_thread
from .checklist_records import MAX_NOTES_CHARS, normalize_actor


def _row_to_notes(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if row is None:
        return {"content": "", "revision": 0, "updated_by": None, "updated_at": None, "carried_from_task_id": None}
    return {
        "content": row["notes_content"],
        "revision": row["notes_revision"],
        "updated_by": row["notes_updated_by"],
        "updated_at": row["notes_updated_at"],
        "carried_from_task_id": row["notes_carried_from_task_id"],
    }


class AgentChecklistNotesRepository:
    """Read, append, edit, and replace the notes document with a revision check and a hard size cap."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @run_in_worker_thread
    def get_notes(self, session_id: str) -> Dict[str, Any]:
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM agent_checklists WHERE session_id = ?", (session_id,)).fetchone()
        return _row_to_notes(row)

    def _write(
        self,
        session_id: str,
        build: Callable[[str], Dict[str, Any]],
        *,
        actor: Optional[str],
        expected_revision: Optional[int],
        max_chars: int,
        carried_from_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply build(current_content) -> {"content": str} or {"error": str} under one transaction."""
        with get_sync_connection(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO agent_checklists (session_id) VALUES (?)", (session_id,))
            current = _row_to_notes(
                conn.execute("SELECT * FROM agent_checklists WHERE session_id = ?", (session_id,)).fetchone()
            )
            if expected_revision is not None and int(expected_revision) != current["revision"]:
                return {"ok": False, "conflict": True, "current": current}
            built = build(current["content"])
            if "error" in built:
                return {"ok": False, "error": built["error"], "current": current}
            content = built["content"]
            # A shrinking edit is always allowed so that carried or hand-edited text can be brought back under the cap.
            if len(content) > max_chars and len(content) >= len(current["content"]):
                return {
                    "ok": False,
                    "rejected": "over_limit",
                    "size": len(current["content"]),
                    "limit": max_chars,
                    "error": (
                        f"The notes hold {len(current['content'])} of {max_chars} characters. "
                        "Condense them with an edit (notes are the current state, not a history) and try again."
                    ),
                    "current": current,
                }
            if content == current["content"]:
                return {"ok": True, "changed": False, "notes": current}
            conn.execute(
                """
                UPDATE agent_checklists
                SET notes_content = ?, notes_revision = notes_revision + 1, notes_updated_by = ?,
                    notes_updated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                    notes_carried_from_task_id = COALESCE(?, notes_carried_from_task_id)
                WHERE session_id = ?
                """,
                (content, normalize_actor(actor), carried_from_task_id, session_id),
            )
            conn.execute("UPDATE agent_work_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM agent_checklists WHERE session_id = ?", (session_id,)).fetchone()
        return {"ok": True, "changed": True, "notes": _row_to_notes(row)}

    @run_in_worker_thread
    def append_notes(
        self,
        session_id: str,
        text: str,
        *,
        actor: Optional[str] = None,
        expected_revision: Optional[int] = None,
        max_chars: int = MAX_NOTES_CHARS,
    ) -> Dict[str, Any]:
        addition = str(text or "").strip()
        if not addition:
            return {"ok": False, "error": "text is required"}

        def build(content: str) -> Dict[str, Any]:
            return {"content": f"{content}\n{addition}" if content else addition}

        return self._write(session_id, build, actor=actor, expected_revision=expected_revision, max_chars=max_chars)

    @run_in_worker_thread
    def edit_notes(
        self,
        session_id: str,
        find: str,
        replace: str,
        *,
        actor: Optional[str] = None,
        expected_revision: Optional[int] = None,
        max_chars: int = MAX_NOTES_CHARS,
    ) -> Dict[str, Any]:
        needle = str(find or "")
        if not needle:
            return {"ok": False, "error": "find is required"}

        def build(content: str) -> Dict[str, Any]:
            occurrences = content.count(needle)
            if occurrences == 0:
                return {"error": "The text to replace was not found in the notes. Read the notes again and copy it exactly."}
            if occurrences > 1:
                return {"error": f"The text to replace appears {occurrences} times. Include more surrounding text so it is unique."}
            return {"content": content.replace(needle, str(replace or ""), 1).strip()}

        return self._write(session_id, build, actor=actor, expected_revision=expected_revision, max_chars=max_chars)

    @run_in_worker_thread
    def set_notes(
        self,
        session_id: str,
        content: str,
        *,
        actor: Optional[str] = None,
        expected_revision: Optional[int] = None,
        max_chars: int = MAX_NOTES_CHARS,
        carried_from_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        replacement = str(content or "").strip()
        return self._write(
            session_id,
            lambda _current: {"content": replacement},
            actor=actor,
            expected_revision=expected_revision,
            max_chars=max_chars,
            carried_from_task_id=carried_from_task_id,
        )
