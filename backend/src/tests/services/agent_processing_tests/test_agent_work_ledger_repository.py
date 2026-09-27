"""Focused persistence coverage for the durable work ledger."""

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService


@pytest.mark.asyncio
async def test_work_session_preserves_root_scope_and_receipt_entity_link(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Review artifacts",
        transcribed_prompt="Review artifacts",
        status="processing",
    )
    session = await service.agent_work_session_repository.create_session(
        agent_task_id="root-task",
        root_task_id="root-task",
        goal="Review artifacts",
        collection_type="files",
        scope={"source": "shell", "coverage": {"complete": True}},
    )
    await service.agent_work_item_repository.add_items(
        session_id=session["id"],
        items=[{"external_id": "file:/tmp/report.txt", "metadata": {"kind": "file_artifact"}}],
    )
    item = (await service.agent_work_item_repository.get_items(session_id=session["id"]))[0]
    receipt = await service.agent_work_receipt_repository.add_receipt(
        session_id=session["id"],
        item_id=item["id"],
        agent_task_id="root-task",
        service="shell_service",
        method="execute_command",
        execution_state="succeeded",
        verification_status="verified",
        requested_effect={"material_write": True},
        evidence={"full_path": "/tmp/report.txt"},
    )

    latest = await service.agent_work_session_repository.get_latest_session_for_root("root-task")

    assert latest["scope"]["source"] == "shell"
    assert receipt["item_id"] == item["id"]
    assert receipt["verification_status"] == "verified"
