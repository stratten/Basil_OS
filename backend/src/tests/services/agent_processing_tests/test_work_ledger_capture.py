"""Focused structured artifact-capture coverage for durable work ledger."""

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
    AgentWorkLedgerService,
)

from api.services.agent_processing.lifecycle.runtime.work_ledger_capture import (
    capture_records,
    capture_scope,
)


def test_capture_records_handles_email_coverage_files_browser_and_discovery():
    payload = {
        "result": {
            "items": [{"id": "email-1", "subject": "One", "body": "excluded"}],
            "coverage_metadata": {"coverage_complete": "false", "scanned": 100},
            "file_artifacts": [{"full_path": "/tmp/output.txt", "operation": "create"}],
            "browser_automation_target": {
                "browser": "Safari", "window_index": 2, "tab_index": 3,
            },
            "discovery_receipts": [{"id": "connection-1", "source": "mail"}],
        },
    }

    records = {
        record.external_id: record
        for record in capture_records(payload, source_system="email_service")
    }

    assert capture_scope(payload)["coverage"]["coverage_complete"] == "false"
    assert "body" not in records["email-1"].metadata
    assert records["email-1"].entity_type == "discovered_item"
    assert records["email-1"].source_system == "email_service"
    assert records["file:/tmp/output.txt"].verification_status == "verified"
    assert records["file:/tmp/output.txt"].entity_type == "file"
    assert records["browser:Safari:2:3"].metadata["kind"] == "browser_target"
    assert records["browser:Safari:2:3"].entity_type == "browser_target"
    assert records["discovery:connection-1"].metadata["kind"] == "discovery_receipt"
    assert records["discovery:connection-1"].entity_type == "discovery_receipt"


def test_capture_records_handles_external_envelopes_without_content_fields():
    records = capture_records({
        "result": {
            "external_catalog_envelope": {
                "items": [{"external_id": "catalog-1", "name": "Mail", "content": "secret"}],
            },
            "browser_automation_target": {
                "browser": "Safari", "window_index": 1, "tab_index": 2,
            },
        },
    }, source_system="catalog_service")

    records_by_id = {record.external_id: record for record in records}

    assert records_by_id["catalog-1"].metadata == {
        "external_id": "catalog-1",
        "name": "Mail",
    }
    assert records_by_id["catalog-1"].source_system == "catalog_service"
    assert records_by_id["browser:Safari:1:2"].evidence == {
        "browser_automation_target": {
            "browser": "Safari", "window_index": 1, "tab_index": 2,
        },
    }


@pytest.mark.asyncio
async def test_ledger_persists_artifact_sources_and_verified_file_receipt(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="artifact-root",
        original_prompt="Capture artifacts",
        transcribed_prompt="Capture artifacts",
        status="processing",
    )
    result = await AgentWorkLedgerService(service).capture_tool_result(
        context={"agent_task_id": "artifact-root", "root_task_id": "artifact-root"},
        service="shell_service",
        method="execute_command",
        parameters={"file_operations": [{"operation": "create", "path": "/tmp/output.txt"}]},
        result={
            "success": True,
            "result": {
                "items": [{"id": "email-1"}],
                "coverage_metadata": {"coverage_complete": "false"},
                "file_artifacts": [{"full_path": "/tmp/output.txt", "operation": "create"}],
                "browser_automation_target": {
                    "browser": "Safari", "window_index": 2, "tab_index": 3,
                },
                "discovery_receipts": [{"id": "connection-1"}],
            },
        },
    )
    items = await service.agent_work_item_repository.get_items(session_id=result["session"]["id"])
    file_item = next(item for item in items if item["external_id"] == "file:/tmp/output.txt")
    receipts = await service.agent_work_receipt_repository.get_receipts(
        session_id=result["session"]["id"], item_id=file_item["id"],
    )

    assert result["session"]["scope"]["coverage"]["coverage_complete"] == "false"
    assert {item["external_id"] for item in items} == {
        "email-1", "file:/tmp/output.txt", "browser:Safari:2:3", "discovery:connection-1",
    }
    assert receipts[0]["verification_status"] == "verified"
    assert receipts[0]["evidence"]["file_artifact"]["full_path"] == "/tmp/output.txt"


@pytest.mark.asyncio
async def test_ledger_records_empty_discovery_without_upgrading_verification(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="empty-root",
        original_prompt="Inspect inbox",
        transcribed_prompt="Inspect inbox",
        status="processing",
    )

    captured = await AgentWorkLedgerService(service).capture_tool_result(
        context={"agent_task_id": "empty-root"},
        service="email_service",
        method="get_email_metadata",
        parameters={"folder": "inbox"},
        result={"success": True, "result": {"items": []}},
        receipt_key="empty-discovery",
        evidence_source="raw_service",
    )
    receipts = await service.agent_work_receipt_repository.get_receipts(
        session_id=captured["session"]["id"],
    )

    assert captured["item_count"] == 0
    assert len(receipts) == 1
    assert receipts[0]["verification_status"] == "not_applicable"
    assert receipts[0]["requested_effect"]["material_write"] is False
