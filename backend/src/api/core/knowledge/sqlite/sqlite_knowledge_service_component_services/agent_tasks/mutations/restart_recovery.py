"""Agent task restart recovery mutation operations."""

import json
import logging
import sqlite3
from datetime import datetime

from ...infrastructure.connection import run_write_transaction_async
from .root_summary import recompute_root_summary, root_task_id_for_agent_task

logger = logging.getLogger(__name__)


async def mark_interrupted_active_agent_tasks(db_path: str) -> int:
    """Mark active task rows as failed after a backend restart."""
    active_statuses = ("routing", "processing", "awaiting_user_input", "capturing")

    def _body(conn: sqlite3.Connection) -> int:
        placeholders = ",".join("?" * len(active_statuses))
        cursor = conn.execute(
            f"""
            SELECT id, status, result_data
            FROM agent_tasks
            WHERE status IN ({placeholders})
            """,
            active_statuses,
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
                "error": "Task interrupted by application restart",
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
                SET status = 'cancelled',
                    updated_at = ?,
                    resolved_at = ?,
                    revision = revision + 1
                WHERE status = 'pending' AND agent_task_id IN ({cancel_placeholders})
                """,
                (interrupted_at, interrupted_at, *interrupted_task_ids),
            )

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
