"""Agent re-engagement tools: bounded in-task wait, durable follow-ups, registration, and chain-cancel cleanup."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
    AgentTaskFollowUpRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_follow_up_migrations import (
    migrate_agent_follow_up_tables,
)
from api.services.agent_processing.lifecycle.execution_graph import tool_run_watchdog
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    register_optional_tools,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
    family_names_for_tool_name,
)
from api.services.agent_processing.lifecycle.execution_graph.workflow_deadline import WorkflowDeadline
from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
    AgentTaskSubmissionService,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.internal_basil_tools import agent_follow_up_tool as tool_module
from api.services.agent_processing.tools.internal_basil_tools.agent_follow_up_tool import (
    CANCEL_TOOL_NAME,
    SCHEDULE_TOOL_NAME,
    WAIT_TOOL_NAME,
    WAIT_USED_CONTEXT_KEY,
    create_agent_follow_up_tools,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(tool_module, "time", SimpleNamespace(time=fake.time))
    return fake


@pytest.fixture
def progress(monkeypatch):
    calls = []
    monkeypatch.setattr(tool_run_watchdog, "record_tool_progress", lambda **kwargs: calls.append(kwargs))
    return calls


@pytest.fixture
def repository(tmp_path) -> AgentTaskFollowUpRepository:
    db_path = tmp_path / "follow_ups.db"
    with sqlite3.connect(db_path) as conn:
        migrate_agent_follow_up_tables(conn)
    return AgentTaskFollowUpRepository(str(db_path))


@pytest.fixture
def agent_context():
    context = {"agent_task_id": "task-1"}
    token = set_current_agent_context(context)
    try:
        yield context
    finally:
        reset_current_agent_context(token)


def _tool(tools, name):
    return next(item for item in tools if item.name == name)


def _install_sleep(monkeypatch, clock, on_sleep=None):
    slept = []

    async def _fake_sleep(seconds):
        slept.append(seconds)
        if on_sleep is not None:
            on_sleep()
        clock.now += seconds

    monkeypatch.setattr(tool_module, "asyncio", SimpleNamespace(sleep=_fake_sleep))
    return slept


@pytest.mark.asyncio
async def test_wait_pauses_budget_marks_waiting_and_clamps(monkeypatch, clock, progress, agent_context):
    deadline = WorkflowDeadline.start(total_seconds=10_000, finalization_reserve_seconds=0)
    agent_context["_workflow_deadline"] = deadline
    paused_during_sleep = []
    slept = _install_sleep(monkeypatch, clock, on_sleep=lambda: paused_during_sleep.append(deadline.pause_reasons))

    raw = await _tool(create_agent_follow_up_tools(), WAIT_TOOL_NAME).ainvoke({"seconds": 9999, "reason": "build"})
    result = json.loads(raw)

    assert result["success"] is True
    assert result["waited_seconds"] == 600
    assert sum(slept) == 600
    assert max(slept) <= tool_module.WAIT_TICK_SECONDS
    assert paused_during_sleep and all(reasons == ["agent_wait"] for reasons in paused_during_sleep)
    assert deadline.is_paused is False
    assert agent_context[WAIT_USED_CONTEXT_KEY] == 600
    assert result["remaining_wait_allowance_seconds"] == 1200
    assert [call["status"] for call in progress] == ["waiting", "active"]
    assert progress[0]["tool_name"] == WAIT_TOOL_NAME
    assert progress[0]["agent_task_id"] == "task-1"


@pytest.mark.asyncio
async def test_wait_clamps_small_values_up(monkeypatch, clock, progress, agent_context):
    slept = _install_sleep(monkeypatch, clock)

    result = json.loads(await _tool(create_agent_follow_up_tools(), WAIT_TOOL_NAME).ainvoke({"seconds": 0}))

    assert result["waited_seconds"] == 5
    assert sum(slept) == 5


@pytest.mark.asyncio
async def test_wait_allowance_exhausted_refuses(monkeypatch, clock, progress, agent_context):
    agent_context[WAIT_USED_CONTEXT_KEY] = 1800
    slept = _install_sleep(monkeypatch, clock)

    result = json.loads(await _tool(create_agent_follow_up_tools(), WAIT_TOOL_NAME).ainvoke({"seconds": 60}))

    assert result["success"] is False
    assert "schedule_agent_follow_up" in result["error"]
    assert slept == []
    assert progress == []


@pytest.mark.asyncio
async def test_wait_is_clamped_to_the_remaining_workflow_time(monkeypatch, clock, progress, agent_context):
    agent_context["_workflow_deadline"] = WorkflowDeadline.start(total_seconds=40, finalization_reserve_seconds=0)
    _install_sleep(monkeypatch, clock)

    result = json.loads(await _tool(create_agent_follow_up_tools(), WAIT_TOOL_NAME).ainvoke({"seconds": 60}))

    assert result["success"] is True
    assert 5 <= result["waited_seconds"] <= 10

    agent_context["_workflow_deadline"] = WorkflowDeadline.start(total_seconds=20, finalization_reserve_seconds=0)
    refused = json.loads(await _tool(create_agent_follow_up_tools(), WAIT_TOOL_NAME).ainvoke({"seconds": 60}))
    assert refused["success"] is False


@pytest.mark.asyncio
async def test_canceling_a_wait_unpauses_and_propagates(monkeypatch, clock, progress, agent_context):
    deadline = WorkflowDeadline.start(total_seconds=10_000, finalization_reserve_seconds=0)
    agent_context["_workflow_deadline"] = deadline

    async def _canceled_sleep(seconds):
        raise asyncio.CancelledError()

    monkeypatch.setattr(tool_module, "asyncio", SimpleNamespace(sleep=_canceled_sleep))

    with pytest.raises(asyncio.CancelledError):
        await _tool(create_agent_follow_up_tools(), WAIT_TOOL_NAME).ainvoke({"seconds": 60})

    assert deadline.is_paused is False
    assert [call["status"] for call in progress] == ["waiting", "active"]


@pytest.mark.asyncio
async def test_schedule_persists_a_follow_up_for_the_chain(repository, agent_context):
    tools = create_agent_follow_up_tools(
        agent_task_id="task-2",
        root_task_id="root-1",
        repository_provider=lambda: repository,
    )
    before = datetime.now(timezone.utc)

    result = json.loads(
        await _tool(tools, SCHEDULE_TOOL_NAME).ainvoke(
            {"delay_minutes": 0, "check_instructions": "  Check the deploy status  ", "reason": "rollout"}
        )
    )

    assert result["success"] is True
    assert result["delay_minutes"] == 1
    stored = await repository.get_follow_up(result["follow_up_id"])
    assert stored["root_task_id"] == "root-1"
    assert stored["source_agent_task_id"] == "task-2"
    assert stored["instructions"] == "Check the deploy status"
    due_at = datetime.fromisoformat(stored["due_at"])
    assert before + timedelta(seconds=59) <= due_at <= datetime.now(timezone.utc) + timedelta(seconds=61)


@pytest.mark.asyncio
async def test_schedule_uses_the_task_as_root_and_validates_input(repository, agent_context):
    tools = create_agent_follow_up_tools(repository_provider=lambda: repository)
    schedule = _tool(tools, SCHEDULE_TOOL_NAME)

    empty = json.loads(await schedule.ainvoke({"delay_minutes": 10, "check_instructions": "   "}))
    too_long = json.loads(await schedule.ainvoke({"delay_minutes": 10, "check_instructions": "x" * 4001}))
    capped = json.loads(await schedule.ainvoke({"delay_minutes": 10**9, "check_instructions": "Check again"}))

    assert empty["success"] is False
    assert too_long["success"] is False
    assert capped["delay_minutes"] == 7 * 24 * 60
    assert (await repository.get_follow_up(capped["follow_up_id"]))["root_task_id"] == "task-1"


@pytest.mark.asyncio
async def test_schedule_without_a_task_context_refuses(repository):
    tools = create_agent_follow_up_tools(repository_provider=lambda: repository)

    result = json.loads(await _tool(tools, SCHEDULE_TOOL_NAME).ainvoke({"delay_minutes": 5, "check_instructions": "Check"}))

    assert result["success"] is False


@pytest.mark.asyncio
async def test_schedule_limit_returns_a_structured_refusal(repository, agent_context):
    tools = create_agent_follow_up_tools(repository_provider=lambda: repository)
    schedule = _tool(tools, SCHEDULE_TOOL_NAME)
    for _ in range(5):
        assert json.loads(await schedule.ainvoke({"delay_minutes": 5, "check_instructions": "Check"}))["success"] is True

    refused = json.loads(await schedule.ainvoke({"delay_minutes": 5, "check_instructions": "Check"}))

    assert refused["success"] is False
    assert "pending follow-ups" in refused["error"]


@pytest.mark.asyncio
async def test_cancel_tool_cancels_pending_follow_ups(repository, agent_context):
    tools = create_agent_follow_up_tools(repository_provider=lambda: repository)
    await _tool(tools, SCHEDULE_TOOL_NAME).ainvoke({"delay_minutes": 5, "check_instructions": "Check"})

    result = json.loads(await _tool(tools, CANCEL_TOOL_NAME).ainvoke({"reason": "user said stop"}))

    assert result == {"success": True, "canceled_follow_ups": 1}
    rows = await repository.list_for_root("task-1")
    assert rows[0]["status"] == "canceled"
    assert "user said stop" in rows[0]["error_message"]


def test_constrained_tasks_get_only_the_wait_tool():
    assert [item.name for item in create_agent_follow_up_tools(include_durable=False)] == [WAIT_TOOL_NAME]


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def _registered_tool_map(**factory_fields):
    tools, tool_map, warnings = [], {}, []
    factory = SimpleNamespace(logger=_Logger(), profile=None, current_agent_task_id="task-1", current_root_task_id="root-1", **factory_fields)
    register_optional_tools(factory, tools, tool_map, warnings)
    assert not any("follow-up tools" in warning for warning in warnings)
    return tool_map


def test_registry_adds_follow_up_tools_and_respects_child_constraints():
    full = _registered_tool_map()
    constrained = _registered_tool_map(allow_child_interaction_tools=False)

    assert {f"follow_up.{name}" for name in (WAIT_TOOL_NAME, SCHEDULE_TOOL_NAME, CANCEL_TOOL_NAME)} <= set(full)
    assert f"follow_up.{WAIT_TOOL_NAME}" in constrained
    assert f"follow_up.{SCHEDULE_TOOL_NAME}" not in constrained
    assert f"follow_up.{CANCEL_TOOL_NAME}" not in constrained


def test_follow_up_tools_belong_to_the_schedule_family():
    for name in (WAIT_TOOL_NAME, SCHEDULE_TOOL_NAME, CANCEL_TOOL_NAME, "create_scheduled_agent_task_from_prompt"):
        assert family_names_for_tool_name(name) == ["schedule"]


class _FollowUpRepository:
    def __init__(self):
        self.calls = []

    async def cancel_pending_for_root(self, root_task_id, *, reason):
        self.calls.append((root_task_id, reason))
        return 2


@pytest.mark.asyncio
async def test_durable_chain_cancel_cancels_pending_follow_ups():
    repository = _FollowUpRepository()
    record = SimpleNamespace(id="task-2", root_task_id="root-1", status="completed")

    async def _get_agent_task(agent_task_id):
        return record

    async def _get_agent_task_chain(root_task_id):
        return [record]

    async def _cancel_agent_tasks_if_active(*, agent_task_ids, result_data):
        return []

    db_service = SimpleNamespace(
        agent_task_follow_up_repository=repository,
        get_agent_task=_get_agent_task,
        get_agent_task_chain=_get_agent_task_chain,
        cancel_agent_tasks_if_active=_cancel_agent_tasks_if_active,
    )
    service = AgentTaskSubmissionService(agent_task_orchestrator=None, db_service=db_service)

    result = await service.cancel_agent_task_durably("task-2", "user_canceled")

    assert result["root_task_id"] == "root-1"
    assert repository.calls == [("root-1", "Task chain canceled")]


@pytest.mark.asyncio
async def test_follow_up_cancel_hook_tolerates_missing_or_broken_repositories():
    without_repository = AgentTaskSubmissionService(agent_task_orchestrator=None, db_service=SimpleNamespace())
    with_mock = AgentTaskSubmissionService(agent_task_orchestrator=None, db_service=MagicMock())

    assert await without_repository._retire_interrupted_task_waits(root_task_id="root-1", agent_task_ids=["task-1"]) is None
    assert await with_mock._retire_interrupted_task_waits(root_task_id="root-1", agent_task_ids=["task-1"]) is None
