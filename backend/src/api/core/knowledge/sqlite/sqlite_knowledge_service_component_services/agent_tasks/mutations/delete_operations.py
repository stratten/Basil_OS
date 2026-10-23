"""Agent task delete mutation operations."""

import logging
import sqlite3
from typing import Callable

from ...infrastructure.connection import run_write_transaction_async
from .root_summary import recompute_root_summary

logger = logging.getLogger(__name__)


async def delete_agent_task(
    db_path: str,
    agent_task_id: str,
    cascade: bool = True,
) -> bool:
    """Delete a agent_task by ID."""

    def _body(conn: sqlite3.Connection) -> bool:
        if cascade:
            cursor = conn.execute(
                """
                SELECT id
                FROM agent_tasks
                WHERE id = ?
                   OR root_task_id = (
                        SELECT COALESCE(root_task_id, id)
                        FROM agent_tasks
                        WHERE id = ?
                   )
                """,
                (agent_task_id, agent_task_id),
            )
            agent_task_ids = [row["id"] for row in cursor.fetchall()]
        else:
            cursor = conn.execute(
                "SELECT id FROM agent_tasks WHERE id = ?",
                (agent_task_id,),
            )
            agent_task_ids = [row["id"] for row in cursor.fetchall()]

        if not agent_task_ids:
            return False

        placeholders = ",".join("?" * len(agent_task_ids))
        impacted_roots = set()
        root_cursor = conn.execute(
            f"""
            SELECT DISTINCT COALESCE(root_task_id, id) AS root_id
            FROM agent_tasks
            WHERE id IN ({placeholders})
            """,
            agent_task_ids,
        )
        impacted_roots.update(row["root_id"] for row in root_cursor.fetchall() if row["root_id"])

        def table_exists(table_name: str) -> bool:
            table_cursor = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            )
            return table_cursor.fetchone() is not None

        if table_exists("mcp_call_log"):
            conn.execute(
                f"DELETE FROM mcp_call_log WHERE agent_task_id IN ({placeholders})",
                agent_task_ids,
            )

        if table_exists("scheduled_agent_task_runs"):
            conn.execute(
                f"DELETE FROM scheduled_agent_task_runs WHERE agent_task_id IN ({placeholders})",
                agent_task_ids,
            )

        if table_exists("agent_conversation_threads"):
            conn.execute(
                f"DELETE FROM agent_conversation_threads WHERE agent_task_id IN ({placeholders})",
                agent_task_ids,
            )

        conn.execute(
            f"DELETE FROM agent_tasks WHERE id IN ({placeholders})",
            agent_task_ids,
        )

        for root_task_id in impacted_roots:
            recompute_root_summary(conn, root_task_id)

        logger.info(
            "Deleted agent_task %s and %s related task(s) (cascade=%s)",
            agent_task_id,
            len(agent_task_ids) - 1,
            cascade,
        )
        return True

    return await run_write_transaction_async(db_path, "delete_agent_task", _body)
