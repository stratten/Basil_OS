"""Focused contracts for universal staged-tool ledger capture."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
    AgentWorkLedgerService,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)


@pytest.fixture
def captured_ledger_calls(monkeypatch):
    captured = []

    async def capture_tool_result(**kwargs):
        captured.append(kwargs)
        return {}

    monkeypatch.setattr(
        "api.dependencies.get_sqlite_knowledge_service",
        lambda: SimpleNamespace(
            agent_work_session_repository=object(),
            agent_work_receipt_repository=object(),
            agent_work_entity_repository=object(),
        ),
    )
    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service.AgentWorkLedgerService",
        lambda _db_service: SimpleNamespace(capture_tool_result=capture_tool_result),
    )
    return captured


@pytest.mark.asyncio
async def test_capture_is_noop_without_an_active_agent_task(captured_ledger_calls):
    token = set_current_agent_context({})
    try:
        outcome = await ToolLedgerCaptureCoordinator().capture_raw_service(
            service="email_service",
            method="get_email_metadata",
            parameters={"folder": "inbox"},
            result=SimpleNamespace(result={"items": []}),
        )
    finally:
        reset_current_agent_context(token)

    assert outcome.attempted is False
    assert captured_ledger_calls == []


@pytest.mark.asyncio
async def test_raw_and_guard_observation_share_one_canonical_capture(captured_ledger_calls):
    context = {
        "agent_task_id": "task-1",
        "root_task_id": "task-1",
        "active_tool_invocation_id": "email-call-1",
    }
    token = set_current_agent_context(context)
    try:
        raw = await ToolLedgerCaptureCoordinator().capture_raw_service(
            service="email_service",
            method="get_email_metadata",
            parameters={"folder": "inbox"},
            result=SimpleNamespace(result={"items": [{"id": "email-1"}]}),
        )
        observation = await ToolLedgerCaptureCoordinator().capture_observation(
            tool_name="email_service_get_email_metadata",
            tool_input={"folder": "inbox"},
            observation='{"items": [{"id": "email-1"}]}',
            invocation_id="email-call-1",
        )
    finally:
        reset_current_agent_context(token)

    assert raw.attempted is True
    assert observation.deduplicated is True
    assert len(captured_ledger_calls) == 1
    assert captured_ledger_calls[0]["evidence_source"] == "raw_service"


@pytest.mark.asyncio
async def test_failed_raw_capture_allows_one_bounded_observation_fallback(monkeypatch):
    calls = []

    async def capture_tool_result(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TypeError("unsupported EmailSearchCriteriaArgs")
        return {}

    monkeypatch.setattr(
        "api.dependencies.get_sqlite_knowledge_service",
        lambda: SimpleNamespace(
            agent_work_session_repository=object(),
            agent_work_receipt_repository=object(),
            agent_work_entity_repository=object(),
        ),
    )
    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service.AgentWorkLedgerService",
        lambda _db_service: SimpleNamespace(capture_tool_result=capture_tool_result),
    )
    context = {
        "agent_task_id": "task-1",
        "root_task_id": "task-1",
        "active_tool_invocation_id": "email-call-1",
    }
    token = set_current_agent_context(context)
    try:
        raw = await ToolLedgerCaptureCoordinator().capture_raw_service(
            service="email_service",
            method="get_email_metadata",
            parameters={"folder": "inbox"},
            result=SimpleNamespace(result={"items": [{"id": "email-1"}]}),
        )
        fallback = await ToolLedgerCaptureCoordinator().capture_observation(
            tool_name="email_service_get_email_metadata",
            tool_input={"folder": "inbox"},
            observation='{"items": [{"id": "email-1"}]}',
            invocation_id="email-call-1",
        )
    finally:
        reset_current_agent_context(token)

    assert raw.attempted is True
    assert raw.persisted is False
    assert fallback.attempted is True
    assert fallback.persisted is True
    assert len(calls) == 2
    assert calls[-1]["evidence_source"] == "normalized_observation"


@pytest.mark.asyncio
async def test_invalid_json_creates_redacted_opaque_receipt(captured_ledger_calls):
    token = set_current_agent_context({"agent_task_id": "task-1"})
    try:
        await ToolLedgerCaptureCoordinator().capture_observation(
            tool_name="vision_analyze",
            tool_input={"image": "secret-path"},
            observation="model output containing private email content",
            invocation_id="vision-call-1",
        )
    finally:
        reset_current_agent_context(token)

    call = captured_ledger_calls[0]
    assert call["opaque_evidence"] == {
        "tool_name": "vision_analyze",
        "result_type": "str",
        "result_size_bytes": len("model output containing private email content"),
        "success": True,
    }
    assert "private email content" not in str(call["opaque_evidence"])
    assert call["result"] == {"success": True, "result": {}}


@pytest.mark.asyncio
async def test_receipt_key_is_stable_for_identical_invocation(captured_ledger_calls):
    coordinator = ToolLedgerCaptureCoordinator()
    receipt_keys = []
    for _ in range(2):
        token = set_current_agent_context({
            "agent_task_id": "task-1",
            "root_task_id": "task-1",
            "active_tool_invocation_id": "stable-call",
        })
        try:
            await coordinator.capture_raw_service(
                service="email_service",
                method="get_email_metadata",
                parameters={"folder": "inbox"},
                result=SimpleNamespace(result={"items": []}),
            )
        finally:
            reset_current_agent_context(token)
        receipt_keys.append(captured_ledger_calls[-1]["receipt_key"])

    assert receipt_keys[0] == receipt_keys[1]
