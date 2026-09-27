"""Foundation Remediation acceptance coverage: source-safe capture, append-only
history, atomic root-session ownership, and strict evidence lookup.

These tests prove the specific acceptance criteria named in
Agent_Task_Continuation_and_Verified_Outcomes_Plan.md's Foundation
Remediation stage, rather than re-testing general ledger behavior already
covered elsewhere (see test_work_ledger_capture.py, test_work_ledger_
functional_validation.py, test_agent_work_ledger_repository.py).
"""

import asyncio
import json
import threading

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
    AgentWorkLedgerService,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.internal_basil_tools.iterative_work_tool import (
    create_iterative_work_tool,
)


@pytest.mark.asyncio
async def test_best_effort_discovery_capture_gets_source_safe_identity(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Review the inbox",
        transcribed_prompt="Review the inbox",
        status="processing",
    )
    ledger = AgentWorkLedgerService(service)

    captured = await ledger.capture_tool_result(
        context={"agent_task_id": "root-task", "root_task_id": "root-task"},
        service="email_service",
        method="get_email_metadata",
        parameters={"folder": "inbox"},
        result={"success": True, "result": {"items": [{"id": "message-1", "subject": "One"}]}},
    )

    entities = await service.agent_work_entity_repository.get_entities(
        session_id=captured["session"]["id"],
    )
    entity = next(item for item in entities if item["external_id"] == "message-1")

    assert entity["entity_type"] == "discovered_item"
    assert entity["source_system"] == "email_service"
    assert entity["identity_quality"] == "best_effort_capture"


@pytest.mark.asyncio
async def test_discovery_capture_from_two_services_with_same_external_id_does_not_collide(
    tmp_path,
):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Cross-service capture",
        transcribed_prompt="Cross-service capture",
        status="processing",
    )
    ledger = AgentWorkLedgerService(service)
    context = {"agent_task_id": "root-task", "root_task_id": "root-task"}

    await ledger.capture_tool_result(
        context=context,
        service="email_service",
        method="get_email_metadata",
        parameters={},
        result={"success": True, "result": {"items": [{"id": "123", "name": "From mail"}]}},
    )
    captured = await ledger.capture_tool_result(
        context=context,
        service="calendar_service",
        method="get_calendar_events",
        parameters={},
        result={"success": True, "result": {"items": [{"id": "123", "name": "From calendar"}]}},
    )

    entities = await service.agent_work_entity_repository.find_by_external_id(
        session_id=captured["session"]["id"],
        external_id="123",
    )

    assert len(entities) == 2
    assert {entity["source_system"] for entity in entities} == {
        "email_service",
        "calendar_service",
    }


@pytest.mark.asyncio
async def test_get_or_create_root_session_is_atomic_under_concurrent_creation(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    repository = service.agent_work_session_repository
    winners: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        barrier.wait()
        try:
            result = asyncio.run(repository.get_or_create_root_session(
                root_task_id="race-root",
                goal="Concurrent creation",
                collection_type="agent_work",
            ))
            winners.append(result["id"])
        except BaseException as exc:  # noqa: BLE001 - surface to the main thread via assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(set(winners)) == 1


@pytest.mark.asyncio
async def test_add_event_never_overwrites_prior_history_for_the_same_entity(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    session = await service.agent_work_session_repository.create_session(
        goal="History", collection_type="files", root_task_id="root-task",
    )
    entity = await service.agent_work_entity_repository.upsert_entity(
        session_id=session["id"],
        entity_type="file",
        source_system="filesystem",
        source_scope={},
        external_id="/tmp/report.txt",
    )

    await service.agent_work_event_repository.add_event(
        session_id=session["id"], item_id=entity["id"],
        event_kind="discovered", payload={"step": 1},
    )
    await service.agent_work_event_repository.add_event(
        session_id=session["id"], item_id=entity["id"],
        event_kind="acted_on", payload={"step": 2},
    )

    events = await service.agent_work_event_repository.get_events(
        session_id=session["id"], item_id=entity["id"],
    )

    assert len(events) == 2
    assert {event["payload"]["step"] for event in events} == {1, 2}
    assert {event["event_kind"] for event in events} == {"discovered", "acted_on"}


@pytest.mark.asyncio
async def test_get_evidence_returns_entity_not_found_for_an_unknown_external_id(
    tmp_path, monkeypatch,
):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="root-query", original_prompt="Continue task",
        transcribed_prompt="Continue task", status="processing",
    )
    ledger = AgentWorkLedgerService(service)
    context = {"agent_task_id": "root-query", "root_task_id": "root-query"}
    session = await ledger.ensure_session(context=context)

    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    tool = create_iterative_work_tool()
    token = set_current_agent_context(context)
    try:
        response = json.loads(await tool.ainvoke({
            "action": "get_evidence",
            "session_id": session["id"],
            "external_id": "never-captured",
        }))
    finally:
        reset_current_agent_context(token)

    assert response["success"] is False
    assert response["error"]["code"] == "entity_not_found"
