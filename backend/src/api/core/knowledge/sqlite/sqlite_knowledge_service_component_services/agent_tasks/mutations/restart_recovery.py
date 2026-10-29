"""Agent task restart recovery mutation operations."""

import json
import logging
import sqlite3
from datetime import datetime

from ...infrastructure.connection import run_write_transaction_async
from .root_summary import recompute_root_summary, root_task_id_for_agent_task

logger = logging.getLogger(__name__)


AWAITING_USER_INPUT_RESTART_RETENTION_DAYS = 7
EXPIRED_AWAITING_USER_INPUT_ERROR = (
    "Task expired: Basil restarted after this question had waited more than "
    f"{AWAITING_USER_INPUT_RESTART_RETENTION_DAYS} days for an answer"
)
EXPIRED_PAUSED_ERROR = (
    "Task expired: Basil restarted after this task had been paused for more than "
    f"{AWAITING_USER_INPUT_RESTART_RETENTION_DAYS} days"
)


def close_stale_waiting_interactions(conn: sqlite3.Connection) -> int:
    """Mark still-waiting user interactions on finished tasks as canceled.

    A finished task can never receive the answer, so a lingering waiting entry (for example from a run canceled while it waited, before the cancel path recorded the resolution) would show a question nobody can answer.
    """
    from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
        close_waiting_interactions_in_timeline,
    )

    rows = conn.execute(
        """
        SELECT id, execution_timeline
        FROM agent_tasks
        WHERE status IN ('completed', 'failed', 'canceled')
          AND execution_timeline LIKE '%user_interaction%'
        """
    ).fetchall()
    closed_total = 0
    for row in rows:
        try:
            timeline = json.loads(row["execution_timeline"] or "[]")
        except Exception:
            continue
        if not isinstance(timeline, list):
            continue
        updated, closed = close_waiting_interactions_in_timeline(timeline)
        if not closed:
            continue
        conn.execute(
            "UPDATE agent_tasks SET execution_timeline = ? WHERE id = ?",
            (json.dumps(updated), row["id"]),
        )
        closed_total += closed
    return closed_total


async def mark_interrupted_active_agent_tasks(db_path: str) -> int:
    """Mark active task rows as failed after a backend restart.

    A task paused on a question for the user resumes from its durable checkpoint, so it survives a restart unless it has waited longer than the retention window.
    """
    interrupted_statuses = ("routing", "processing", "capturing")

    def _body(conn: sqlite3.Connection) -> int:
        placeholders = ",".join("?" * len(interrupted_statuses))
        cursor = conn.execute(
            f"""
            SELECT id, status, result_data
            FROM agent_tasks
            WHERE status IN ({placeholders})
               OR (
                   status IN ('awaiting_user_input', 'paused')
                   AND (updated_at IS NULL OR julianday(updated_at) < julianday('now', ?))
               )
            """,
            (*interrupted_statuses, f"-{AWAITING_USER_INPUT_RESTART_RETENTION_DAYS} days"),
        )
        rows = cursor.fetchall()
        interrupted_at = datetime.now().isoformat()
        impacted_roots = set()
        interrupted_task_ids: list[str] = []

        for row in rows:
            interrupted_task_ids.append(row["id"])
            try:
                result_data = json.loads(row["result_data"]) if row["result_data"] else {}
            except Exception:
                result_data = {}

            result_data["failure_info"] = {
                "success": False,
                "error": (
                    EXPIRED_AWAITING_USER_INPUT_ERROR
                    if row["status"] == "awaiting_user_input"
                    else EXPIRED_PAUSED_ERROR
                    if row["status"] == "paused"
                    else "Task interrupted by application restart"
                ),
                "previous_status": row["status"],
                "interrupted_at": interrupted_at,
            }

            conn.execute(
                """
                UPDATE agent_tasks
                SET status = 'failed',
                    result_data = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(result_data), row["id"]),
            )
            root_task_id = root_task_id_for_agent_task(conn, row["id"])
            if root_task_id:
                impacted_roots.add(root_task_id)

        if interrupted_task_ids:
            cancel_placeholders = ",".join("?" * len(interrupted_task_ids))
            conn.execute(
                f"""
                UPDATE execution_approvals
                SET status = 'canceled',
                    updated_at = ?,
                    resolved_at = ?,
                    revision = revision + 1
                WHERE status = 'pending' AND agent_task_id IN ({cancel_placeholders})
                """,
                (interrupted_at, interrupted_at, *interrupted_task_ids),
            )

        # Pending approvals only have live waiters inside the process that created them, so after a restart any approval owned by a terminal or paused task can never be answered.
        orphan_cursor = conn.execute(
            """
            UPDATE execution_approvals
            SET status = 'canceled',
                updated_at = ?,
                resolved_at = ?,
                revision = revision + 1
            WHERE status = 'pending'
              AND agent_task_id IN (
                  SELECT id FROM agent_tasks WHERE status IN ('completed', 'failed', 'canceled', 'awaiting_user_input', 'paused')
              )
            """,
            (interrupted_at, interrupted_at),
        )
        if orphan_cursor.rowcount:
            logger.info("Canceled %s orphaned pending execution approval(s) on startup", orphan_cursor.rowcount)

        closed_interactions = close_stale_waiting_interactions(conn)
        if closed_interactions:
            logger.info("Closed %s stale waiting interaction(s) on finished tasks at startup", closed_interactions)

        for root_task_id in impacted_roots:
            recompute_root_summary(conn, root_task_id)

        if rows:
            logger.info("Marked %s active agent_task(s) as interrupted on startup", len(rows))
        return len(rows)

    return await run_write_transaction_async(
        db_path,
        "mark_interrupted_active_agent_tasks",
        _body,
    )
