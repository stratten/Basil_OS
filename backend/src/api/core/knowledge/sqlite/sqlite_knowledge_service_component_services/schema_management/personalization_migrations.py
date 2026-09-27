"""Additive migrations for the personalization/user_profile table."""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def migrate_personalization_profile_table(conn: sqlite3.Connection) -> None:
    """Ensure ``user_profile`` exists and has ``custom_instructions``.

    Pure additive migration. ``user_profile`` is created by the one-off
    ``migrations/add_personalization_tables.py`` script rather than the
    incremental migrations this module belongs to, so some existing
    databases may already have it (in which case this only adds the new
    column) while others may not (in which case this also creates it,
    mirroring the create-only branch of ``_migrate_mcp_call_log_table``).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profile (
            id TEXT PRIMARY KEY DEFAULT 'default',
            full_name TEXT,
            preferred_name TEXT,
            email TEXT,
            job_title TEXT,
            company_name TEXT,
            industry TEXT,
            default_formality TEXT,
            default_tone TEXT,
            custom_instructions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            profile_version INTEGER DEFAULT 1
        )
        """
    )
    cursor = conn.execute("PRAGMA table_info(user_profile)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "custom_instructions" not in columns:
        conn.execute("ALTER TABLE user_profile ADD COLUMN custom_instructions TEXT")
        logger.info("Added custom_instructions column to user_profile table")
