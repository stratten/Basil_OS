"""Durable, task-owned artifact revision repository (SQLite)."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ...infrastructure.connection import get_async_connection


def latest_revision_sha256(
    conn: sqlite3.Connection,
    agent_task_id: str,
    artifact_id: str,
) -> Optional[str]:
    """Return the most recently captured revision's digest, if any."""
    row = conn.execute(
        """
        SELECT content_sha256
        FROM agent_task_artifact_revisions
        WHERE agent_task_id = ? AND artifact_id = ?
        ORDER BY revision DESC
        LIMIT 1
        """,
        (agent_task_id, artifact_id),
    ).fetchone()
    return row["content_sha256"] if row is not None else None


def latest_artifact_revision_metadata(
    conn: sqlite3.Connection,
    agent_task_id: str,
    artifact_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the latest task-owned revision's presentation metadata, if any."""
    row = conn.execute(
        """
        SELECT revision, content_kind
        FROM agent_task_artifact_revisions
        WHERE agent_task_id = ? AND artifact_id = ?
        ORDER BY revision DESC
        LIMIT 1
        """,
        (agent_task_id, artifact_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "revision": int(row["revision"]),
        "content_kind": row["content_kind"],
        "revision_count": revision_count(conn, agent_task_id, artifact_id),
    }


def task_snapshot_bytes_used(conn: sqlite3.Connection, agent_task_id: str) -> int:
    """Return the sum of already-persisted revision bytes for one task."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(byte_count), 0) AS total_bytes
        FROM agent_task_artifact_revisions
        WHERE agent_task_id = ?
        """,
        (agent_task_id,),
    ).fetchone()
    return int(row["total_bytes"]) if row is not None else 0


def insert_artifact_revision(
    conn: sqlite3.Connection,
    *,
    agent_task_id: str,
    artifact_id: str,
    local_path: str,
    display_name: str,
    content_kind: str,
    content_sha256: str,
    content: str,
    byte_count: int,
) -> int:
    """Insert one new revision row and return its assigned revision number.

    Must be called inside an already-open write transaction (``BEGIN
    IMMEDIATE``) so the ``MAX(revision) + 1`` computation and the insert are
    atomic with respect to concurrent writers for the same artifact.
    """
    next_revision_row = conn.execute(
        """
        SELECT COALESCE(MAX(revision), 0) + 1 AS next_revision
        FROM agent_task_artifact_revisions
        WHERE agent_task_id = ? AND artifact_id = ?
        """,
        (agent_task_id, artifact_id),
    ).fetchone()
    next_revision = int(next_revision_row["next_revision"])

    conn.execute(
        """
        INSERT INTO agent_task_artifact_revisions (
            id, agent_task_id, artifact_id, local_path, display_name,
            content_kind, revision, content_sha256, content, byte_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"artifact_revision_{uuid.uuid4().hex}",
            agent_task_id,
            artifact_id,
            local_path,
            display_name,
            content_kind,
            next_revision,
            content_sha256,
            content,
            byte_count,
        ),
    )
    return next_revision


def revision_count(conn: sqlite3.Connection, agent_task_id: str, artifact_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS revision_count
        FROM agent_task_artifact_revisions
        WHERE agent_task_id = ? AND artifact_id = ?
        """,
        (agent_task_id, artifact_id),
    ).fetchone()
    return int(row["revision_count"]) if row is not None else 0


async def list_artifact_revisions(
    db_path: str,
    agent_task_id: str,
    artifact_id: str,
    *,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Return metadata-only revision rows, newest-first, owned by one task."""
    conn = await get_async_connection(db_path)
    try:
        cursor = await conn.execute(
            """
            SELECT revision, display_name, content_kind, byte_count, created_at
            FROM agent_task_artifact_revisions
            WHERE agent_task_id = ? AND artifact_id = ?
            ORDER BY revision DESC
            LIMIT ?
            """,
            (agent_task_id, artifact_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "revision": row["revision"],
                "display_name": row["display_name"],
                "content_kind": row["content_kind"],
                "byte_count": row["byte_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        await conn.close()


async def get_artifact_revision(
    db_path: str,
    agent_task_id: str,
    artifact_id: str,
    revision: int,
) -> Optional[Dict[str, Any]]:
    """Return one bounded text snapshot owned by one task, or ``None``."""
    conn = await get_async_connection(db_path)
    try:
        cursor = await conn.execute(
            """
            SELECT revision, display_name, content_kind, byte_count, created_at,
                   content, content_sha256
            FROM agent_task_artifact_revisions
            WHERE agent_task_id = ? AND artifact_id = ? AND revision = ?
            """,
            (agent_task_id, artifact_id, revision),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "revision": row["revision"],
            "display_name": row["display_name"],
            "content_kind": row["content_kind"],
            "byte_count": row["byte_count"],
            "created_at": row["created_at"],
            "content": row["content"],
            "content_sha256": row["content_sha256"],
        }
    finally:
        await conn.close()
