"""Archive and un-archive an agent task chain.

Archiving is a nullable ``archived_at`` timestamp on the chain's root row only, so the whole chain moves together and no follow-up row is touched.
"""

import logging
import sqlite3
from typing import Literal

from ...infrastructure.connection import run_write_transaction_async
from .root_summary import root_task_id_for_agent_task

logger = logging.getLogger(__name__)

ArchiveOutcome = Literal["ok", "not_found", "active"]

# A chain can only be archived once its latest turn has finished; running, paused and awaiting-input chains stay in the main list, mirroring when Delete is offered.
ARCHIVABLE_STATUSES = ("completed", "failed", "canceled")


def clear_chain_archive_flag(conn: sqlite3.Connection, root_task_id: str) -> None:
    """Un-archive a chain inside the caller's transaction; a no-op when it is not archived."""
    conn.execute(
        "UPDATE agent_tasks SET archived_at = NULL WHERE id = ? AND archived_at IS NOT NULL",
        (root_task_id,),
    )


def set_chain_archived(conn: sqlite3.Connection, agent_task_id: str, archived: bool) -> ArchiveOutcome:
    """Archive or un-archive the chain containing ``agent_task_id`` by updating its root row."""
    root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
    if not root_task_id:
        return "not_found"

    if not archived:
        clear_chain_archive_flag(conn, root_task_id)
        return "ok"

    root = conn.execute(
        "SELECT COALESCE(latest_status, status) AS chain_status FROM agent_tasks WHERE id = ?",
        (root_task_id,),
    ).fetchone()
    if root is None:
        return "not_found"
    if root["chain_status"] not in ARCHIVABLE_STATUSES:
        return "active"

    conn.execute(
        "UPDATE agent_tasks SET archived_at = COALESCE(archived_at, CURRENT_TIMESTAMP) WHERE id = ?",
        (root_task_id,),
    )
    return "ok"


async def set_chain_archived_async(db_path: str, agent_task_id: str, archived: bool) -> ArchiveOutcome:
    """Run ``set_chain_archived`` in its own write transaction."""

    def _body(conn: sqlite3.Connection) -> ArchiveOutcome:
        outcome = set_chain_archived(conn, agent_task_id, archived)
        logger.info(
            "%s agent task chain for %s: %s",
            "Archived" if archived else "Un-archived",
            agent_task_id,
            outcome,
        )
        return outcome

    return await run_write_transaction_async(
        db_path,
        "archive_agent_task_chain" if archived else "unarchive_agent_task_chain",
        _body,
    )
