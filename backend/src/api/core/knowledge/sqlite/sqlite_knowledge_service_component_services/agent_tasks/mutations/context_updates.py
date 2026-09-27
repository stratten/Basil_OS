"""Agent task context, clarification, timeline, and title update operations."""

import json
import logging
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from ...infrastructure.connection import run_write_transaction_async
from .root_summary import recompute_root_summary, root_task_id_for_agent_task

if TYPE_CHECKING:
    from api.services.agent_processing.lifecycle.runtime.artifact_revision_capture import (
        ArtifactRevisionCaptureResult,
    )

logger = logging.getLogger(__name__)


def _artifact_id_for_timeline_entry(value: Any) -> Optional[str]:
    if not isinstance(value, Mapping):
        return None
    metadata = value.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    artifact = metadata.get("artifact")
    if not isinstance(artifact, Mapping):
        return None
    candidate = artifact.get("artifact_id")
    return candidate if isinstance(candidate, str) else None


def _preserve_missing_artifacts(
    persisted_timeline: Any,
    requested_timeline: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Retain durable artifacts when a stale full-timeline writer catches up."""
    if not isinstance(persisted_timeline, list):
        return requested_timeline

    requested_artifact_ids = {
        artifact_id
        for entry in requested_timeline
        if (artifact_id := _artifact_id_for_timeline_entry(entry)) is not None
    }
    missing_artifacts_by_id: Dict[str, Dict[str, Any]] = {}
    for entry in persisted_timeline:
        artifact_id = _artifact_id_for_timeline_entry(entry)
        if (
            isinstance(entry, dict)
            and artifact_id is not None
            and artifact_id not in requested_artifact_ids
        ):
            missing_artifacts_by_id[artifact_id] = entry
    return [*requested_timeline, *missing_artifacts_by_id.values()]


async def clear_agent_task_execution_timeline(
    db_path: str,
    agent_task_id: str,
) -> None:
    """Clear visible execution details before starting a new retry attempt."""

    def _body(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE agent_tasks
            SET execution_timeline = '[]',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (agent_task_id,),
        )
        logger.info("Cleared execution timeline for agent_task %s", agent_task_id)

    await run_write_transaction_async(
        db_path,
        "clear_agent_task_execution_timeline",
        _body,
    )


async def add_agent_task_clarification(
    db_path: str,
    *,
    agent_task_id: str,
    clarification_text: str,
    clarification_agent_task: Optional[str] = None,
    current_clarifications: List[Dict[str, Any]] = None,
) -> None:
    """Add a clarification to a agent_task."""
    if current_clarifications is None:
        current_clarifications = []

    clarification_entry = {
        "text": clarification_text,
        "timestamp": datetime.now().isoformat(),
        "agent_task": clarification_agent_task,
    }
    updated_clarifications = current_clarifications.copy()
    updated_clarifications.append(clarification_entry)

    def _body(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE agent_tasks
            SET clarifications = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(updated_clarifications), agent_task_id),
        )
        logger.info(
            "Added clarification to agent_task %s: '%s...'",
            agent_task_id,
            clarification_text[:50],
        )

    await run_write_transaction_async(db_path, "add_agent_task_clarification", _body)


async def update_agent_task_screen_context(
    db_path: str,
    *,
    agent_task_id: str,
    screen_text: Optional[str] = None,
    app_name: Optional[str] = None,
    window_title: Optional[str] = None,
    screen_capture_path: Optional[str] = None,
) -> None:
    """Update the screen context fields directly in the agent_task record."""

    def _body(conn: sqlite3.Connection) -> None:
        updates = []
        params: list[Any] = []

        if screen_text is not None:
            updates.append("screen_text = ?")
            params.append(screen_text)

        if app_name is not None:
            updates.append("app_name = ?")
            params.append(app_name)

        if window_title is not None:
            updates.append("window_title = ?")
            params.append(window_title)

        if screen_capture_path is not None:
            updates.append("screen_capture_path = ?")
            params.append(screen_capture_path)

        if not updates:
            return

        params.append(agent_task_id)
        conn.execute(
            f"""
            UPDATE agent_tasks
            SET {", ".join(updates)}
            WHERE id = ?
            """,
            params,
        )
        root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
        if root_task_id:
            recompute_root_summary(conn, root_task_id)
        logger.info(
            "Updated agent_task %s screen context: screen_text_length=%s, app=%s, window=%s, capture_path=%s",
            agent_task_id,
            len(screen_text) if screen_text else 0,
            app_name,
            window_title,
            screen_capture_path,
        )

    await run_write_transaction_async(db_path, "update_agent_task_screen_context", _body)


async def update_execution_timeline(
    db_path: str,
    agent_task_id: str,
    timeline: List[Dict[str, Any]],
) -> None:
    """Store the unified execution timeline for a agent_task."""

    def _body(conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT execution_timeline FROM agent_tasks WHERE id = ?",
            (agent_task_id,),
        ).fetchone()
        try:
            persisted_timeline = json.loads(row["execution_timeline"] or "[]") if row else []
        except (TypeError, ValueError):
            persisted_timeline = []
        timeline_with_artifacts = _preserve_missing_artifacts(persisted_timeline, timeline)
        conn.execute(
            "UPDATE agent_tasks SET execution_timeline = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(timeline_with_artifacts), agent_task_id),
        )
        root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
        if root_task_id:
            recompute_root_summary(conn, root_task_id)
        logger.info(
            "Stored execution timeline for agent_task %s: %s entries",
            agent_task_id,
            len(timeline_with_artifacts),
        )

    await run_write_transaction_async(db_path, "update_execution_timeline", _body)


async def update_execution_timeline_if_active(
    db_path: str,
    agent_task_id: str,
    timeline: List[Dict[str, Any]],
) -> bool:
    """Store a timeline only while the Agent Task remains non-terminal."""

    def _body(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            """
            SELECT execution_timeline
            FROM agent_tasks
            WHERE id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            (agent_task_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            persisted_timeline = json.loads(row["execution_timeline"] or "[]")
        except (TypeError, ValueError):
            persisted_timeline = []
        timeline_with_artifacts = _preserve_missing_artifacts(persisted_timeline, timeline)
        updated = conn.execute(
            """
            UPDATE agent_tasks
            SET execution_timeline = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            (json.dumps(timeline_with_artifacts), agent_task_id),
        )
        if updated.rowcount != 1:
            return False
        root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
        if root_task_id:
            recompute_root_summary(conn, root_task_id)
        logger.info(
            "Stored active execution timeline for agent_task %s: %s entries",
            agent_task_id,
            len(timeline_with_artifacts),
        )
        return True

    return await run_write_transaction_async(
        db_path,
        "update_execution_timeline_if_active",
        _body,
    )


async def upsert_execution_timeline_artifact(
    db_path: str,
    agent_task_id: str,
    entry: Dict[str, Any],
    artifact_id: str,
    *,
    revision_capture: Optional["ArtifactRevisionCaptureResult"] = None,
    local_path: Optional[str] = None,
    display_name: Optional[str] = None,
) -> bool:
    """Atomically replace one active timeline artifact by its stable identity.

    When ``revision_capture`` is supplied and its status is ``captured``,
    this inserts one new durable revision row for the artifact in the same
    write transaction as the timeline upsert, and embeds the resulting
    ``review`` presentation metadata into ``entry['metadata']['artifact']``.
    A ``captured``/``unchanged``/``unavailable`` status never fails the
    timeline upsert itself; a revision-table failure only omits ``review``.
    """
    from .revision_repository import (
        insert_artifact_revision,
        latest_artifact_revision_metadata,
        latest_revision_sha256,
        revision_count as count_revisions,
        task_snapshot_bytes_used,
    )

    def _body(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            """
            SELECT execution_timeline
            FROM agent_tasks
            WHERE id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            (agent_task_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            timeline = json.loads(row["execution_timeline"] or "[]")
        except (TypeError, ValueError):
            return False
        if not isinstance(timeline, list):
            return False

        entry_with_review = entry
        if revision_capture is not None and local_path and display_name:
            review = _apply_revision_capture(
                conn,
                agent_task_id=agent_task_id,
                artifact_id=artifact_id,
                local_path=local_path,
                display_name=display_name,
                capture=revision_capture,
                insert_artifact_revision=insert_artifact_revision,
                latest_revision_sha256_fn=latest_revision_sha256,
                revision_count_fn=count_revisions,
                task_snapshot_bytes_used_fn=task_snapshot_bytes_used,
            )
            if review is not None:
                entry_with_review = _entry_with_artifact_review(entry, review)
        else:
            latest_revision = latest_artifact_revision_metadata(
                conn,
                agent_task_id,
                artifact_id,
            )
            if latest_revision is not None:
                entry_with_review = _entry_with_artifact_review(
                    entry,
                    {
                        "revision": latest_revision["revision"],
                        "revision_count": latest_revision["revision_count"],
                        "kind": latest_revision["content_kind"],
                        "snapshot_status": "available",
                    },
                )

        updated_timeline = [
            existing
            for existing in timeline
            if _artifact_id_for_timeline_entry(existing) != artifact_id
        ]
        updated_timeline.append(entry_with_review)
        updated = conn.execute(
            """
            UPDATE agent_tasks
            SET execution_timeline = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            (json.dumps(updated_timeline), agent_task_id),
        )
        if updated.rowcount != 1:
            return False
        root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
        if root_task_id:
            recompute_root_summary(conn, root_task_id)
        logger.info(
            "Upserted timeline artifact for agent_task %s: %s entries",
            agent_task_id,
            len(updated_timeline),
        )
        return True

    return await run_write_transaction_async(
        db_path,
        "upsert_execution_timeline_artifact",
        _body,
    )


def _apply_revision_capture(
    conn: sqlite3.Connection,
    *,
    agent_task_id: str,
    artifact_id: str,
    local_path: str,
    display_name: str,
    capture: "ArtifactRevisionCaptureResult",
    insert_artifact_revision,
    latest_revision_sha256_fn,
    revision_count_fn,
    task_snapshot_bytes_used_fn,
) -> Optional[Dict[str, Any]]:
    """Insert a revision row if captured, then return ``review`` metadata.

    ``capture.content_sha256`` is compared against the DB's own latest row
    for this artifact (not the caller-supplied ``latest_known_sha256`` used
    inside ``capture_artifact_revision`` itself, which the publication layer
    always passes as ``None``): the durable transaction is the single source
    of truth for "did this exact content already get a revision row", so the
    dedupe-by-digest decision belongs here, against the row the write
    transaction can actually see.
    """
    if capture.status == "captured":
        if latest_revision_sha256_fn(conn, agent_task_id, artifact_id) == capture.content_sha256:
            existing_count = revision_count_fn(conn, agent_task_id, artifact_id)
            return {
                "revision": existing_count,
                "revision_count": existing_count,
                "kind": capture.content_kind,
                "snapshot_status": "unchanged",
            }
        bytes_used = task_snapshot_bytes_used_fn(conn, agent_task_id)
        if bytes_used + (capture.byte_count or 0) > 8 * 1024 * 1024:
            return {
                "revision": None,
                "revision_count": revision_count_fn(conn, agent_task_id, artifact_id),
                "kind": capture.content_kind or "unsupported",
                "snapshot_status": "unavailable",
                "unavailable_reason": "Snapshot unavailable: task review size limit.",
            }
        revision = insert_artifact_revision(
            conn,
            agent_task_id=agent_task_id,
            artifact_id=artifact_id,
            local_path=local_path,
            display_name=display_name,
            content_kind=capture.content_kind,
            content_sha256=capture.content_sha256,
            content=capture.content,
            byte_count=capture.byte_count,
        )
        return {
            "revision": revision,
            "revision_count": revision_count_fn(conn, agent_task_id, artifact_id),
            "kind": capture.content_kind,
            "snapshot_status": "available",
        }
    if capture.status == "unchanged":
        latest_sha = latest_revision_sha256_fn(conn, agent_task_id, artifact_id)
        existing_count = revision_count_fn(conn, agent_task_id, artifact_id)
        return {
            "revision": existing_count if latest_sha else None,
            "revision_count": existing_count,
            "snapshot_status": "unchanged",
        }
    return {
        "revision": None,
        "revision_count": revision_count_fn(conn, agent_task_id, artifact_id),
        "snapshot_status": "unavailable",
        "unavailable_reason": capture.unavailable_reason,
    }


def _entry_with_artifact_review(entry: Dict[str, Any], review: Dict[str, Any]) -> Dict[str, Any]:
    metadata = entry.get("metadata")
    if not isinstance(metadata, Mapping):
        return entry
    artifact = metadata.get("artifact")
    if not isinstance(artifact, Mapping):
        return entry
    updated_metadata = {**metadata, "artifact": {**artifact, "review": review}}
    return {**entry, "metadata": updated_metadata}


async def update_agent_task_title(
    db_path: str,
    agent_task_id: str,
    title: str,
) -> None:
    """Update the generated title for a agent_task."""

    def _body(conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE agent_tasks SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, agent_task_id),
        )
        root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
        if root_task_id:
            recompute_root_summary(conn, root_task_id)
        logger.info("Updated title for agent_task %s: '%s'", agent_task_id, title)

    await run_write_transaction_async(db_path, "update_agent_task_title", _body)
