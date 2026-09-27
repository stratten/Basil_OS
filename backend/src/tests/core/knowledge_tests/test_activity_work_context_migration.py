"""Migration tests for activity work-context backfill."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.activity_work_context_migrations import (
    migrate_activity_work_contexts,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_zettel_backreference,
)
from api.services.zettel.materializer import ZettelMaterializer
from api.services.zettel.sources.screen_source import ScreenActivitySource


class NonClosingConnection:
    """Hands a test connection to code that expects a context manager."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc_info):
        return False


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in get_schema_statements():
        conn.execute(statement)
    migrate_zettel_backreference(conn)


def _insert_activity(
    conn: sqlite3.Connection,
    activity_id: str,
    *,
    app_name: str,
    window_title: str,
    moment: datetime,
    extracted_text: str = "ocr body",
    ai_analysis: str | None = '{"content_summary": "working"}',
    zettel_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO activities (
            id, timestamp, app_name, window_title, extracted_text,
            ai_analysis, created_at, context_hash, zettel_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity_id,
            moment.isoformat(),
            app_name,
            window_title,
            extracted_text,
            ai_analysis,
            moment.isoformat(),
            f"hash-{activity_id}",
            zettel_id,
        ),
    )


def _seed_pre_v1_fixture(conn: sqlite3.Connection) -> None:
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    _insert_activity(
        conn,
        "a-basil-1",
        app_name="Cursor",
        window_title="main.py — Basil_Plus_Auth_Service (Workspace)",
        moment=base,
    )
    _insert_activity(
        conn,
        "a-basil-2",
        app_name="Cursor",
        window_title="routes.py — Basil_Plus_Auth_Service (Workspace)",
        moment=base + timedelta(minutes=2),
    )
    _insert_activity(
        conn,
        "a-speakeasy-1",
        app_name="Cursor",
        window_title="admin.py — Speakeasy_AutoAdmin (Workspace)",
        moment=base + timedelta(minutes=4),
    )
    _insert_activity(
        conn,
        "a-outlook-1",
        app_name="Microsoft Outlook",
        window_title="Re: Contract review",
        moment=base + timedelta(minutes=6),
    )
    conn.execute(
        """
        INSERT INTO zettel_entries (
            id, source_kind, source_id, event_type, occurred_at, title,
            payload_json, materialized_at
        ) VALUES (
            'z-old-block', 'screen_block', 'a-basil-1', 'screen_block',
            ?, 'Cursor: merged block', '{"capture_count": 4}', ?
        )
        """,
        (base.isoformat(), base.isoformat()),
    )
    conn.execute(
        """
        INSERT INTO zettel_entries (
            id, source_kind, source_id, event_type, occurred_at, title,
            payload_json, materialized_at
        ) VALUES (
            'agent_task:preserved', 'agent_task', 'preserved', 'agent_task_run',
            ?, 'Unrelated agent task', '{"outcome": "completed"}', ?
        )
        """,
        (base.isoformat(), base.isoformat()),
    )
    conn.execute(
        "UPDATE activities SET zettel_id = 'screen_block:a-basil-1' WHERE id IN ('a-basil-1', 'a-basil-2', 'a-speakeasy-1', 'a-outlook-1')"
    )


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _apply_schema(connection)
    _seed_pre_v1_fixture(connection)
    yield connection
    connection.close()


def test_first_migration_preserves_raw_rows_and_resets_only_screen_blocks(conn):
    before = conn.execute(
        "SELECT id, extracted_text, ai_analysis FROM activities ORDER BY id"
    ).fetchall()
    preserved_zettel = conn.execute(
        "SELECT id, source_kind, source_id, payload_json FROM zettel_entries "
        "WHERE id = 'agent_task:preserved'"
    ).fetchone()
    changed = migrate_activity_work_contexts(conn)
    after = conn.execute(
        "SELECT id, extracted_text, ai_analysis FROM activities ORDER BY id"
    ).fetchall()

    assert changed == 4
    assert [(row["id"], row["extracted_text"], row["ai_analysis"]) for row in before] == [
        (row["id"], row["extracted_text"], row["ai_analysis"]) for row in after
    ]
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE source_kind = 'screen_block'"
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM activities WHERE zettel_id LIKE 'screen_block:%'"
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM activity_metadata WHERE key = 'work_context_version' AND value = '1'"
    ).fetchone()["n"] == 4
    assert conn.execute(
        "SELECT id, source_kind, source_id, payload_json FROM zettel_entries "
        "WHERE id = 'agent_task:preserved'"
    ).fetchone() == preserved_zettel


def test_recarding_after_migration_produces_three_expected_blocks(conn):
    migrate_activity_work_contexts(conn)
    materializer = ZettelMaterializer(sources=[ScreenActivitySource()])
    materializer._connection = lambda: NonClosingConnection(conn)
    materializer.run_pass()

    rows = conn.execute(
        """
        SELECT source_id, json_extract(payload_json, '$.work_context_label') AS label,
               json_extract(payload_json, '$.capture_count') AS captures
        FROM zettel_entries
        WHERE source_kind = 'screen_block'
        ORDER BY source_id
        """
    ).fetchall()

    assert len(rows) == 3
    labels = {row["label"] for row in rows}
    assert labels == {"Basil_Plus_Auth_Service", "Speakeasy_AutoAdmin", "Re: Contract review"}
    basil = next(row for row in rows if row["label"] == "Basil_Plus_Auth_Service")
    assert basil["captures"] == 2


def test_second_migration_is_idempotent(conn):
    first = migrate_activity_work_contexts(conn)
    materializer = ZettelMaterializer(sources=[ScreenActivitySource()])
    materializer._connection = lambda: NonClosingConnection(conn)
    materializer.run_pass()

    zettel_snapshot = conn.execute(
        "SELECT id, source_id FROM zettel_entries WHERE source_kind = 'screen_block' ORDER BY id"
    ).fetchall()
    stamp_snapshot = conn.execute(
        "SELECT id, zettel_id FROM activities ORDER BY id"
    ).fetchall()

    second = migrate_activity_work_contexts(conn)

    assert first == 4
    assert second == 0
    assert conn.execute(
        "SELECT id, source_id FROM zettel_entries WHERE source_kind = 'screen_block' ORDER BY id"
    ).fetchall() == zettel_snapshot
    assert conn.execute(
        "SELECT id, zettel_id FROM activities ORDER BY id"
    ).fetchall() == stamp_snapshot
