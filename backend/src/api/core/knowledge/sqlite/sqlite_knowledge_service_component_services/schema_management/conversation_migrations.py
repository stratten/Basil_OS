"""SQLite schema migrations grouped by durable domain."""

import json
import logging
import sqlite3
import uuid

from ...schema import get_schema_statements
from ..infrastructure.connection import generate_context_hash

logger = logging.getLogger(__name__)


def migrate_conversation_indexes(conn: sqlite3.Connection) -> None:
    """Install indexes required by cursor-paginated conversation history."""
    conversation_table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'conversations'"
    ).fetchone()
    if conversation_table_exists is None:
        return
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_updated_at_id "
        "ON conversations(updated_at DESC, id DESC)"
    )



