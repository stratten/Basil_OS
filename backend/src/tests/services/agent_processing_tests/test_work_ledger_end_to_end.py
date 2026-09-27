"""Temporary-SQLite normal-flow proof for generic ledger continuation."""

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


def _envelope(entity: LedgerEntityReference, status: str) -> MaterialOperationEnvelope:
    return MaterialOperationEnvelope(
        receipts=(
            MaterialOperationReceipt(
                entity=entity,
                requested_effect={"operation": "flag"},
                execution_state="succeeded",
                observed_postcondition={"observed": True},
                verification_status=status,
                evidence={"fixture": True},
            ),
        )
    )


@pytest.mark.asyncio
async def test_durable_flow_keeps_bodies_out_and_reports_unverified_receipts(
    tmp_path: Path,
):
    knowledge = SQLiteKnowledgeService(tmp_path / "ledger.db")
    ledger = AgentWorkLedgerService(knowledge)
    context = {"agent_task_id": "root-task"}

    await ledger.capture_tool_result(
        context=context,
        service="email_service",
        method="get_email_metadata",
        parameters={},
        result={"items": [{"id": "retrieval-email", "subject": "safe", "body": "secret"}]},
        receipt_key="discovery",
    )
    shell = _envelope(
        LedgerEntityReference(
            "file",
            "filesystem",
            {"host_scope": "local"},
            str(tmp_path / "artifact.txt"),
        ),
        "verified",
    )
    await ledger.capture_tool_result(
        context=context,
        service="shell_service",
        method="execute_command",
        parameters={},
        result=shell.to_tool_result_fields(),
        receipt_key="shell",
    )
    mail = _envelope(
        LedgerEntityReference(
            "email",
            "mail_app",
            {"mailbox": "inbox"},
            "mail-fixture",
        ),
        "unverified",
    )
    await ledger.capture_tool_result(
        context=context,
        service="email_service",
        method="organize_emails",
        parameters={},
        result=mail.to_tool_result_fields(),
        receipt_key="mail",
    )

    session = await ledger.resolve_session(context=context)
    discovery = await knowledge.agent_work_item_repository.get_items(
        session_id=session["id"],
        external_id="retrieval-email",
    )
    assert "body" not in discovery[0]["metadata"]
    receipts = await knowledge.agent_work_receipt_repository.get_receipts(
        session_id=session["id"],
        item_id=None,
        limit=10,
    )
    assert sum(receipt["material_write"] for receipt in receipts) == 2
    assert "unverified" in await ledger.handoff(context=context)
    assert mail.to_tool_result_fields()["needs_outcome_review"] is True
