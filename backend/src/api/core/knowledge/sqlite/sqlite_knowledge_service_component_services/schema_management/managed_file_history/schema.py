"""Schema statements for durable managed file-change history."""

from __future__ import annotations


def get_managed_file_history_schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS managed_file_changes (
            id TEXT PRIMARY KEY,
            root_task_id TEXT NOT NULL,
            agent_task_id TEXT NOT NULL,
            canonical_path TEXT NOT NULL,
            operation TEXT NOT NULL
                CHECK (operation IN ('create', 'overwrite', 'append', 'rollback')),
            origin TEXT NOT NULL CHECK (origin IN ('model', 'user')),
            pre_image_sha256 TEXT,
            pre_image_size_bytes INTEGER,
            post_image_sha256 TEXT,
            post_image_size_bytes INTEGER,
            expected_precondition_sha256 TEXT,
            restores_change_id TEXT,
            state TEXT NOT NULL DEFAULT 'prepared'
                CHECK (state IN ('prepared', 'applied', 'failed', 'conflicted', 'reverted')),
            error_message TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            applied_at TIMESTAMP,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (restores_change_id) REFERENCES managed_file_changes(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_managed_file_changes_path
        ON managed_file_changes(canonical_path, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_managed_file_changes_task
        ON managed_file_changes(agent_task_id, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_managed_file_changes_state
        ON managed_file_changes(state)
        """,
        """
        CREATE TABLE IF NOT EXISTS managed_file_heads (
            canonical_path TEXT PRIMARY KEY,
            current_change_id TEXT NOT NULL,
            current_sha256 TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (current_change_id) REFERENCES managed_file_changes(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS managed_file_blobs (
            sha256 TEXT PRIMARY KEY,
            byte_size INTEGER NOT NULL,
            ref_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            pending_deletion INTEGER NOT NULL DEFAULT 0,
            marked_for_deletion_at TIMESTAMP
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_managed_file_blobs_pending
        ON managed_file_blobs(pending_deletion)
        """,
    ]
