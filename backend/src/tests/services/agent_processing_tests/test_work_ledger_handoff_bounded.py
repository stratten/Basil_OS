"""Regression coverage for bounded, accurate work-ledger handoffs."""

import json
import sqlite3
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
    AgentWorkLedgerService,
)
from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)


def _receipt(index: int, verification_status: str) -> MaterialOperationReceipt:
    execution_state = "failed" if verification_status == "failed" else "succeeded"
    return MaterialOperationReceipt(
        entity=LedgerEntityReference(
            entity_type="file",
            source_system="fixture_filesystem",
            source_scope={"host_scope": "temporary"},
            external_id=f"/tmp/handoff-{index}.txt",
        ),
        requested_effect={"operation": "write"},
        execution_state=execution_state,
        observed_postcondition={"exists": True}
        if verification_status != "failed"
        else {},
        verification_status=verification_status,
        evidence={"fixture_index": index},
        discrepancy={"fixture_failure": index}
        if verification_status == "failed"
        else {},
    )


def _handoff_value(handoff: str, field_name: str):
    prefix = f"- {field_name}: "
    line = next(line for line in handoff.splitlines() if line.startswith(prefix))
    return json.loads(line.removeprefix(prefix))


async def _capture_material_receipts(
    ledger: AgentWorkLedgerService,
    context: dict[str, str],
    statuses: list[str],
) -> dict:
    envelope = MaterialOperationEnvelope(
        receipts=tuple(_receipt(index, status) for index, status in enumerate(statuses))
    )
    return await ledger.capture_tool_result(
        context=context,
        service="fixture_service",
        method="write_fixture_files",
        parameters={},
        result=envelope.to_tool_result_fields(),
        receipt_key="fixture-material-write",
    )


@pytest.mark.asyncio
async def test_handoff_counts_all_material_receipts_beyond_fifty(
    tmp_path: Path,
):
    knowledge = SQLiteKnowledgeService(tmp_path / "ledger.db")
    ledger = AgentWorkLedgerService(knowledge)
    context = {"agent_task_id": "bounded-count-root"}
    statuses = ["verified"] * 40 + ["unverified"] * 12 + ["failed"] * 8

    await _capture_material_receipts(ledger, context, statuses)

    handoff = await ledger.handoff(context=context)
    assert _handoff_value(handoff, "material_receipt_counts") == {
        "failed": 8,
        "unverified": 12,
        "verified": 40,
    }
    assert _handoff_value(handoff, "unresolved_material_receipt_total") == 20


@pytest.mark.asyncio
async def test_handoff_returns_newest_unresolved_receipts_beyond_fifty(
    tmp_path: Path,
):
    knowledge = SQLiteKnowledgeService(tmp_path / "ledger.db")
    ledger = AgentWorkLedgerService(knowledge)
    context = {"agent_task_id": "bounded-newest-root"}
    statuses = ["verified"] * 55 + ["unverified"] * 4 + ["failed"] * 3

    captured = await _capture_material_receipts(ledger, context, statuses)

    handoff = await ledger.handoff(context=context)
    summary = _handoff_value(handoff, "unresolved_material_receipts")
    expected_ids = [
        receipt["id"] for receipt in captured["receipts"][-1:-6:-1]
    ]
    assert [receipt["id"] for receipt in summary] == expected_ids


@pytest.mark.asyncio
async def test_unresolved_material_receipts_use_rowid_for_same_timestamp_ordering(
    tmp_path: Path,
):
    knowledge = SQLiteKnowledgeService(tmp_path / "ledger.db")
    ledger = AgentWorkLedgerService(knowledge)
    context = {"agent_task_id": "same-timestamp-root"}
    captured = await _capture_material_receipts(
        ledger,
        context,
        ["unverified", "unverified", "failed"],
    )
    session = await ledger.resolve_session(context=context)

    with sqlite3.connect(
        knowledge.agent_work_receipt_repository.db_path
    ) as connection:
        connection.execute(
            """
            UPDATE agent_work_receipts
            SET created_at = '2026-01-01 00:00:00'
            WHERE session_id = ?
            """,
            (session["id"],),
        )

    first = await knowledge.agent_work_receipt_repository.get_unresolved_material_receipts(
        session_id=session["id"],
    )
    second = await knowledge.agent_work_receipt_repository.get_unresolved_material_receipts(
        session_id=session["id"],
    )
    expected_ids = [receipt["id"] for receipt in captured["receipts"][::-1]]
    assert [receipt["id"] for receipt in first] == expected_ids
    assert [receipt["id"] for receipt in second] == expected_ids


@pytest.mark.asyncio
async def test_get_receipts_returns_newest_first_when_requested(
    tmp_path: Path,
):
    knowledge = SQLiteKnowledgeService(tmp_path / "ledger.db")
    ledger = AgentWorkLedgerService(knowledge)
    context = {"agent_task_id": "newest-first-root"}
    captured = await _capture_material_receipts(
        ledger,
        context,
        ["unverified", "unverified", "unverified"],
    )
    session = await ledger.resolve_session(context=context)

    with sqlite3.connect(
        knowledge.agent_work_receipt_repository.db_path
    ) as connection:
        connection.execute(
            """
            UPDATE agent_work_receipts
            SET created_at = '2026-01-01 00:00:00'
            WHERE session_id = ?
            """,
            (session["id"],),
        )

    receipts = await knowledge.agent_work_receipt_repository.get_receipts(
        session_id=session["id"],
        newest_first=True,
    )
    expected_ids = [receipt["id"] for receipt in captured["receipts"][::-1]]
    assert [receipt["id"] for receipt in receipts] == expected_ids


@pytest.mark.asyncio
async def test_handoff_renders_an_empty_material_receipt_summary(
    tmp_path: Path,
):
    knowledge = SQLiteKnowledgeService(tmp_path / "ledger.db")
    ledger = AgentWorkLedgerService(knowledge)
    context = {"agent_task_id": "empty-material-root"}

    await ledger.ensure_session(context=context)

    handoff = await ledger.handoff(context=context)
    assert _handoff_value(handoff, "material_receipt_counts") == {}
    assert _handoff_value(handoff, "unresolved_material_receipt_total") == 0
    assert _handoff_value(handoff, "unresolved_material_receipts") == []
