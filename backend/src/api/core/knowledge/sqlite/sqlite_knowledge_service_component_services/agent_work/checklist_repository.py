"""Durable checklist items, references, and step logs for one agent work session."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, Iterable, List, Optional

from ..infrastructure.connection import get_sync_connection, run_in_worker_thread
from .checklist_records import (
    CARRYABLE_CHECKLIST_STATUSES,
    EDITABLE_ITEM_FIELDS,
    MAX_DETAIL_CHARS,
    MAX_EVENT_TEXT_CHARS,
    MAX_EVENTS_PER_ITEM,
    MAX_ITEM_NOTE_CHARS,
    MAX_ITEMS_PER_SESSION,
    MAX_REFS_PER_ITEM,
    MAX_TITLE_CHARS,
    MAX_WAITING_ON_CHARS,
    clip,
    counts_from_rows,
    normalize_actor,
    normalize_ref,
    normalize_status,
    optional_text,
    row_to_event,
    row_to_item,
    row_to_ref,
)

_SQL_CHUNK = 400


def _chunks(values: List[str]) -> Iterable[List[str]]:
    for start in range(0, len(values), _SQL_CHUNK):
        yield values[start:start + _SQL_CHUNK]


def _ensure_checklist_row(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO agent_checklists (session_id) VALUES (?)", (session_id,))


def _touch(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE agent_checklists SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?", (session_id,))
    conn.execute("UPDATE agent_work_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))


def _add_event(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    session_id: str,
    agent_task_id: Optional[str],
    kind: str,
    actor: str,
    text: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO agent_checklist_events (id, item_id, session_id, agent_task_id, kind, actor, text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), item_id, session_id, agent_task_id, kind, actor, clip(text, MAX_EVENT_TEXT_CHARS)),
    )
    conn.execute(
        """
        DELETE FROM agent_checklist_events
        WHERE item_id = ? AND rowid NOT IN (
            SELECT rowid FROM agent_checklist_events WHERE item_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?
        )
        """,
        (item_id, item_id, MAX_EVENTS_PER_ITEM),
    )


def _load_items(conn: sqlite3.Connection, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    items = [row_to_item(row) for row in rows]
    by_id = {item["id"]: item for item in items}
    for chunk in _chunks(list(by_id)):
        marks = ",".join("?" * len(chunk))
        for ref_row in conn.execute(
            f"SELECT * FROM agent_checklist_refs WHERE item_id IN ({marks}) ORDER BY created_at, rowid", chunk
        ).fetchall():
            by_id[ref_row["item_id"]]["refs"].append(row_to_ref(ref_row))
    return items


def _load_one(conn: sqlite3.Connection, session_id: str, item_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM agent_checklist_items WHERE id = ? AND session_id = ?", (item_id, session_id)
    ).fetchone()
    return _load_items(conn, [row])[0] if row else None


def _find_item_by_ref(conn: sqlite3.Connection, session_id: str, ref: Dict[str, str]) -> Optional[str]:
    row = conn.execute(
        """
        SELECT i.id FROM agent_checklist_refs r JOIN agent_checklist_items i ON i.id = r.item_id
        WHERE i.session_id = ? AND r.ref_kind = ? AND r.source_system = ? AND r.source_scope = ? AND r.external_id = ?
        LIMIT 1
        """,
        (session_id, ref["ref_kind"], ref["source_system"], ref["source_scope"], ref["external_id"]),
    ).fetchone()
    return row["id"] if row else None


def _insert_ref(conn: sqlite3.Connection, item_id: str, ref: Dict[str, str]) -> bool:
    count = conn.execute("SELECT COUNT(*) AS n FROM agent_checklist_refs WHERE item_id = ?", (item_id,)).fetchone()["n"]
    if count >= MAX_REFS_PER_ITEM:
        return False
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO agent_checklist_refs (
            id, item_id, role, ref_kind, source_system, source_scope, external_id, label, open_url, added_by,
            last_known_status, last_known_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = '' THEN NULL ELSE CURRENT_TIMESTAMP END)
        """,
        (
            str(uuid.uuid4()), item_id, ref["role"], ref["ref_kind"], ref["source_system"], ref["source_scope"],
            ref["external_id"], ref["label"], ref["open_url"], ref["added_by"], ref["last_known_status"],
            ref["last_known_status"],
        ),
    )
    return cursor.rowcount > 0


def _link_work_item(conn: sqlite3.Connection, session_id: str, item_id: str, ref: Dict[str, str]) -> None:
    """Point the item at the captured evidence row with the same external id, when capture saw one."""
    row = conn.execute(
        "SELECT id FROM agent_work_items WHERE session_id = ? AND external_id = ? LIMIT 1",
        (session_id, ref["external_id"]),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE agent_checklist_items SET work_item_id = ? WHERE id = ? AND work_item_id IS NULL",
            (row["id"], item_id),
        )


class AgentChecklistRepository:
    """Items, references, and step logs. Notes live in AgentChecklistNotesRepository."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @run_in_worker_thread
    def add_item(self, **fields: Any) -> Dict[str, Any]:
        """Add one item (arguments of _add_item_blocking) or return the existing item that shares a reference."""
        return self._add_item_blocking(**fields)

    def _add_item_blocking(
        self,
        *,
        session_id: str,
        title: str,
        origin: str = "agent",
        detail: str = "",
        status: str = "pending",
        required: bool = False,
        note: str = "",
        waiting_on: str = "",
        recheck_at: Optional[str] = None,
        refs: Optional[List[Dict[str, Any]]] = None,
        agent_task_id: Optional[str] = None,
        actor: Optional[str] = None,
        carried_from_item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_title = clip(title, MAX_TITLE_CHARS)
        if not clean_title:
            raise ValueError("title is required")
        item_status = normalize_status(status)
        item_actor = normalize_actor(actor or ("user" if origin == "user" else "agent"))
        clean_refs = [normalize_ref(raw, added_by=item_actor) for raw in (refs or [])][:MAX_REFS_PER_ITEM]
        with get_sync_connection(self.db_path) as conn:
            _ensure_checklist_row(conn, session_id)
            for ref in clean_refs:
                existing_id = _find_item_by_ref(conn, session_id, ref)
                if existing_id:
                    return {"created": False, "duplicate": True, "item": _load_one(conn, session_id, existing_id)}
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM agent_checklist_items WHERE session_id = ?", (session_id,)
            ).fetchone()["n"]
            if total >= MAX_ITEMS_PER_SESSION:
                return {
                    "created": False,
                    "rejected": f"The checklist already has {total} items, which is the limit. Archive or drop finished items first.",
                }
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM agent_checklist_items WHERE session_id = ?",
                (session_id,),
            ).fetchone()["n"]
            item_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO agent_checklist_items (
                    id, session_id, origin, title, detail, status, required, note, waiting_on, recheck_at,
                    sort_order, carried_from_item_id, created_by_task_id, updated_by_task_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id, session_id, origin if origin in ("agent", "user", "carried") else "agent", clean_title,
                    clip(detail, MAX_DETAIL_CHARS), item_status, 1 if required else 0, clip(note, MAX_ITEM_NOTE_CHARS),
                    clip(waiting_on, MAX_WAITING_ON_CHARS), optional_text(recheck_at), next_order,
                    carried_from_item_id, agent_task_id, agent_task_id,
                ),
            )
            for ref in clean_refs:
                _insert_ref(conn, item_id, ref)
                _link_work_item(conn, session_id, item_id, ref)
            conn.execute("UPDATE agent_checklists SET closed_at = NULL WHERE session_id = ?", (session_id,))
            _add_event(
                conn, item_id=item_id, session_id=session_id, agent_task_id=agent_task_id,
                kind="carried" if origin == "carried" else "added", actor=item_actor, text=clean_title,
            )
            _touch(conn, session_id)
            conn.commit()
            return {"created": True, "item": _load_one(conn, session_id, item_id)}

    @run_in_worker_thread
    def update_item(
        self,
        *,
        session_id: str,
        item_id: str,
        changes: Dict[str, Any],
        expected_revision: Optional[int] = None,
        actor: Optional[str] = None,
        agent_task_id: Optional[str] = None,
        event_text: str = "",
    ) -> Optional[Dict[str, Any]]:
        item_actor = normalize_actor(actor)
        with get_sync_connection(self.db_path) as conn:
            current = _load_one(conn, session_id, item_id)
            if current is None:
                return None
            if expected_revision is not None and int(expected_revision) != current["revision"]:
                return {"conflict": True, "current": current}
            sets: Dict[str, Any] = {}
            for field in EDITABLE_ITEM_FIELDS:
                if field not in changes:
                    continue
                value = changes[field]
                if field == "status":
                    value = normalize_status(value)
                elif field == "title":
                    value = clip(value, MAX_TITLE_CHARS)
                    if not value:
                        raise ValueError("title cannot be empty")
                elif field == "detail":
                    value = clip(value, MAX_DETAIL_CHARS)
                elif field == "note":
                    value = clip(value, MAX_ITEM_NOTE_CHARS)
                elif field == "waiting_on":
                    value = clip(value, MAX_WAITING_ON_CHARS)
                elif field == "required":
                    value = 1 if value else 0
                elif field == "recheck_at":
                    value = optional_text(value)
                elif field == "sort_order":
                    value = int(value)
                if value != (int(current[field]) if field == "required" else current[field]):
                    sets[field] = value
            status_after = sets.get("status", current["status"])
            if status_after not in ("waiting_user", "waiting_external") and "waiting_on" not in changes and current["waiting_on"]:
                sets["waiting_on"] = ""
            if not sets:
                return {"item": current, "changed": False}
            assignments = ", ".join(f"{field} = ?" for field in sets)
            conn.execute(
                f"""
                UPDATE agent_checklist_items
                SET {assignments}, revision = revision + 1, updated_at = CURRENT_TIMESTAMP,
                    updated_by_task_id = COALESCE(?, updated_by_task_id)
                WHERE id = ? AND session_id = ?
                """,
                [*sets.values(), agent_task_id if item_actor == "agent" else None, item_id, session_id],
            )
            if "status" in sets:
                kind, text = "status", f"{current['status']} to {sets['status']}"
            elif set(sets) == {"note"}:
                kind, text = "note", sets["note"]
            else:
                kind, text = "edited", ", ".join(sorted(sets))
            if event_text:
                text = f"{text}: {event_text}"
            _add_event(
                conn, item_id=item_id, session_id=session_id, agent_task_id=agent_task_id,
                kind=kind, actor=item_actor, text=text,
            )
            if sets.get("status") in ("pending", "in_progress", "waiting_user", "waiting_external"):
                conn.execute("UPDATE agent_checklists SET closed_at = NULL WHERE session_id = ?", (session_id,))
            _touch(conn, session_id)
            conn.commit()
            return {"item": _load_one(conn, session_id, item_id), "changed": True}

    @run_in_worker_thread
    def set_archived(
        self,
        *,
        session_id: str,
        item_id: str,
        archived: bool,
        actor: Optional[str] = None,
        agent_task_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with get_sync_connection(self.db_path) as conn:
            if _load_one(conn, session_id, item_id) is None:
                return None
            conn.execute(
                """
                UPDATE agent_checklist_items
                SET archived_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                    revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND session_id = ?
                """,
                (1 if archived else 0, item_id, session_id),
            )
            _add_event(
                conn, item_id=item_id, session_id=session_id, agent_task_id=agent_task_id,
                kind="archived" if archived else "restored", actor=normalize_actor(actor),
            )
            _touch(conn, session_id)
            conn.commit()
            return _load_one(conn, session_id, item_id)

    @run_in_worker_thread
    def add_ref(
        self,
        *,
        session_id: str,
        item_id: str,
        ref: Dict[str, Any],
        added_by: str = "agent",
        agent_task_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        clean = normalize_ref(ref, added_by=added_by)
        with get_sync_connection(self.db_path) as conn:
            if _load_one(conn, session_id, item_id) is None:
                return None
            if _insert_ref(conn, item_id, clean):
                _link_work_item(conn, session_id, item_id, clean)
                conn.execute(
                    "UPDATE agent_checklist_items SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (item_id,),
                )
                _add_event(
                    conn, item_id=item_id, session_id=session_id, agent_task_id=agent_task_id, kind="ref_added",
                    actor=normalize_actor(added_by), text=clean["label"] or clean["external_id"],
                )
                _touch(conn, session_id)
                conn.commit()
            return _load_one(conn, session_id, item_id)

    @run_in_worker_thread
    def list_items(
        self,
        session_id: str,
        *,
        include_archived: bool = False,
        statuses: Optional[List[str]] = None,
        limit: int = MAX_ITEMS_PER_SESSION,
    ) -> List[Dict[str, Any]]:
        clauses, params = ["session_id = ?"], [session_id]
        if not include_archived:
            clauses.append("archived_at IS NULL")
        if statuses:
            clauses.append(f"status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM agent_checklist_items WHERE {' AND '.join(clauses)} ORDER BY sort_order, created_at, rowid LIMIT ?",
                [*params, max(1, min(int(limit), MAX_ITEMS_PER_SESSION))],
            ).fetchall()
            return _load_items(conn, rows)

    @run_in_worker_thread
    def get_item(self, session_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        with get_sync_connection(self.db_path) as conn:
            return _load_one(conn, session_id, item_id)

    @run_in_worker_thread
    def find_items(
        self,
        session_id: str,
        *,
        external_id: Optional[str] = None,
        ref_kind: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        clauses, params = ["i.session_id = ?"], [session_id]
        if external_id:
            clauses.append("EXISTS (SELECT 1 FROM agent_checklist_refs r WHERE r.item_id = i.id AND r.external_id = ?"
                           + (" AND r.ref_kind = ?)" if ref_kind else ")"))
            params.append(clip(external_id, 300))
            if ref_kind:
                params.append(clip(ref_kind, 60))
        if query:
            escaped = clip(query, 80).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("i.title LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT i.* FROM agent_checklist_items i WHERE {' AND '.join(clauses)} ORDER BY i.sort_order, i.rowid LIMIT ?",
                [*params, max(1, min(int(limit), 50))],
            ).fetchall()
            return _load_items(conn, rows)

    @run_in_worker_thread
    def add_item_event(
        self,
        *,
        session_id: str,
        item_id: str,
        kind: str,
        actor: Optional[str] = None,
        text: str = "",
        agent_task_id: Optional[str] = None,
    ) -> bool:
        """Append one entry to an item's step log without changing the item. False when the item is not in this session."""
        with get_sync_connection(self.db_path) as conn:
            if _load_one(conn, session_id, item_id) is None:
                return False
            _add_event(
                conn, item_id=item_id, session_id=session_id, agent_task_id=agent_task_id,
                kind=clip(kind, 40) or "note", actor=normalize_actor(actor), text=text,
            )
            conn.commit()
            return True

    @run_in_worker_thread
    def list_events(self, session_id: str, item_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT rowid AS rid, * FROM agent_checklist_events WHERE session_id = ? AND item_id = ?
                    ORDER BY created_at DESC, rowid DESC LIMIT ?
                ) ORDER BY created_at, rid
                """,
                (session_id, item_id, max(1, min(int(limit), MAX_EVENTS_PER_ITEM))),
            ).fetchall()
            return [row_to_event(row) for row in rows]

    @run_in_worker_thread
    def last_actor_by_item(self, session_id: str) -> Dict[str, str]:
        """Who made the latest logged change to each item, so the model can be told about edits the user made."""
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT e.item_id AS item_id, e.actor AS actor FROM agent_checklist_events e
                WHERE e.session_id = ?
                  AND e.rowid = (SELECT MAX(x.rowid) FROM agent_checklist_events x WHERE x.item_id = e.item_id)
                """,
                (session_id,),
            ).fetchall()
        return {row["item_id"]: row["actor"] for row in rows}

    @run_in_worker_thread
    def get_state(self, session_id: str) -> Dict[str, Any]:
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM agent_checklists WHERE session_id = ?", (session_id,)).fetchone()
            counted = conn.execute(
                "SELECT status, required FROM agent_checklist_items WHERE session_id = ? AND archived_at IS NULL",
                (session_id,),
            ).fetchall()
        return {
            "session_id": session_id,
            "exists": row is not None,
            "closed_at": row["closed_at"] if row else None,
            "counts": counts_from_rows(counted),
        }

    @run_in_worker_thread
    def set_closed(self, session_id: str, closed: bool) -> Dict[str, Any]:
        with get_sync_connection(self.db_path) as conn:
            _ensure_checklist_row(conn, session_id)
            conn.execute(
                "UPDATE agent_checklists SET closed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END WHERE session_id = ?",
                (1 if closed else 0, session_id),
            )
            _touch(conn, session_id)
            conn.commit()
            row = conn.execute("SELECT closed_at FROM agent_checklists WHERE session_id = ?", (session_id,)).fetchone()
        return {"closed_at": row["closed_at"]}

    @run_in_worker_thread
    def counts_for_roots(self, root_task_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Counter summary per chain root, for the sidebar. Roots without a checklist are absent."""
        grouped: Dict[str, List[sqlite3.Row]] = {}
        unique_roots = [root for root in dict.fromkeys(root_task_ids) if root]
        with get_sync_connection(self.db_path) as conn:
            for chunk in _chunks(unique_roots):
                marks = ",".join("?" * len(chunk))
                for row in conn.execute(
                    f"""
                    SELECT s.root_task_id AS root_task_id, i.status AS status, i.required AS required
                    FROM agent_checklist_items i JOIN agent_work_sessions s ON s.id = i.session_id
                    WHERE s.root_task_id IN ({marks}) AND i.archived_at IS NULL
                    """,
                    chunk,
                ).fetchall():
                    grouped.setdefault(row["root_task_id"], []).append(row)
        summaries = {root: counts_from_rows(rows) for root, rows in grouped.items()}
        return {root: counts for root, counts in summaries.items() if counts["total"] > 0}

    @run_in_worker_thread
    def copy_carryable_items(
        self,
        *,
        from_session_id: str,
        to_session_id: str,
        agent_task_id: Optional[str] = None,
    ) -> int:
        """Copy open and waiting items into another session as carried items. Safe to call twice."""
        marks = ",".join("?" * len(CARRYABLE_CHECKLIST_STATUSES))
        with get_sync_connection(self.db_path) as conn:
            source_rows = conn.execute(
                f"""
                SELECT * FROM agent_checklist_items
                WHERE session_id = ? AND archived_at IS NULL AND status IN ({marks})
                ORDER BY sort_order, rowid
                """,
                [from_session_id, *CARRYABLE_CHECKLIST_STATUSES],
            ).fetchall()
            sources = _load_items(conn, source_rows)
            already = {
                row["carried_from_item_id"]
                for row in conn.execute(
                    "SELECT carried_from_item_id FROM agent_checklist_items WHERE session_id = ? AND carried_from_item_id IS NOT NULL",
                    (to_session_id,),
                ).fetchall()
            }
        copied = 0
        for source in sources:
            if source["id"] in already:
                continue
            result = self._add_item_blocking(
                session_id=to_session_id,
                title=source["title"],
                origin="carried",
                detail=source["detail"],
                status=source["status"],
                required=source["required"],
                note=source["note"],
                waiting_on=source["waiting_on"],
                recheck_at=source["recheck_at"],
                refs=[{**ref, "added_by": ref["added_by"]} for ref in source["refs"]],
                agent_task_id=agent_task_id,
                actor="system",
                carried_from_item_id=source["id"],
            )
            copied += 1 if result.get("created") else 0
        return copied
