"""Idempotent migration for durable managed file-change history tables.

Also performs restart reconciliation: any ``managed_file_changes`` row still
in the ``prepared`` state when this migration runs was interrupted before its
outcome (success or failure) could be confirmed. Per the Workstream C
recovery decision, this never guesses about partial filesystem effects — it
only transitions the row to a terminal, clearly-labeled state so a future
managed write recaptures a fresh pre-image rather than trusting stale state.
"""

from __future__ import annotations

import sqlite3

from .schema import get_managed_file_history_schema_statements

_INTERRUPTED_MESSAGE = (
    "Interrupted by restart before completion could be confirmed; no "
    "assumption was made about partial filesystem effects."
)

_MANAGED_FILE_HEADS_CASCADE_SCHEMA = """
CREATE TABLE managed_file_heads (
    canonical_path TEXT PRIMARY KEY,
    current_change_id TEXT NOT NULL,
    current_sha256 TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (current_change_id) REFERENCES managed_file_changes(id) ON DELETE CASCADE
)
"""


def _migrate_managed_file_heads_delete_action(conn: sqlite3.Connection) -> None:
    foreign_keys = conn.execute("PRAGMA foreign_key_list(managed_file_heads)").fetchall()
    has_cascade = any(
        row[2] == "managed_file_changes"
        and row[3] == "current_change_id"
        and row[6].upper() == "CASCADE"
        for row in foreign_keys
    )
    if has_cascade:
        return

    conn.execute("ALTER TABLE managed_file_heads RENAME TO managed_file_heads_legacy")
    conn.execute(_MANAGED_FILE_HEADS_CASCADE_SCHEMA)
    conn.execute(
        """
        INSERT INTO managed_file_heads (canonical_path, current_change_id, current_sha256, updated_at)
        SELECT canonical_path, current_change_id, current_sha256, updated_at
        FROM managed_file_heads_legacy
        """
    )
    conn.execute("DROP TABLE managed_file_heads_legacy")


def migrate_managed_file_history_tables(conn: sqlite3.Connection) -> None:
    for statement in get_managed_file_history_schema_statements():
        conn.execute(statement)
    _migrate_managed_file_heads_delete_action(conn)
    prepared_rows = conn.execute(
        """
        SELECT pre_image_sha256
        FROM managed_file_changes
        WHERE state = 'prepared'
        """
    ).fetchall()
    for row in prepared_rows:
        digest = row["pre_image_sha256"]
        if digest is None:
            continue
        conn.execute(
            """
            UPDATE managed_file_blobs
            SET ref_count = MAX(ref_count - 1, 0)
            WHERE sha256 = ?
            """,
            (digest,),
        )
        conn.execute(
            """
            UPDATE managed_file_blobs
            SET pending_deletion = 1, marked_for_deletion_at = CURRENT_TIMESTAMP
            WHERE sha256 = ? AND ref_count = 0 AND pending_deletion = 0
            """,
            (digest,),
        )
    conn.execute(
        """
        UPDATE managed_file_changes
        SET state = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
        WHERE state = 'prepared'
        """,
        (_INTERRUPTED_MESSAGE,),
    )
