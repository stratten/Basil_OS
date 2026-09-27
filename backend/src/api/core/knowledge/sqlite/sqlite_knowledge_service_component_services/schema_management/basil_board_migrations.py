"""SQLite schema migrations grouped by durable domain."""

import json
import logging
import sqlite3
import uuid

from ...schema import get_schema_statements
from ..infrastructure.connection import generate_context_hash

logger = logging.getLogger(__name__)


_BASIL_BOARD_SEED_TABS = (
    ("home", "Home", "home", 0, "home", '{"detach_behavior": "none"}'),
    (
        "todos",
        "To-Dos",
        "checklist",
        1,
        "capability",
        '{"capability_id": "todos.workspace", "detach_behavior": "none"}',
    ),
    (
        "chats",
        "Chats",
        "chat",
        2,
        "capability",
        '{"capability_id": "conversations.history", "detach_behavior": "useNativeWindow"}',
    ),
    (
        "meetings",
        "Meetings",
        "meetings",
        3,
        "capability",
        '{"capability_id": "meetings.history", "detach_behavior": "useBoardWindow"}',
    ),
    (
        "agent_tasks",
        "Agent Tasks",
        "agent_tasks",
        4,
        "capability",
        '{"capability_id": "agent_tasks.history", "detach_behavior": "useNativeWindow"}',
    ),
)


def migrate_basil_board_tables(conn: sqlite3.Connection) -> None:
    """Create/upgrade all BasilBoard tables, then seed default tabs and
    one-time-import any pre-inquiry Home history. Runs inside the caller's
    transaction (see SchemaManager.initialize_db); this function must not
    call conn.commit()."""
    for statement in get_schema_statements():
        stmt = statement.lower()
        if (
            "create table if not exists basil_board_" in stmt
            or "create unique index if not exists idx_basil_board_" in stmt
            or "create index if not exists idx_basil_board_" in stmt
        ):
            conn.execute(statement)

    _migrate_basil_board_tabs_capability_kind(conn)
    _seed_basil_board_tabs(conn)
    _import_legacy_home_inquiry(conn)


def _migrate_basil_board_tabs_capability_kind(conn: sqlite3.Connection) -> None:
    """Rebuild basil_board_tabs so its tab_kind CHECK constraint accepts
    'capability'. SQLite cannot ALTER a CHECK constraint in place, so this
    mirrors the rename/create/copy/drop pattern already used elsewhere in
    this module for CHECK-constraint upgrades. No-ops once already migrated."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'basil_board_tabs'"
    ).fetchone()
    if row is None or row[0] is None or "'capability'" in row[0]:
        return

    conn.execute("DROP INDEX IF EXISTS idx_basil_board_tabs_active_home")
    conn.execute("ALTER TABLE basil_board_tabs RENAME TO basil_board_tabs_legacy")

    for statement in get_schema_statements():
        if statement.strip().lower().startswith("create table if not exists basil_board_tabs ("):
            conn.execute(statement)
            break

    conn.execute(
        """
        INSERT INTO basil_board_tabs (
            id, title, icon_key, position, tab_kind, status, configuration_json,
            created_by_kind, created_by_id, created_at, updated_at
        )
        SELECT
            id, title, icon_key, position, tab_kind, status, configuration_json,
            created_by_kind, created_by_id, created_at, updated_at
        FROM basil_board_tabs_legacy
        """
    )
    conn.execute("DROP TABLE basil_board_tabs_legacy")

    for statement in get_schema_statements():
        if "create unique index if not exists idx_basil_board_tabs_" in statement.lower():
            conn.execute(statement)

    logger.info("Migrated basil_board_tabs to accept the 'capability' tab_kind")


def _seed_basil_board_tabs(conn: sqlite3.Connection) -> None:
    """Idempotently create/refresh the default Home, To-Dos, Chats, Meetings, and Agent Tasks tabs."""
    for tab_id, title, icon_key, position, tab_kind, configuration_json in _BASIL_BOARD_SEED_TABS:
        conn.execute(
            """
            INSERT INTO basil_board_tabs (
                id, title, icon_key, position, tab_kind, status,
                configuration_json, created_by_kind
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, 'system')
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                icon_key = excluded.icon_key,
                position = excluded.position,
                tab_kind = excluded.tab_kind,
                status = 'active',
                configuration_json = excluded.configuration_json
            """,
            (tab_id, title, icon_key, position, tab_kind, configuration_json),
        )
    logger.info("Seeded/refreshed default BasilBoard tabs (home, todos, chats, meetings, agent_tasks)")


def _import_legacy_home_inquiry(conn: sqlite3.Connection) -> None:
    """One-time import: fold the pre-inquiry singleton Home conversation's
    first user message into exactly one legacy-marked inquiry, so upgrading
    users never silently lose their prior Home history from the new
    Recent Inquiries list. Reads basil_board_home_state directly via raw SQL
    (not through BasilBoardRepository) so this migration has no dependency
    on the service layer; basil_board_home_state itself is left untouched."""
    already_imported = conn.execute(
        "SELECT 1 FROM basil_board_inquiries WHERE legacy_imported = 1 LIMIT 1"
    ).fetchone()
    if already_imported:
        return

    home_state = conn.execute(
        "SELECT conversation_id FROM basil_board_home_state WHERE id = 'default'"
    ).fetchone()
    if not home_state:
        return
    conversation_id = home_state["conversation_id"]

    first_message = conn.execute(
        """
        SELECT id, content, timestamp
        FROM conversation_messages
        WHERE conversation_id = ? AND role = 'user'
        ORDER BY timestamp ASC
        LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    if not first_message:
        return

    conn.execute(
        """
        INSERT INTO basil_board_inquiries (
            id, prompt_text, state, conversation_id, user_message_id,
            legacy_imported, created_at, updated_at
        ) VALUES (?, ?, 'completed', ?, ?, 1, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            first_message["content"],
            conversation_id,
            first_message["id"],
            first_message["timestamp"],
            first_message["timestamp"],
        ),
    )
    logger.info("Imported legacy Home conversation as one legacy-marked inquiry")

