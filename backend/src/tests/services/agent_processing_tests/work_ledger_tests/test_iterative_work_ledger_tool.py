"""Focused continuation query and chain-access coverage for iterative_work."""

import json

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import AgentWorkLedgerService
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.internal_basil_tools.iterative_work_tool import (
    create_iterative_work_tool,
)


@pytest.mark.asyncio
async def test_iterative_tool_queries_entity_evidence_within_current_chain(tmp_path, monkeypatch):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="root-query",
        original_prompt="Continue task",
        transcribed_prompt="Continue task",
        status="processing",
    )
    ledger = AgentWorkLedgerService(service)
    context = {"agent_task_id": "root-query", "root_task_id": "root-query"}
    captured = await ledger.capture_tool_result(
        context=context,
        service="email_service",
        method="get_email_metadata",
        parameters={"folder": "inbox"},
        result={"success": True, "result": {"items": [{"id": "email-query"}]}},
    )
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    tool = create_iterative_work_tool()
    token = set_current_agent_context(context)
    try:
        query = json.loads(await tool.ainvoke({
            "action": "query", "session_id": captured["session"]["id"], "external_id": "email-query",
        }))
        evidence = json.loads(await tool.ainvoke({
            "action": "get_evidence", "session_id": captured["session"]["id"], "external_id": "email-query",
        }))
    finally:
        reset_current_agent_context(token)

    assert query["items"][0]["external_id"] == "email-query"
    assert evidence["receipts"][0]["item_id"] == query["items"][0]["id"]
