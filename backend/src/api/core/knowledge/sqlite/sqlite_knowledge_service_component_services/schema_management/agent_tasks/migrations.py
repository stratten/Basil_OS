"""Agent task table migrations for SQLite schema management."""

import logging
import sqlite3
from typing import Dict, Optional

from ....schema import get_schema_statements
from .summary_backfill import (
    agent_task_summary_backfill_needed,
    backfill_agent_task_summaries,
)
from ..fts.tables import ensure_agent_task_search_fts

logger = logging.getLogger(__name__)


def _create_agent_task_artifact_revisions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_task_artifact_revisions (
            id TEXT PRIMARY KEY,
            agent_task_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            local_path TEXT NOT NULL,
            display_name TEXT NOT NULL,
            content_kind TEXT NOT NULL,
            revision INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            content TEXT NOT NULL,
            byte_count INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            UNIQUE(agent_task_id, artifact_id, revision)
        )
        """
    )


def _has_revision_digest_unique_constraint(conn: sqlite3.Connection) -> bool:
    for index in conn.execute("PRAGMA index_list(agent_task_artifact_revisions)").fetchall():
        if not index["unique"]:
            continue
        index_name = index["name"].replace('"', '""')
        columns = [
            row["name"]
            for row in conn.execute(f'PRAGMA index_info("{index_name}")').fetchall()
        ]
        if columns == ["agent_task_id", "artifact_id", "content_sha256"]:
            return True
    return False


def _rebuild_agent_task_artifact_revisions_without_digest_constraint(
    conn: sqlite3.Connection,
) -> None:
    """Preserve existing revisions while allowing an artifact to return to prior content."""
    conn.execute(
        "ALTER TABLE agent_task_artifact_revisions RENAME TO agent_task_artifact_revisions_legacy"
    )
    _create_agent_task_artifact_revisions_table(conn)
    conn.execute(
        """
        INSERT INTO agent_task_artifact_revisions (
            id, agent_task_id, artifact_id, local_path, display_name, content_kind,
            revision, content_sha256, content, byte_count, created_at
        )
        SELECT
            id, agent_task_id, artifact_id, local_path, display_name, content_kind,
            revision, content_sha256, content, byte_count, created_at
        FROM agent_task_artifact_revisions_legacy
        """
    )
    conn.execute("DROP TABLE agent_task_artifact_revisions_legacy")


def migrate_agent_task_artifact_revisions(conn: sqlite3.Connection) -> None:
    """Idempotently create the durable, task-owned artifact revision table."""
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_task_artifact_revisions'"
    ).fetchone() is not None
    if table_exists and _has_revision_digest_unique_constraint(conn):
        _rebuild_agent_task_artifact_revisions_without_digest_constraint(conn)
    else:
        _create_agent_task_artifact_revisions_table(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_task_artifact_revisions_lookup
        ON agent_task_artifact_revisions(agent_task_id, artifact_id, revision DESC)
        """
    )


def migrate_agent_tasks_table(conn: sqlite3.Connection) -> None:
    legacy_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='minions'"
    ).fetchone() is not None
    new_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_tasks'"
    ).fetchone() is not None

    if legacy_exists and not new_exists:
        conn.execute("ALTER TABLE minions RENAME TO agent_tasks")
        logger.info("Renamed legacy 'minions' table to 'agent_tasks'")
        new_exists = True

    if not new_exists:
        for statement in get_schema_statements():
            if "create table if not exists agent_tasks" in statement.lower():
                conn.execute(statement)
                break
        logger.info("Created agent_tasks table")
        return

    cursor = conn.execute("PRAGMA table_info(agent_tasks)")
    vc_columns = [row['name'] for row in cursor.fetchall()]

    rename_columns = {
        "original_command": "original_prompt",
        "transcribed_command": "transcribed_prompt",
    }
    for old_column, new_column in rename_columns.items():
        if old_column in vc_columns and new_column not in vc_columns:
            logger.info(
                "Renaming legacy agent_tasks column %s to %s...",
                old_column,
                new_column,
            )
            conn.execute(
                f"ALTER TABLE agent_tasks RENAME COLUMN {old_column} TO {new_column}"
            )
            vc_columns[vc_columns.index(old_column)] = new_column
            logger.info("Renamed agent_tasks column %s to %s", old_column, new_column)

    if 'title' not in vc_columns:
        logger.info("Adding title column to agent_tasks table...")
        conn.execute("ALTER TABLE agent_tasks ADD COLUMN title TEXT")
        logger.info("Added title column")

    if 'display_prompt_markdown' not in vc_columns:
        logger.info("Adding display_prompt_markdown column to agent_tasks table...")
        conn.execute("ALTER TABLE agent_tasks ADD COLUMN display_prompt_markdown TEXT")
        logger.info("Added display_prompt_markdown column")

    if 'execution_timeline' not in vc_columns:
        logger.info("Adding execution_timeline column to agent_tasks table...")
        conn.execute("ALTER TABLE agent_tasks ADD COLUMN execution_timeline TEXT")
        logger.info("Added execution_timeline column")
        vc_columns.append("execution_timeline")

    if 'root_task_id' not in vc_columns:
        logger.info("Adding root_task_id column to agent_tasks table...")
        conn.execute("ALTER TABLE agent_tasks ADD COLUMN root_task_id TEXT")
        logger.info("Added root_task_id column")
        vc_columns.append("root_task_id")

    if 'previous_task_id' not in vc_columns:
        logger.info("Adding previous_task_id column to agent_tasks table...")
        conn.execute("ALTER TABLE agent_tasks ADD COLUMN previous_task_id TEXT")
        logger.info("Added previous_task_id column")
        vc_columns.append("previous_task_id")

    if 'parent_agent_task_id' in vc_columns:
        conn.execute(
            """
            UPDATE agent_tasks
            SET root_task_id = COALESCE(parent_agent_task_id, id)
            WHERE root_task_id IS NULL OR root_task_id = ''
            """
        )
    else:
        conn.execute(
            """
            UPDATE agent_tasks
            SET root_task_id = id
            WHERE root_task_id IS NULL OR root_task_id = ''
            """
        )

    chain_rows = conn.execute(
        """
        SELECT id, root_task_id, previous_task_id
        FROM agent_tasks
        ORDER BY root_task_id, chain_sequence_number, timestamp, id
        """
    ).fetchall()
    previous_by_root: Dict[str, Optional[str]] = {}
    for row in chain_rows:
        root_task_id = row["root_task_id"] or row["id"]
        desired_previous_id = previous_by_root.get(root_task_id)
        if row["previous_task_id"] in (None, ""):
            conn.execute(
                "UPDATE agent_tasks SET previous_task_id = ? WHERE id = ?",
                (desired_previous_id, row["id"]),
            )
        previous_by_root[root_task_id] = row["id"]

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_root_sequence
        ON agent_tasks(root_task_id, chain_sequence_number)
        """
    )

    if 'parent_agent_task_id' in vc_columns:
        drop_agent_tasks_parent_agent_task_id(conn)
        vc_columns.remove("parent_agent_task_id")

    summary_columns = {
        "last_turn_timestamp": "ALTER TABLE agent_tasks ADD COLUMN last_turn_timestamp TIMESTAMP",
        "turn_count": "ALTER TABLE agent_tasks ADD COLUMN turn_count INTEGER DEFAULT 1",
        "follow_up_count": "ALTER TABLE agent_tasks ADD COLUMN follow_up_count INTEGER DEFAULT 0",
        "result_preview": "ALTER TABLE agent_tasks ADD COLUMN result_preview TEXT",
        "file_count": "ALTER TABLE agent_tasks ADD COLUMN file_count INTEGER DEFAULT 0",
        "latest_status": "ALTER TABLE agent_tasks ADD COLUMN latest_status TEXT",
        "latest_agent_task_id": "ALTER TABLE agent_tasks ADD COLUMN latest_agent_task_id TEXT",
    }
    summary_schema_changed = False
    for column_name, alter_sql in summary_columns.items():
        if column_name not in vc_columns:
            logger.info(f"Adding {column_name} column to agent_tasks table...")
            conn.execute(alter_sql)
            vc_columns.append(column_name)
            summary_schema_changed = True

    provenance_columns = {
        "origin_type": "ALTER TABLE agent_tasks ADD COLUMN origin_type TEXT",
        "origin_id": "ALTER TABLE agent_tasks ADD COLUMN origin_id TEXT",
    }
    for column_name, alter_sql in provenance_columns.items():
        if column_name not in vc_columns:
            logger.info(f"Adding {column_name} column to agent_tasks table...")
            conn.execute(alter_sql)
            vc_columns.append(column_name)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_last_turn
        ON agent_tasks(last_turn_timestamp DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_conversation_roots
        ON agent_tasks(origin_type, origin_id, last_turn_timestamp DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_latest_status
        ON agent_tasks(latest_status)
        """
    )
    ensure_agent_task_search_fts(conn)
    if summary_schema_changed or agent_task_summary_backfill_needed(conn):
        backfill_agent_task_summaries(conn)

    if legacy_exists:
        legacy_columns = [
            row['name']
            for row in conn.execute("PRAGMA table_info(minions)").fetchall()
        ]
        shared_columns = [
            column
            for column in vc_columns
            if column in legacy_columns
        ]

        if shared_columns:
            column_sql = ", ".join(shared_columns)
            conn.execute(
                f"""
                INSERT OR IGNORE INTO agent_tasks ({column_sql})
                SELECT {column_sql}
                FROM minions
                """
            )
            migrated_count = conn.execute(
                "SELECT COUNT(*) FROM agent_tasks"
            ).fetchone()[0]
            legacy_count = conn.execute(
                "SELECT COUNT(*) FROM minions"
            ).fetchone()[0]
            logger.info(
                "Copied legacy minions rows into agent_tasks "
                "(agent_tasks=%s, minions=%s)",
                migrated_count,
                legacy_count,
            )


def drop_agent_tasks_parent_agent_task_id(conn: sqlite3.Connection) -> None:
    """Remove the legacy parent_agent_task_id column after chain backfill."""
    logger.info("Removing legacy parent_agent_task_id column from agent_tasks")
    try:
        conn.execute("ALTER TABLE agent_tasks DROP COLUMN parent_agent_task_id")
        logger.info("Dropped agent_tasks.parent_agent_task_id using ALTER TABLE DROP COLUMN")
        return
    except sqlite3.OperationalError as drop_err:
        logger.info(
            "ALTER TABLE DROP COLUMN unavailable for agent_tasks.parent_agent_task_id; "
            "rebuilding table instead: %s",
            drop_err,
        )

    old_columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(agent_tasks)").fetchall()
        if row["name"] != "parent_agent_task_id"
    ]
    column_sql = ", ".join(old_columns)

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("ALTER TABLE agent_tasks RENAME TO agent_tasks_legacy_parent")
        conn.execute("PRAGMA legacy_alter_table = OFF")
        for statement in get_schema_statements():
            if "create table if not exists agent_tasks" in statement.lower():
                conn.execute(statement)
                break
        conn.execute(
            f"""
            INSERT INTO agent_tasks ({column_sql})
            SELECT {column_sql}
            FROM agent_tasks_legacy_parent
            """
        )
        conn.execute("DROP TABLE agent_tasks_legacy_parent")
        for statement in get_schema_statements():
            lower_stmt = statement.lower()
            if "create index if not exists idx_agent_tasks" in lower_stmt:
                conn.execute(statement)
        logger.info("Rebuilt agent_tasks without parent_agent_task_id")
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
