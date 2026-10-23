"""Phase 1-3 functional validation for durable agent-work continuation."""

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_work.migrations import (
    migrate_agent_work_session_tables,
)
from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
    AgentWorkLedgerService,
)
from api.services.agent_processing.lifecycle.runtime.work_ledger_capture import capture_records


@pytest.mark.asyncio
async def test_restart_preserves_structured_capture_for_follow_up_handoff(tmp_path):
    db_path = tmp_path / "knowledge.db"
    first_process = SQLiteKnowledgeService(db_path)
    await first_process.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Review the inbox",
        transcribed_prompt="Review the inbox",
        status="processing",
    )
    captured = await AgentWorkLedgerService(first_process).capture_tool_result(
        context={"agent_task_id": "root-task", "root_task_id": "root-task"},
        service="email_service",
        method="get_email_metadata",
        parameters={"folder": "inbox"},
        result={
            "success": True,
            "result": {
                "items": [{"email_id": "message-1", "subject": "One", "body": "private"}],
                "coverage_metadata": {"coverage_complete": "false"},
            },
        },
    )

    restarted_process = SQLiteKnowledgeService(db_path)
    follow_up = AgentWorkLedgerService(restarted_process)
    session = await follow_up.resolve_session(
        context={"agent_task_id": "follow-up", "root_task_id": "root-task"},
    )
    handoff = await follow_up.handoff(
        context={"agent_task_id": "follow-up", "root_task_id": "root-task"},
    )
    items = await restarted_process.agent_work_item_repository.get_items(
        session_id=session["id"],
    )
    receipts = await restarted_process.agent_work_receipt_repository.get_receipts(
        session_id=session["id"],
    )

    assert session["id"] == captured["session"]["id"]
    assert items[0]["external_id"] == "message-1"
    assert "body" not in items[0]["metadata"]
    assert receipts[0]["agent_task_id"] == "root-task"
    assert f"session_id: {session['id']}" in handoff
    assert '"coverage_complete": "false"' in handoff


def test_capture_excludes_sensitive_content_and_deduplicates_nested_entities():
    records = capture_records(
        {
            "result": {
                "items": [
                    {
                        "message_id": "message-1",
                        "subject": "One",
                        "body": "private body",
                        "content": "private content",
                        "html_body": "<p>private html</p>",
                    },
                    {"message_id": "message-1", "subject": "Duplicate"},
                ],
                "file_artifacts": [{"full_path": "/tmp/report.txt", "operation": "create"}],
            }
        },
        source_system="email_service",
    )

    records_by_id = {record.external_id: record for record in records}

    assert set(records_by_id) == {"message-1", "file:/tmp/report.txt"}
    assert records_by_id["message-1"].metadata == {
        "message_id": "message-1",
        "subject": "One",
    }
    assert records_by_id["file:/tmp/report.txt"].verification_status == "verified"


@pytest.mark.asyncio
async def test_receipts_are_idempotent_and_require_material_write_evidence(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    session = await service.agent_work_session_repository.create_session(
        goal="Validate receipt behavior",
        collection_type="files",
        root_task_id="root-task",
    )
    repository = service.agent_work_receipt_repository

    first = await repository.add_receipt(
        session_id=session["id"],
        service="shell_service",
        method="write_file",
        receipt_key="tool-call-1",
        execution_state="succeeded",
        verification_status="verified",
        requested_effect={"material_write": True},
        evidence={"path": "/tmp/report.txt"},
    )
    repeated = await repository.add_receipt(
        session_id=session["id"],
        service="shell_service",
        method="write_file",
        receipt_key="tool-call-1",
        execution_state="succeeded",
        verification_status="verified",
        requested_effect={"material_write": True},
        evidence={"path": "/tmp/other.txt"},
    )

    with pytest.raises(ValueError, match="require evidence"):
        await repository.add_receipt(
            session_id=session["id"],
            service="shell_service",
            method="write_file",
            execution_state="succeeded",
            verification_status="verified",
            requested_effect={"material_write": True},
        )

    assert repeated["id"] == first["id"]


@pytest.mark.asyncio
async def test_root_isolation_allows_follow_ups_but_rejects_other_chains(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    ledger = AgentWorkLedgerService(service)
    owner = await ledger.ensure_session(
        context={"agent_task_id": "root-owner", "root_task_id": "root-owner"},
    )

    follow_up = await ledger.resolve_session(
        context={"agent_task_id": "child-owner", "root_task_id": "root-owner"},
        session_id=owner["id"],
    )

    with pytest.raises(ValueError, match="not accessible"):
        await ledger.resolve_session(
            context={"agent_task_id": "other-root", "root_task_id": "other-root"},
            session_id=owner["id"],
        )

    assert follow_up["id"] == owner["id"]


@pytest.mark.asyncio
async def test_legacy_session_migration_backfills_task_chain_root_and_receipts(tmp_path):
    db_path = tmp_path / "knowledge.db"
    service = SQLiteKnowledgeService(db_path)
    await service.store_agent_task(
        agent_task_id="legacy-root",
        original_prompt="Legacy root",
        transcribed_prompt="Legacy root",
        status="processing",
    )
    session = await service.agent_work_session_repository.create_session(
        agent_task_id="legacy-root",
        root_task_id="legacy-root",
        goal="Legacy work",
        collection_type="email",
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "UPDATE agent_work_sessions SET root_task_id = NULL WHERE id = ?",
            (session["id"],),
        )
        migrate_agent_work_session_tables(conn)
        conn.commit()

    restarted = SQLiteKnowledgeService(db_path)
    migrated = await restarted.agent_work_session_repository.get_session(session["id"])
    receipts = await restarted.agent_work_receipt_repository.get_receipts(
        session_id=session["id"],
    )

    assert migrated["root_task_id"] == "legacy-root"
    assert receipts == []
