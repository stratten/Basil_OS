"""Test schema for SQLite knowledge service."""

from typing import List

def get_schema_statements() -> List[str]:
    """Get SQL statements for creating the test database schema."""
    return [
        # Activities table - Core activity storage
        """
        CREATE TABLE IF NOT EXISTS activities (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            app_name TEXT NOT NULL,
            window_title TEXT,
            extracted_text TEXT,
            ai_analysis TEXT,
            duration INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            context_hash TEXT
        )
        """,

        # Activity metadata - Flexible attribute storage
        """
        CREATE TABLE IF NOT EXISTS activity_metadata (
            activity_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            FOREIGN KEY (activity_id) REFERENCES activities(id),
            PRIMARY KEY (activity_id, key)
        )
        """
    ] 