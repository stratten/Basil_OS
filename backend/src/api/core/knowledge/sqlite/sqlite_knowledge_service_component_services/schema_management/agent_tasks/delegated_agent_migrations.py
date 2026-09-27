"""Idempotent migration for executor-neutral delegated AgentTask work."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from .delegated_agent_schema import get_delegated_agent_schema_statements


def _rebuild_v1_delegated_tables(conn: sqlite3.Connection) -> None:
    """Migrate pre-dependency generic runs while retaining every durable row."""
    conn.execute("SAVEPOINT delegated_agent_schema_v1_to_v3")
    try:
        conn.execute("ALTER TABLE delegated_agent_turns RENAME TO delegated_agent_turns_legacy")
        conn.execute("ALTER TABLE delegated_agent_outcomes RENAME TO delegated_agent_outcomes_legacy")
        conn.execute("ALTER TABLE delegated_agent_runs RENAME TO delegated_agent_runs_legacy")
        for statement in get_delegated_agent_schema_statements():
            conn.execute(statement)
        legacy_runs = conn.execute("SELECT * FROM delegated_agent_runs_legacy").fetchall()
        legacy_turn_count = conn.execute("SELECT COUNT(*) FROM delegated_agent_turns_legacy").fetchone()[0]
        legacy_outcome_count = conn.execute("SELECT COUNT(*) FROM delegated_agent_outcomes_legacy").fetchone()[0]
        now = datetime.utcnow().isoformat()
        for row in legacy_runs:
            conn.execute(
                """
                INSERT INTO delegated_agent_runs (
                    id, parent_agent_task_id, root_task_id, child_agent_task_id,
                    executor_kind, admitted_scope_json, evidence_policy_json,
                    dependency_run_ids_json, parent_continuation_required, status,
                    revision, created_at, updated_at, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 1, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["parent_agent_task_id"], row["root_task_id"],
                    row["child_agent_task_id"], row["executor_kind"],
                    row["admitted_scope_json"], row["evidence_policy_json"],
                    row["status"], row["revision"], row["created_at"],
                    row["updated_at"], row["settled_at"],
                ),
            )
            conn.execute(
                """
                INSERT INTO delegated_agent_events (
                    id, delegated_agent_run_id, revision, event_kind, event_data_json, created_at
                ) VALUES (?, ?, ?, 'legacy_snapshot', ?, ?)
                """,
                (
                    str(uuid.uuid4()), row["id"], int(row["revision"]),
                    json.dumps({"legacy_status": row["status"]}, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
        conn.execute(
            """
            INSERT INTO delegated_agent_turns (
                id, delegated_agent_run_id, turn_sequence, controller_instruction,
                status, terminal_response_json, created_at, started_at, settled_at
            )
            SELECT id, delegated_agent_run_id, turn_sequence, controller_instruction,
                   status, terminal_response_json, created_at, started_at, settled_at
            FROM delegated_agent_turns_legacy
            """
        )
        conn.execute(
            """
            INSERT INTO delegated_agent_outcomes (
                delegated_agent_run_id, transport_state, executor_result_state,
                evidence_state, summary, receipt_references_json, created_at
            )
            SELECT delegated_agent_run_id, transport_state, executor_result_state,
                   evidence_state, summary, receipt_references_json, created_at
            FROM delegated_agent_outcomes_legacy
            """
        )
        counts = (
            conn.execute("SELECT COUNT(*) FROM delegated_agent_runs").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM delegated_agent_turns").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM delegated_agent_outcomes").fetchone()[0],
        )
        if counts != (len(legacy_runs), legacy_turn_count, legacy_outcome_count):
            raise RuntimeError("delegated-agent migration did not preserve every legacy row")
        conn.execute("DROP TABLE delegated_agent_turns_legacy")
        conn.execute("DROP TABLE delegated_agent_outcomes_legacy")
        conn.execute("DROP TABLE delegated_agent_runs_legacy")
        conn.execute("RELEASE SAVEPOINT delegated_agent_schema_v1_to_v3")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT delegated_agent_schema_v1_to_v3")
        conn.execute("RELEASE SAVEPOINT delegated_agent_schema_v1_to_v3")
        raise


def migrate_delegated_agent_tables(conn: sqlite3.Connection) -> None:
    """Install or upgrade every delegated-agent table without partial schema state."""
    reservation_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(delegated_agent_child_reservations)")
    }
    run_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(delegated_agent_runs)")
    }
    if not run_columns:
        for statement in get_delegated_agent_schema_statements():
            conn.execute(statement)
        return
    if not reservation_columns:
        for statement in get_delegated_agent_schema_statements():
            conn.execute(statement)
        return
    required_run_columns = {"dependency_run_ids_json", "parent_continuation_required"}
    if not required_run_columns.issubset(run_columns):
        _rebuild_v1_delegated_tables(conn)
        reservation_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(delegated_agent_child_reservations)")
        }
    if "strategic_assessment_json" not in reservation_columns:
        conn.execute("SAVEPOINT delegated_agent_schema_v3_assessment")
        try:
            conn.execute(
                "ALTER TABLE delegated_agent_child_reservations "
                "ADD COLUMN strategic_assessment_json TEXT NOT NULL DEFAULT "
                "'{\"child_cannot_delegate\":true,\"expected_benefit\":\"legacy reservation\","
                "\"independence_rationale\":\"legacy reservation\","
                "\"parallelism_reason\":\"legacy reservation\","
                "\"parent_work_can_continue\":false}'"
            )
            conn.execute("RELEASE SAVEPOINT delegated_agent_schema_v3_assessment")
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT delegated_agent_schema_v3_assessment")
            conn.execute("RELEASE SAVEPOINT delegated_agent_schema_v3_assessment")
            raise
    for statement in get_delegated_agent_schema_statements():
        conn.execute(statement)
