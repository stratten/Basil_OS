from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from api import dependencies
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    register_optional_tools,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
    family_names_for_tool_name,
    get_family_names,
)
from api.services.agent_processing.tools.internal_basil_tools.separate_agent_task_tool import (
    SPLIT_ORIGIN_TYPE,
    TOOL_NAME,
    create_start_separate_agent_task_tool,
)


class _Submission:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._result = {"success": True} if result is None else result
        self._error = error

    async def process_agent_task_direct(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


class _Wrapper:
    """Mirrors the authorized-delegation wrapper that exposes the raw service as ``_submission_service``."""

    def __init__(self, inner: _Submission) -> None:
        self._submission_service = inner


@pytest.fixture(autouse=True)
def _parent_task(monkeypatch):
    class AgentTasks:
        async def get_agent_task(self, agent_task_id):
            return SimpleNamespace(accumulated_artifacts={"model_id": "parent-model"})

    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", lambda: SimpleNamespace(agent_task_service=AgentTasks()))


@pytest.fixture(autouse=True)
def _no_application_service(monkeypatch):
    """Keep every test off the real api.main application; tests that need its service set their own."""
    monkeypatch.setitem(sys.modules, "api.main", SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))


def _tool(submission):
    return create_start_separate_agent_task_tool(agent_task_id="source-turn", root_task_id="source-root", submission_service=submission)


async def _call(tool, **kwargs) -> dict:
    return json.loads(await tool.coroutine(**kwargs))


def test_tool_name_is_stable_for_the_family_catalog():
    assert _tool(_Submission()).name == TOOL_NAME == "start_separate_agent_task"


@pytest.mark.asyncio
async def test_submits_a_standalone_task_linked_back_to_the_source_turn():
    submission = _Submission()
    result = await _call(_tool(submission), task_prompt="Reply to Mo about the storage limits.", reference_paths=["/tmp/notes.md"])

    assert result["success"] is True
    assert len(submission.calls) == 1
    call = submission.calls[0]
    assert call["agent_task_id"] == result["agent_task_id"]
    assert call["origin_type"] == SPLIT_ORIGIN_TYPE
    assert call["origin_id"] == "source-turn"
    assert call["model_id"] == "parent-model"
    assert call["reference_paths"] == ["/tmp/notes.md"]
    assert "root_task_id" not in call and "previous_task_id" not in call
    assert call["agent_task"].startswith("Reply to Mo about the storage limits.")
    assert "recall_agent_tasks(scope='detail', task_id='source-turn')" in call["agent_task"]
    assert "chain root source-root" in call["agent_task"]


@pytest.mark.asyncio
async def test_unwraps_the_authorized_delegation_wrapper():
    inner = _Submission()
    result = await _call(_tool(_Wrapper(inner)), task_prompt="Handle the Origami reply separately.")

    assert result["success"] is True
    assert len(inner.calls) == 1
    assert inner.calls[0]["reference_paths"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   \n\t "])
async def test_blank_prompt_is_rejected_without_submitting(blank):
    submission = _Submission()
    result = await _call(_tool(submission), task_prompt=blank)

    assert result["success"] is False
    assert "task_prompt is required" in result["error"]
    assert submission.calls == []


@pytest.mark.asyncio
async def test_retrying_the_same_prompt_in_one_turn_does_not_create_a_second_task():
    submission = _Submission()
    tool = _tool(submission)
    first = await _call(tool, task_prompt="Split off the DLRS storage review.")
    second = await _call(tool, task_prompt="  Split off the DLRS storage review.  ")

    assert second["success"] is True and second["already_started"] is True
    assert second["agent_task_id"] == first["agent_task_id"]
    assert len(submission.calls) == 1


@pytest.mark.asyncio
async def test_a_rejected_submission_is_returned_and_can_be_retried():
    rejecting = _Submission(result={"success": False, "message": "Task was canceled"})
    tool = _tool(rejecting)
    first = await _call(tool, task_prompt="Split off the DLRS storage review.")
    assert first == {"success": False, "error": "Task was canceled"}

    rejecting._result = {"success": True}
    second = await _call(tool, task_prompt="Split off the DLRS storage review.")
    assert second["success"] is True and "already_started" not in second
    assert len(rejecting.calls) == 2


@pytest.mark.asyncio
async def test_a_submission_exception_becomes_a_tool_error_instead_of_failing_the_turn():
    result = await _call(_tool(_Submission(error=RuntimeError("queue unavailable"))), task_prompt="Split off the DLRS storage review.")

    assert result == {"success": False, "error": "queue unavailable"}


@pytest.mark.asyncio
async def test_missing_submission_capability_is_reported():
    result = await _call(_tool(SimpleNamespace()), task_prompt="Split off the DLRS storage review.")

    assert result["success"] is False
    assert "unavailable" in result["error"]
    assert "Do not retry" in result["error"]


def _application_with(monkeypatch, top_level_service):
    """Stand in for api.main so the application's top-level submission service is the one given (or none)."""
    state = SimpleNamespace() if top_level_service is None else SimpleNamespace(agent_task_submission_service=top_level_service)
    monkeypatch.setitem(sys.modules, "api.main", SimpleNamespace(app=SimpleNamespace(state=state)))


@pytest.mark.asyncio
async def test_the_real_delegation_wrapper_and_inner_service_fall_through_to_the_top_level_service(monkeypatch):
    """What a running task is really given: the wrapper around the orchestrator's inner service, which cannot start a standalone task."""
    from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_submission_service import (
        AgentTaskSubmissionService as InnerSubmissionService,
    )
    from api.services.agent_processing.lifecycle.submission.agent_task_processing.authorized_provider_delegation_submission_service import (
        AuthorizedProviderDelegationSubmissionService,
    )

    inner = InnerSubmissionService(
        db_service=SimpleNamespace(), screen_context_service=SimpleNamespace(), routing_service=SimpleNamespace(), processing_service=SimpleNamespace()
    )
    wrapper = AuthorizedProviderDelegationSubmissionService(inner)
    assert not hasattr(inner, "process_agent_task_direct")
    top_level = _Submission()
    _application_with(monkeypatch, top_level)

    result = await _call(_tool(wrapper), task_prompt="Own REQ-2026-0651 through the Speakeasy connection.")

    assert result["success"] is True
    assert len(top_level.calls) == 1
    assert top_level.calls[0]["origin_type"] == SPLIT_ORIGIN_TYPE


@pytest.mark.asyncio
async def test_a_service_that_can_submit_directly_is_used_without_consulting_the_application(monkeypatch):
    given = _Submission()
    application_service = _Submission()
    _application_with(monkeypatch, application_service)

    result = await _call(_tool(given), task_prompt="Split off the DLRS storage review.")

    assert result["success"] is True
    assert len(given.calls) == 1 and application_service.calls == []


@pytest.mark.asyncio
async def test_no_usable_service_anywhere_reports_unavailable_and_logs_what_it_was_given(monkeypatch, caplog):
    _application_with(monkeypatch, None)

    with caplog.at_level("WARNING"):
        result = await _call(_tool(SimpleNamespace()), task_prompt="Split off the DLRS storage review.")

    assert result["success"] is False
    assert "SimpleNamespace" in caplog.text


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def _registered(**factory_fields):
    tools, tool_map, warnings = [], {}, []
    factory = SimpleNamespace(
        logger=_Logger(),
        profile=None,
        current_agent_task_id="source-turn",
        current_root_task_id="source-root",
        agent_task_submission_service=_Submission(),
        **factory_fields,
    )
    register_optional_tools(factory, tools, tool_map, warnings)
    return tools, tool_map, warnings


def test_registry_registers_the_tool_for_a_normal_task():
    tools, tool_map, warnings = _registered()

    assert tool_map["separate_agent_task.start"].name == TOOL_NAME
    assert any(tool.name == TOOL_NAME for tool in tools)
    assert not any("start_separate_agent_task" in warning for warning in warnings)


def test_registry_leaves_the_tool_out_for_constrained_child_tasks():
    tools, tool_map, _ = _registered(allow_delegated_agent=False)

    assert "separate_agent_task.start" not in tool_map
    assert not any(tool.name == TOOL_NAME for tool in tools)


def test_the_tool_has_its_own_family_distinct_from_delegation():
    assert family_names_for_tool_name(TOOL_NAME) == ["separate_task"]
    assert "separate_task" in get_family_names()
    assert family_names_for_tool_name("delegated_agent") == ["delegation"]


@pytest.mark.asyncio
async def test_unknown_parent_model_falls_back_to_the_default_model(monkeypatch):
    class AgentTasks:
        async def get_agent_task(self, agent_task_id):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", lambda: SimpleNamespace(agent_task_service=AgentTasks()))
    submission = _Submission()
    result = await _call(_tool(submission), task_prompt="Split off the DLRS storage review.")

    assert result["success"] is True
    assert submission.calls[0]["model_id"] is None
