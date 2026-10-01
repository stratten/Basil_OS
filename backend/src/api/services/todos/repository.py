"""Sole owner of `todo_*` SQL. Every public method runs one explicit
transaction inside `asyncio.to_thread`."""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ...core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from .models import TodoItemDetail, TodoItemSummary, TodoSource, TodoWorkspaceHydration
from .records import row_to_todo_detail, row_to_todo_source, row_to_todo_summary

DEFAULT_TODO_WORKSPACE_PAGE_LIMIT = 50
MAX_TODO_WORKSPACE_PAGE_LIMIT = 200
_TODO_STATUSES = frozenset({
    "candidate", "open", "in_progress", "ready_for_review", "completed", "dismissed", "canceled",
})


class TodoRevisionConflict(Exception):
    """Raised when an optimistic-concurrency update targets a stale revision."""

    def __init__(self, todo_id: str):
        super().__init__(f"Revision conflict for To-Do {todo_id}")
        self.todo_id = todo_id


class TodoIdempotencyConflict(Exception):
    """Raised when a repeated idempotency key carries a different payload hash."""

    def __init__(self, idempotency_key: str):
        super().__init__(f"Idempotency key {idempotency_key} already used with a different payload")
        self.idempotency_key = idempotency_key


class TodoReferenceNotFound(Exception):
    """Raised when a reference does not belong to the requested To-Do."""

    def __init__(self, todo_id: str, reference_id: str):
        super().__init__(f"Reference {reference_id} was not found on To-Do {todo_id}")
        self.todo_id = todo_id
        self.reference_id = reference_id


class TodoWorkspaceCursorError(ValueError):
    """Raised when a workspace pagination cursor cannot be safely applied."""

    def __init__(self) -> None:
        super().__init__("Invalid To-Do workspace cursor")


class TodoRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    # === Create ===

    async def create_todo_item_with_source(
        self,
        *,
        title: str,
        description: str,
        notes: str,
        responsibility: str,
        priority: str,
        due_at: Optional[str],
        status: str,
        created_by_kind: str,
        created_by_id: Optional[str],
        idempotency_key: Optional[str],
        idempotency_payload_hash: Optional[str],
        source_kind: Optional[str],
        source_id: Optional[str],
        source_locator: Optional[Dict[str, Any]],
        source_excerpt: str,
    ) -> Tuple[TodoItemDetail, bool]:
        """Create an item and its optional source in one transaction.

        Returns `(detail, created)`. `created=False` means an existing row
        (matched by idempotency key or unique source identity) was returned
        instead of inserting a duplicate.
        """
        return await asyncio.to_thread(
            self._create_todo_item_with_source_sync,
            title=title,
            description=description,
            notes=notes,
            responsibility=responsibility,
            priority=priority,
            due_at=due_at,
            status=status,
            created_by_kind=created_by_kind,
            created_by_id=created_by_id,
            idempotency_key=idempotency_key,
            idempotency_payload_hash=idempotency_payload_hash,
            source_kind=source_kind,
            source_id=source_id,
            source_locator=source_locator,
            source_excerpt=source_excerpt,
        )

    def _create_todo_item_with_source_sync(
        self,
        *,
        title: str,
        description: str,
        notes: str,
        responsibility: str,
        priority: str,
        due_at: Optional[str],
        status: str,
        created_by_kind: str,
        created_by_id: Optional[str],
        idempotency_key: Optional[str],
        idempotency_payload_hash: Optional[str],
        source_kind: Optional[str],
        source_id: Optional[str],
        source_locator: Optional[Dict[str, Any]],
        source_excerpt: str,
    ) -> Tuple[TodoItemDetail, bool]:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if source_kind and source_id:
                existing_source = conn.execute(
                    "SELECT todo_id FROM todo_sources WHERE source_kind = ? AND source_id = ?",
                    (source_kind, source_id),
                ).fetchone()
                if existing_source is not None:
                    detail = self._get_todo_item_detail_sync_locked(conn, existing_source["todo_id"])
                    conn.commit()
                    return detail, False
            if idempotency_key:
                existing_item = conn.execute(
                    "SELECT id, idempotency_payload_hash FROM todo_items WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing_item is not None:
                    if existing_item["idempotency_payload_hash"] != idempotency_payload_hash:
                        conn.rollback()
                        raise TodoIdempotencyConflict(idempotency_key)
                    detail = self._get_todo_item_detail_sync_locked(conn, existing_item["id"])
                    conn.commit()
                    return detail, False

            todo_id = str(uuid.uuid4())
            now = _utc_now_iso()
            conn.execute(
                """
                INSERT INTO todo_items (
                    id, title, description, notes, status, responsibility, priority,
                    due_at, idempotency_key, idempotency_payload_hash, revision,
                    created_by_kind, created_by_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    todo_id, title, description, notes, status, responsibility, priority,
                    due_at, idempotency_key, idempotency_payload_hash,
                    created_by_kind, created_by_id, now, now,
                ),
            )
            if source_kind and source_id:
                conn.execute(
                    """
                    INSERT INTO todo_sources (
                        id, todo_id, source_kind, source_id, source_locator_json,
                        source_excerpt, created_by_kind, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), todo_id, source_kind, source_id,
                        json.dumps(source_locator or {}), source_excerpt, created_by_kind, now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO todo_events (id, todo_id, event_kind, actor_kind, actor_id, payload_json, created_at)
                VALUES (?, ?, 'created', ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), todo_id, created_by_kind, created_by_id, json.dumps({"status": status}), now),
            )
            detail = self._get_todo_item_detail_sync_locked(conn, todo_id)
            conn.commit()
            return detail, True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # === Read ===

    async def list_todo_item_summaries(
        self, *, status: Optional[str], limit: int, cursor: Optional[str], sort_by: str = "created_at",
    ) -> Tuple[List[TodoItemSummary], Optional[str]]:
        return await asyncio.to_thread(
            self._list_todo_item_summaries_sync,
            status=status,
            limit=limit,
            cursor=cursor,
            sort_by=sort_by,
        )

    def _list_todo_item_summaries_sync(
        self, *, status: Optional[str], limit: int, cursor: Optional[str], sort_by: str,
    ) -> Tuple[List[TodoItemSummary], Optional[str]]:
        sort_column = _todo_sort_column(sort_by)
        conn = self._connection()
        try:
            clauses = []
            params: List[Any] = []
            if status:
                clauses.append("status = ?")
                params.append(status)
            if cursor:
                clauses.append(f"{sort_column} < ?")
                params.append(cursor)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM todo_items {where} ORDER BY {sort_column} DESC, id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            next_cursor = str(page_rows[-1][sort_column]) if has_more and page_rows else None
            return [row_to_todo_summary(row) for row in page_rows], next_cursor
        finally:
            conn.close()

    async def get_todo_workspace_hydration(
        self,
        *,
        query: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        limit: int = DEFAULT_TODO_WORKSPACE_PAGE_LIMIT,
        cursor: Optional[str] = None,
        sort_by: str = "created_at",
        sort_direction: Optional[str] = None,
    ) -> TodoWorkspaceHydration:
        if limit < 1 or limit > MAX_TODO_WORKSPACE_PAGE_LIMIT:
            raise ValueError(
                f"To-Do workspace page limit must be between 1 and {MAX_TODO_WORKSPACE_PAGE_LIMIT}"
            )
        return await asyncio.to_thread(
            self._get_todo_workspace_hydration_sync,
            query=query,
            statuses=statuses,
            limit=limit,
            cursor=cursor,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    def _get_todo_workspace_hydration_sync(
        self,
        *,
        query: Optional[str],
        statuses: Optional[List[str]],
        limit: int,
        cursor: Optional[str],
        sort_by: str,
        sort_direction: Optional[str],
    ) -> TodoWorkspaceHydration:
        normalized_query = query.strip() if query else ""
        normalized_statuses = _normalize_workspace_statuses(statuses)
        resolved_direction = _resolve_todo_sort_direction(sort_by, sort_direction)
        page_cursor = _decode_todo_workspace_cursor(cursor)
        if page_cursor is not None:
            _validate_todo_workspace_cursor(
                page_cursor,
                sort_by=sort_by,
                sort_direction=resolved_direction,
                query=normalized_query,
                statuses=normalized_statuses,
            )

        conditions: List[str] = []
        params: List[Any] = []
        if normalized_query:
            conditions.append("title LIKE ? ESCAPE '\\' COLLATE NOCASE")
            params.append(f"%{_escape_sql_like_literal(normalized_query)}%")
        if normalized_statuses:
            placeholders = ", ".join("?" for _ in normalized_statuses)
            conditions.append(f"status IN ({placeholders})")
            params.extend(normalized_statuses)
        if page_cursor is not None:
            cursor_clause, cursor_params = _todo_workspace_cursor_clause(
                sort_by=sort_by,
                sort_direction=resolved_direction,
                sort_value=page_cursor["sort_value"],
                todo_id=page_cursor["id"],
            )
            conditions.append(cursor_clause)
            params.extend(cursor_params)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_by = _todo_order_by_clause(sort_by, resolved_direction)
        conn = self._connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM todo_items {where} ORDER BY {order_by} LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            counts = conn.execute(
                "SELECT status, COUNT(*) AS n FROM todo_items GROUP BY status"
            ).fetchall()
            page_rows = rows[:limit]
            has_more = len(rows) > limit
            next_cursor = None
            if has_more and page_rows:
                next_cursor = _encode_todo_workspace_cursor(
                    sort_by=sort_by,
                    sort_direction=resolved_direction,
                    query=normalized_query,
                    statuses=normalized_statuses,
                    sort_value=_todo_workspace_sort_value(page_rows[-1], sort_by),
                    todo_id=page_rows[-1]["id"],
                )
            return TodoWorkspaceHydration(
                items=[row_to_todo_summary(row) for row in page_rows],
                next_cursor=next_cursor,
                has_more=has_more,
                counts_by_status={row["status"]: row["n"] for row in counts},
            )
        finally:
            conn.close()

    async def get_todo_item_detail(self, todo_id: str) -> Optional[TodoItemDetail]:
        return await asyncio.to_thread(self._get_todo_item_detail_sync, todo_id)

    def _get_todo_item_detail_sync(self, todo_id: str) -> Optional[TodoItemDetail]:
        conn = self._connection()
        try:
            item_row = conn.execute("SELECT * FROM todo_items WHERE id = ?", (todo_id,)).fetchone()
            if item_row is None:
                return None
            source_rows = conn.execute(
                "SELECT * FROM todo_sources WHERE todo_id = ? ORDER BY created_at ASC", (todo_id,)
            ).fetchall()
            reference_rows = conn.execute(
                "SELECT * FROM todo_references WHERE todo_id = ? ORDER BY created_at ASC", (todo_id,)
            ).fetchall()
            return row_to_todo_detail(
                item_row,
                source_rows=source_rows,
                reference_rows=reference_rows,
                worker_attempts=[],
                attention=_default_attention(),
            )
        finally:
            conn.close()

    def _get_todo_item_detail_sync_locked(self, conn: sqlite3.Connection, todo_id: str) -> TodoItemDetail:
        item_row = conn.execute("SELECT * FROM todo_items WHERE id = ?", (todo_id,)).fetchone()
        source_rows = conn.execute(
            "SELECT * FROM todo_sources WHERE todo_id = ? ORDER BY created_at ASC", (todo_id,)
        ).fetchall()
        reference_rows = conn.execute(
            "SELECT * FROM todo_references WHERE todo_id = ? ORDER BY created_at ASC", (todo_id,)
        ).fetchall()
        return row_to_todo_detail(
            item_row,
            source_rows=source_rows,
            reference_rows=reference_rows,
            worker_attempts=[],
            attention=_default_attention(),
        )

    # === Deletion with optimistic concurrency ===

    async def delete_todo_item_with_expected_revision(
        self, *, todo_id: str, expected_revision: int,
    ) -> None:
        await asyncio.to_thread(
            self._delete_todo_item_with_expected_revision_sync,
            todo_id=todo_id,
            expected_revision=expected_revision,
        )

    def _delete_todo_item_with_expected_revision_sync(
        self, *, todo_id: str, expected_revision: int,
    ) -> None:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_todo_revision_locked(
                conn,
                todo_id=todo_id,
                expected_revision=expected_revision,
            )
            cursor = conn.execute("DELETE FROM todo_items WHERE id = ?", (todo_id,))
            if cursor.rowcount != 1:
                conn.rollback()
                raise TodoRevisionConflict(todo_id)
            conn.commit()
        except TodoRevisionConflict:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def find_todo_by_source(self, *, source_kind: str, source_id: str) -> Optional[TodoItemDetail]:
        return await asyncio.to_thread(self._find_todo_by_source_sync, source_kind=source_kind, source_id=source_id)

    def _find_todo_by_source_sync(self, *, source_kind: str, source_id: str) -> Optional[TodoItemDetail]:
        conn = self._connection()
        try:
            row = conn.execute(
                "SELECT todo_id FROM todo_sources WHERE source_kind = ? AND source_id = ?",
                (source_kind, source_id),
            ).fetchone()
            if row is None:
                return None
            return self._get_todo_item_detail_sync_locked(conn, row["todo_id"])
        finally:
            conn.close()

    # === Update with optimistic concurrency ===

    async def update_todo_item_with_expected_revision(
        self, *, todo_id: str, expected_revision: int, fields: Dict[str, Any], event_kind: str,
        actor_kind: str, actor_id: Optional[str], event_payload: Optional[Dict[str, Any]] = None,
    ) -> TodoItemDetail:
        return await asyncio.to_thread(
            self._update_todo_item_with_expected_revision_sync,
            todo_id=todo_id, expected_revision=expected_revision, fields=fields,
            event_kind=event_kind, actor_kind=actor_kind, actor_id=actor_id, event_payload=event_payload,
        )

    def _update_todo_item_with_expected_revision_sync(
        self, *, todo_id: str, expected_revision: int, fields: Dict[str, Any], event_kind: str,
        actor_kind: str, actor_id: Optional[str], event_payload: Optional[Dict[str, Any]],
    ) -> TodoItemDetail:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            set_clause = ", ".join(f"{key} = ?" for key in fields.keys())
            params = [*fields.values(), _utc_now_iso(), todo_id, expected_revision]
            cursor = conn.execute(
                f"UPDATE todo_items SET {set_clause}, updated_at = ?, revision = revision + 1 "
                f"WHERE id = ? AND revision = ?",
                params,
            )
            if cursor.rowcount == 0:
                conn.rollback()
                raise TodoRevisionConflict(todo_id)
            conn.execute(
                """
                INSERT INTO todo_events (id, todo_id, event_kind, actor_kind, actor_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()), todo_id, event_kind, actor_kind, actor_id,
                    json.dumps(event_payload if event_payload is not None else fields, default=str),
                    _utc_now_iso(),
                ),
            )
            detail = self._get_todo_item_detail_sync_locked(conn, todo_id)
            conn.commit()
            return detail
        except TodoRevisionConflict:
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def replace_todo_item_notes_with_expected_revision(
        self, *, todo_id: str, notes: str, expected_revision: int, actor_kind: str, actor_id: Optional[str],
    ) -> TodoItemDetail:
        return await self.update_todo_item_with_expected_revision(
            todo_id=todo_id, expected_revision=expected_revision, fields={"notes": notes},
            event_kind="notes_replaced", actor_kind=actor_kind, actor_id=actor_id,
        )

    async def add_todo_reference_with_expected_revision(
        self,
        *,
        todo_id: str,
        path: str,
        expected_revision: int,
        actor_kind: str,
        actor_id: Optional[str],
    ) -> TodoItemDetail:
        return await asyncio.to_thread(
            self._add_todo_reference_with_expected_revision_sync,
            todo_id=todo_id,
            path=path,
            expected_revision=expected_revision,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    def _add_todo_reference_with_expected_revision_sync(
        self,
        *,
        todo_id: str,
        path: str,
        expected_revision: int,
        actor_kind: str,
        actor_id: Optional[str],
    ) -> TodoItemDetail:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_todo_revision_locked(conn, todo_id=todo_id, expected_revision=expected_revision)
            existing_reference = conn.execute(
                "SELECT id FROM todo_references WHERE todo_id = ? AND path = ?",
                (todo_id, path),
            ).fetchone()
            if existing_reference is not None:
                detail = self._get_todo_item_detail_sync_locked(conn, todo_id)
                conn.commit()
                return detail
            now = _utc_now_iso()
            conn.execute(
                """
                INSERT INTO todo_references (id, todo_id, path, created_by_kind, created_by_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), todo_id, path, actor_kind, actor_id, now),
            )
            self._advance_todo_revision_locked(
                conn,
                todo_id=todo_id,
                expected_revision=expected_revision,
            )
            self._insert_todo_event_locked(
                conn,
                todo_id=todo_id,
                event_kind="reference_added",
                actor_kind=actor_kind,
                actor_id=actor_id,
                payload={"path": path},
            )
            detail = self._get_todo_item_detail_sync_locked(conn, todo_id)
            conn.commit()
            return detail
        except TodoRevisionConflict:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def remove_todo_reference_with_expected_revision(
        self,
        *,
        todo_id: str,
        reference_id: str,
        expected_revision: int,
        actor_kind: str,
        actor_id: Optional[str],
    ) -> TodoItemDetail:
        return await asyncio.to_thread(
            self._remove_todo_reference_with_expected_revision_sync,
            todo_id=todo_id,
            reference_id=reference_id,
            expected_revision=expected_revision,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    def _remove_todo_reference_with_expected_revision_sync(
        self,
        *,
        todo_id: str,
        reference_id: str,
        expected_revision: int,
        actor_kind: str,
        actor_id: Optional[str],
    ) -> TodoItemDetail:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_todo_revision_locked(conn, todo_id=todo_id, expected_revision=expected_revision)
            reference = conn.execute(
                "SELECT path FROM todo_references WHERE id = ? AND todo_id = ?",
                (reference_id, todo_id),
            ).fetchone()
            if reference is None:
                raise TodoReferenceNotFound(todo_id, reference_id)
            conn.execute("DELETE FROM todo_references WHERE id = ? AND todo_id = ?", (reference_id, todo_id))
            self._advance_todo_revision_locked(
                conn,
                todo_id=todo_id,
                expected_revision=expected_revision,
            )
            self._insert_todo_event_locked(
                conn,
                todo_id=todo_id,
                event_kind="reference_removed",
                actor_kind=actor_kind,
                actor_id=actor_id,
                payload={"reference_id": reference_id, "path": reference["path"]},
            )
            detail = self._get_todo_item_detail_sync_locked(conn, todo_id)
            conn.commit()
            return detail
        except TodoReferenceNotFound:
            conn.rollback()
            raise
        except TodoRevisionConflict:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def append_todo_item_note(
        self, *, todo_id: str, note_markdown: str, actor_kind: str, actor_id: Optional[str],
    ) -> TodoItemDetail:
        """Append a timestamped note line without requiring optimistic
        concurrency from the caller; used only by the scoped workspace-manager
        note tool, which never competes with a user's own notes edit for the
        same field in the same request."""
        return await asyncio.to_thread(
            self._append_todo_item_note_sync, todo_id=todo_id, note_markdown=note_markdown,
            actor_kind=actor_kind, actor_id=actor_id,
        )

    def _append_todo_item_note_sync(
        self, *, todo_id: str, note_markdown: str, actor_kind: str, actor_id: Optional[str],
    ) -> TodoItemDetail:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT notes FROM todo_items WHERE id = ?", (todo_id,)).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError(f"To-Do {todo_id} not found")
            existing_notes = row["notes"] or ""
            appended = f"{existing_notes}\n\n{note_markdown}".strip() if existing_notes else note_markdown
            if len(appended) > 12000:
                appended = appended[-12000:]
            conn.execute(
                "UPDATE todo_items SET notes = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
                (appended, _utc_now_iso(), todo_id),
            )
            conn.execute(
                """
                INSERT INTO todo_events (id, todo_id, event_kind, actor_kind, actor_id, payload_json, created_at)
                VALUES (?, ?, 'workspace_note_appended', ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), todo_id, actor_kind, actor_id, json.dumps({"note": note_markdown}), _utc_now_iso()),
            )
            detail = self._get_todo_item_detail_sync_locked(conn, todo_id)
            conn.commit()
            return detail
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def append_todo_event(
        self, *, todo_id: str, event_kind: str, actor_kind: str, actor_id: Optional[str], payload: Dict[str, Any],
    ) -> None:
        await asyncio.to_thread(self._append_todo_event_sync, todo_id=todo_id, event_kind=event_kind,
                                 actor_kind=actor_kind, actor_id=actor_id, payload=payload)

    def _append_todo_event_sync(
        self, *, todo_id: str, event_kind: str, actor_kind: str, actor_id: Optional[str], payload: Dict[str, Any],
    ) -> None:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO todo_events (id, todo_id, event_kind, actor_kind, actor_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), todo_id, event_kind, actor_kind, actor_id, json.dumps(payload, default=str), _utc_now_iso()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _assert_todo_revision_locked(
        conn: sqlite3.Connection,
        *,
        todo_id: str,
        expected_revision: int,
    ) -> None:
        row = conn.execute("SELECT revision FROM todo_items WHERE id = ?", (todo_id,)).fetchone()
        if row is None or row["revision"] != expected_revision:
            raise TodoRevisionConflict(todo_id)

    @staticmethod
    def _advance_todo_revision_locked(
        conn: sqlite3.Connection,
        *,
        todo_id: str,
        expected_revision: int,
    ) -> None:
        cursor = conn.execute(
            """
            UPDATE todo_items
            SET updated_at = ?, revision = revision + 1
            WHERE id = ? AND revision = ?
            """,
            (_utc_now_iso(), todo_id, expected_revision),
        )
        if cursor.rowcount == 0:
            raise TodoRevisionConflict(todo_id)

    @staticmethod
    def _insert_todo_event_locked(
        conn: sqlite3.Connection,
        *,
        todo_id: str,
        event_kind: str,
        actor_kind: str,
        actor_id: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO todo_events (id, todo_id, event_kind, actor_kind, actor_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                todo_id,
                event_kind,
                actor_kind,
                actor_id,
                json.dumps(payload, default=str),
                _utc_now_iso(),
            ),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_TODO_SORT_DEFAULT_DIRECTION = {
    "created_at": "desc",
    "updated_at": "desc",
    "due_at": "asc",
    "title": "asc",
    "priority": "desc",
    "status": "asc",
}

_TODO_SORT_COLUMN_EXPR = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "due_at": "due_at",
    "title": "title COLLATE NOCASE",
    "priority": (
        "CASE priority "
        "WHEN 'high' THEN 3 WHEN 'normal' THEN 2 WHEN 'low' THEN 1 ELSE 0 END"
    ),
    "status": (
        "CASE status "
        "WHEN 'candidate' THEN 0 WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 "
        "WHEN 'ready_for_review' THEN 3 WHEN 'completed' THEN 4 "
        "WHEN 'dismissed' THEN 5 WHEN 'canceled' THEN 6 ELSE 7 END"
    ),
}


def _todo_sort_column(sort_by: str) -> str:
    if sort_by == "updated_at":
        return "updated_at"
    return "created_at"


def _resolve_todo_sort_direction(sort_by: str, sort_direction: Optional[str]) -> str:
    if sort_by not in _TODO_SORT_COLUMN_EXPR:
        raise ValueError("Invalid To-Do workspace sort column")
    if sort_direction not in (None, "asc", "desc"):
        raise ValueError("Invalid To-Do workspace sort direction")
    return sort_direction or _TODO_SORT_DEFAULT_DIRECTION[sort_by]


def _todo_order_by_clause(sort_by: str, sort_direction: str) -> str:
    column_expr = _TODO_SORT_COLUMN_EXPR[sort_by]
    direction = sort_direction.upper()
    if sort_by == "due_at":
        return f"(due_at IS NULL) ASC, due_at {direction}, id {direction}"
    return f"{column_expr} {direction}, id {direction}"


def _escape_sql_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_workspace_statuses(statuses: Optional[List[str]]) -> tuple[str, ...]:
    normalized = tuple(sorted(set(statuses or [])))
    if any(status not in _TODO_STATUSES for status in normalized):
        raise ValueError("Invalid To-Do workspace status filter")
    return normalized


def _encode_todo_workspace_cursor(
    *,
    sort_by: str,
    sort_direction: str,
    query: str,
    statuses: tuple[str, ...],
    sort_value: Any,
    todo_id: str,
) -> str:
    payload = json.dumps(
        {
            "id": todo_id,
            "query": query,
            "sort_by": sort_by,
            "sort_direction": sort_direction,
            "sort_value": sort_value,
            "statuses": statuses,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_todo_workspace_cursor(cursor: Optional[str]) -> Optional[Dict[str, Any]]:
    if cursor is None:
        return None
    normalized = cursor.strip()
    if not normalized:
        raise TodoWorkspaceCursorError()
    try:
        padded = normalized + "=" * (-len(normalized) % 4)
        decoded = base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise TodoWorkspaceCursorError() from error
    if not isinstance(payload, dict) or set(payload) != {
        "id", "query", "sort_by", "sort_direction", "sort_value", "statuses",
    }:
        raise TodoWorkspaceCursorError()
    return payload


def _validate_todo_workspace_cursor(
    cursor: Dict[str, Any],
    *,
    sort_by: str,
    sort_direction: str,
    query: str,
    statuses: tuple[str, ...],
) -> None:
    cursor_statuses = cursor["statuses"]
    if (
        cursor["sort_by"] != sort_by
        or cursor["sort_direction"] != sort_direction
        or cursor["query"] != query
        or not isinstance(cursor["id"], str)
        or not cursor["id"]
        or not isinstance(cursor_statuses, list)
        or tuple(cursor_statuses) != statuses
    ):
        raise TodoWorkspaceCursorError()
    sort_value = cursor["sort_value"]
    if sort_by == "due_at":
        if sort_value is not None and not isinstance(sort_value, str):
            raise TodoWorkspaceCursorError()
    elif sort_by in ("priority", "status"):
        if not isinstance(sort_value, int) or isinstance(sort_value, bool):
            raise TodoWorkspaceCursorError()
    elif not isinstance(sort_value, str):
        raise TodoWorkspaceCursorError()


def _todo_workspace_sort_value(row: sqlite3.Row, sort_by: str) -> Any:
    if sort_by == "priority":
        return {"high": 3, "normal": 2, "low": 1}.get(row["priority"], 0)
    if sort_by == "status":
        return {
            "candidate": 0,
            "open": 1,
            "in_progress": 2,
            "ready_for_review": 3,
            "completed": 4,
            "dismissed": 5,
            "canceled": 6,
        }.get(row["status"], 7)
    return row[sort_by]


def _todo_workspace_cursor_clause(
    *,
    sort_by: str,
    sort_direction: str,
    sort_value: Any,
    todo_id: str,
) -> Tuple[str, List[Any]]:
    comparison = ">" if sort_direction == "asc" else "<"
    if sort_by == "due_at":
        if sort_value is None:
            return f"(due_at IS NULL AND id {comparison} ?)", [todo_id]
        return (
            f"(due_at IS NULL OR due_at {comparison} ? OR (due_at = ? AND id {comparison} ?))",
            [sort_value, sort_value, todo_id],
        )
    column_expr = _TODO_SORT_COLUMN_EXPR[sort_by]
    return (
        f"(({column_expr}) {comparison} ? OR (({column_expr}) = ? AND id {comparison} ?))",
        [sort_value, sort_value, todo_id],
    )


def _default_attention():
    from .models import TodoAttention
    return TodoAttention()
