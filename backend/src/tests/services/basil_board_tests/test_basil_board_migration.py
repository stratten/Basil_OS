"""Migration coverage for the capability tab_kind CHECK-constraint rebuild
and the legacy-Home-conversation-to-inquiry import, run against a
hand-built pre-migration database (mirrors the existing basil_board schema
before this plan's changes)."""

import sqlite3
import uuid
from pathlib import Path

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.basil_board_migrations import (
    migrate_basil_board_tables,
)


def _build_legacy_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE conversation_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        );

        CREATE TABLE basil_board_tabs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            icon_key TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            tab_kind TEXT NOT NULL CHECK (tab_kind IN ('home', 'system_embed', 'agent_report')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
            configuration_json TEXT NOT NULL DEFAULT '{}',
            created_by_kind TEXT NOT NULL DEFAULT 'system',
            created_by_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX idx_basil_board_tabs_active_home
        ON basil_board_tabs(tab_kind)
        WHERE tab_kind = 'home' AND status = 'active';

        CREATE TABLE basil_board_home_state (
            id TEXT PRIMARY KEY CHECK (id = 'default'),
            conversation_id TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO conversations (id, title, metadata) VALUES (?, 'Basil Home', '{}')",
        (conversation_id,),
    )
    conn.execute(
        "INSERT INTO conversation_messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, 'assistant', ?, '2026-01-01 00:00:00')",
        (str(uuid.uuid4()), conversation_id, "Welcome to Basil Home"),
    )
    conn.execute(
        "INSERT INTO conversation_messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, 'user', ?, '2026-01-01 00:00:01')",
        (message_id, conversation_id, "What did I do yesterday?"),
    )
    conn.execute(
        "INSERT INTO basil_board_tabs (id, title, icon_key, position, tab_kind, status, configuration_json, created_by_kind) "
        "VALUES ('home', 'Home', 'home', 0, 'home', 'active', '{}', 'system')"
    )
    conn.execute(
        "INSERT INTO basil_board_home_state (id, conversation_id) VALUES ('default', ?)",
        (conversation_id,),
    )
    conn.commit()
    conn.close()


def _run_basil_board_migration(db_path: Path) -> None:
    conn = get_sync_connection(str(db_path), ensure_schema=False)
    try:
        migrate_basil_board_tables(conn)
        conn.commit()
    finally:
        conn.close()


def test_migration_upgrades_tab_kind_and_imports_legacy_inquiry(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_basil_board.db"
    _build_legacy_db(db_path)
    _run_basil_board_migration(db_path)

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    tabs_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'basil_board_tabs'"
    ).fetchone()[0]
    assert "'capability'" in tabs_sql

    tabs = conn.execute("SELECT id, tab_kind FROM basil_board_tabs ORDER BY position").fetchall()
    assert [(row["id"], row["tab_kind"]) for row in tabs] == [
        ("home", "home"),
        ("todos", "capability"),
        ("chats", "capability"),
        ("meetings", "capability"),
        ("agent_tasks", "capability"),
    ]

    inquiries = conn.execute("SELECT prompt_text, legacy_imported FROM basil_board_inquiries").fetchall()
    assert len(inquiries) == 1
    assert inquiries[0]["prompt_text"] == "What did I do yesterday?"
    assert inquiries[0]["legacy_imported"] == 1

    home_state = conn.execute("SELECT conversation_id FROM basil_board_home_state WHERE id = 'default'").fetchone()
    assert home_state is not None


def test_migration_is_idempotent_on_second_run(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_basil_board.db"
    _build_legacy_db(db_path)

    _run_basil_board_migration(db_path)
    _run_basil_board_migration(db_path)

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    inquiries = conn.execute("SELECT COUNT(*) AS count FROM basil_board_inquiries").fetchone()
    assert inquiries["count"] == 1
    tabs = conn.execute("SELECT COUNT(*) AS count FROM basil_board_tabs").fetchone()
    assert tabs["count"] == 5


def _build_legacy_db_with_custom_tab(db_path: Path) -> None:
    _build_legacy_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO basil_board_tabs (id, title, icon_key, position, tab_kind, status, configuration_json, created_by_kind) "
        "VALUES ('custom-embed', 'Custom Embed', 'custom', 9, 'system_embed', 'active', '{}', 'user')"
    )
    conn.commit()
    conn.close()


def test_migration_preserves_a_non_canonical_custom_tab(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_basil_board.db"
    _build_legacy_db_with_custom_tab(db_path)

    _run_basil_board_migration(db_path)
    _run_basil_board_migration(db_path)

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    custom_tab = conn.execute(
        "SELECT title, icon_key, position, tab_kind, status, configuration_json, created_by_kind "
        "FROM basil_board_tabs WHERE id = 'custom-embed'"
    ).fetchone()
    assert custom_tab is not None
    assert tuple(custom_tab) == ("Custom Embed", "custom", 9, "system_embed", "active", "{}", "user")

    tab_ids = {row["id"] for row in conn.execute("SELECT id FROM basil_board_tabs").fetchall()}
    assert tab_ids == {"home", "todos", "chats", "meetings", "agent_tasks", "custom-embed"}


def test_migration_seeds_the_todos_tab_with_the_workspace_renderer(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_basil_board.db"
    _build_legacy_db(db_path)

    _run_basil_board_migration(db_path)

    conn = get_sync_connection(str(db_path), ensure_schema=False)
    todos_tab = conn.execute(
        "SELECT position, tab_kind, configuration_json FROM basil_board_tabs WHERE id = 'todos'"
    ).fetchone()
    assert todos_tab is not None
    assert todos_tab["position"] == 1
    assert todos_tab["tab_kind"] == "capability"
    assert "todos.workspace" in todos_tab["configuration_json"]
