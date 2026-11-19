"""Upgrade coverage for durable source-safe agent work ledger schema."""

import sqlite3

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_work.migrations import (
    migrate_agent_work_session_tables,
)


def test_duplicate_root_migration_preserves_items_and_receipts(tmp_path):
    database = tmp_path / "legacy.db"
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agent_tasks (id TEXT PRIMARY KEY, root_task_id TEXT);
        CREATE TABLE agent_work_sessions (
            id TEXT PRIMARY KEY, agent_task_id TEXT, root_task_id TEXT,
            goal TEXT NOT NULL, collection_type TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}', strategy_json TEXT NOT NULL DEFAULT '{}',
            cursor_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active',
            summary_so_far TEXT, item_budget INTEGER, token_budget INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP
        );
        CREATE TABLE agent_work_items (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, external_id TEXT,
            batch_index INTEGER, status TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
            decision_json TEXT NOT NULL DEFAULT '{}', detail_summary TEXT,
            action_result_json TEXT NOT NULL DEFAULT '{}', error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE agent_work_receipts (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, item_id TEXT, agent_task_id TEXT,
            service TEXT NOT NULL, method TEXT NOT NULL, receipt_key TEXT,
            requested_effect_json TEXT NOT NULL DEFAULT '{}', execution_state TEXT NOT NULL,
            verification_status TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '{}',
            discrepancy_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    for session_id in ("first", "second"):
        conn.execute(
            """
            INSERT INTO agent_work_sessions (
                id, root_task_id, goal, collection_type
            ) VALUES (?, 'root', 'goal', 'email')
            """,
            (session_id,),
        )
        conn.execute(
            """
            INSERT INTO agent_work_items (
                id, session_id, external_id, status
            ) VALUES (?, ?, 'same-id', 'discovered')
            """,
            (f"item-{session_id}", session_id),
        )
        conn.execute(
            """
            INSERT INTO agent_work_receipts (
                id, session_id, item_id, service, method, receipt_key,
                execution_state, verification_status
            ) VALUES (?, ?, ?, 'service', 'method', 'same-key', 'succeeded', 'verified')
            """,
            (f"receipt-{session_id}", session_id, f"item-{session_id}"),
        )
    conn.commit()

    migrate_agent_work_session_tables(conn)
    migrate_agent_work_session_tables(conn)

    assert conn.execute("SELECT COUNT(*) FROM agent_work_sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM agent_work_items").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM agent_work_receipts").fetchone()[0] == 2
    receipt_keys = [
        row[0]
        for row in conn.execute(
            "SELECT receipt_key FROM agent_work_receipts ORDER BY receipt_key"
        ).fetchall()
    ]
    assert receipt_keys == ["same-key", "same-key::migrated::receipt-second"]
    assert conn.execute(
        "SELECT COUNT(*) FROM agent_work_events"
    ).fetchone()[0] == 0
    conn.close()
