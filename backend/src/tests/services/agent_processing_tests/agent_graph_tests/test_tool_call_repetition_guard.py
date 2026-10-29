"""Tests for the centralized tool-call repetition guard."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_call_repetition_guard import (
    REPAIR_OBSERVATION_REPEAT_COUNT,
    STOP_REPEAT_COUNT,
    RepeatedInvalidToolCallStop,
    RepetitionGuardedTool,
    build_tool_call_signature,
    classify_invalid_tool_observation,
    record_invalid_tool_call,
    wrap_tools_with_repetition_guard,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_input_normalization import (
    normalize_structured_tool_args_schema,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    get_current_agent_context,
    reset_current_agent_context,
    set_current_agent_context,
)


_MISSING_ACTION_OBSERVATION = json.dumps(
    {
        "success": False,
        "error": "browser_interact requires an action.",
        "valid_actions": ["click", "fill", "select", "navigate", "scroll", "wait"],
    },
    ensure_ascii=False,
)

_VALIDATION_OBSERVATION = (
    "Tool input validation failed for field(s): arguments. "
    "Pass each argument as a native JSON value (for object arguments send a "
    "JSON object, not a quoted JSON string), then call the tool again."
)


class FakeInteractInput(BaseModel):
    action: Optional[str] = None
    selector: Optional[str] = None
    value: Optional[str] = None
    color: Optional[str] = None
    password: Optional[str] = None


class StringListInput(BaseModel):
    items: List[str]


@pytest.fixture(autouse=True)
def ledger_observer(monkeypatch):
    calls = []

    async def capture_observation(self, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        ToolLedgerCaptureCoordinator,
        "capture_observation",
        capture_observation,
    )
    return calls


def _fixed_observation_tool(observation: str, name: str = "browser_interact") -> StructuredTool:
    async def _impl(**kwargs: Any) -> str:
        return observation

    return StructuredTool.from_function(
        func=_impl,
        coroutine=_impl,
        name=name,
        description=f"{name} test tool",
        args_schema=FakeInteractInput,
    )


@contextmanager
def _active_agent_context() -> Iterator[dict[str, Any]]:
    """Bind a fresh agent context for the duration of the block.

    The context must be bound inside the running coroutine so the guard's
    ``get_current_agent_context()`` reads (and mutates) the same dict across
    repeated tool invocations, mirroring how the executor binds it per pass.
    """

    # Seed a non-empty context: get_current_agent_context() returns
    # ``_current_agent_context.get() or {}``, so an empty dict would be falsy
    # and yield a throwaway dict on every read. A real agent pass always binds
    # a populated context (agent_task_id, etc.), which is what we mirror here.
    context: dict[str, Any] = {"agent_task_id": "test-task"}
    token = set_current_agent_context(context)
    try:
        yield get_current_agent_context()
    finally:
        reset_current_agent_context(token)


def test_classifies_browser_interact_missing_action_from_valid_actions_payload():
    diagnostic = classify_invalid_tool_observation(
        "browser_interact", {"color": "green"}, _MISSING_ACTION_OBSERVATION
    )

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "missing_action"
    assert diagnostic["input_keys"] == ["color"]
    assert "green" not in json.dumps(diagnostic)


def test_does_not_classify_successful_tool_output():
    observation = json.dumps({"success": True, "result": "ok"})

    assert classify_invalid_tool_observation("browser_interact", {}, observation) is None


def test_does_not_classify_operational_browser_failures():
    operational_observations = [
        json.dumps({"success": False, "error": "Element not found for selector '#x'."}),
        json.dumps({"success": False, "error": "Invalid response from browser"}),
        json.dumps(
            {"success": False, "error": "Browser denied JavaScript execution permission."}
        ),
        json.dumps({"success": False, "error": "Operation timed out after 30s."}),
    ]

    for observation in operational_observations:
        assert (
            classify_invalid_tool_observation("browser_interact", {"action": "click"}, observation)
            is None
        )


def test_classifies_validation_handler_observation_without_raw_values():
    diagnostic = classify_invalid_tool_observation(
        "load_tool_family", {"arguments": "secret-payload"}, _VALIDATION_OBSERVATION
    )

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "validation_error"
    assert diagnostic["validation_fields"] == ["arguments"]
    assert "secret-payload" not in json.dumps(diagnostic)


def test_classifies_missing_required_argument():
    observation = json.dumps(
        {"success": False, "action": "fill", "error": "Action 'fill' requires a 'value' parameter."}
    )

    diagnostic = classify_invalid_tool_observation(
        "browser_interact", {"action": "fill", "selector": "#x"}, observation
    )

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "missing_required_argument"


@pytest.mark.asyncio
async def test_repeated_invalid_calls_return_guard_observation_then_stop():
    tool = wrap_tools_with_repetition_guard([_fixed_observation_tool(_MISSING_ACTION_OBSERVATION)])[0]

    with _active_agent_context():
        # Counts 1 and 2 return the tool's own output unchanged.
        for _ in range(REPAIR_OBSERVATION_REPEAT_COUNT - 1):
            result = await tool.ainvoke({"color": "green"})
            assert json.loads(result).get("guarded") is None

        # Count 3 (the repair threshold) returns the stronger guarded observation.
        repair_result = await tool.ainvoke({"color": "green"})
        repair_payload = json.loads(repair_result)
        assert repair_payload["guarded"] is True
        assert repair_payload["repeat_count"] == REPAIR_OBSERVATION_REPEAT_COUNT
        assert repair_payload["next_actions"]

        # Counts 4 and 5 remain guarded but do not yet stop the run.
        for _ in range(STOP_REPEAT_COUNT - REPAIR_OBSERVATION_REPEAT_COUNT - 1):
            await tool.ainvoke({"color": "green"})

        # The stop threshold raises the controlled-stop exception.
        with pytest.raises(RepeatedInvalidToolCallStop) as stop_info:
            await tool.ainvoke({"color": "green"})

    assert stop_info.value.repeat_count == STOP_REPEAT_COUNT
    assert stop_info.value.tool_name == "browser_interact"
    assert stop_info.value.agent_output


@pytest.mark.asyncio
async def test_single_and_double_invalid_calls_do_not_stop():
    tool = wrap_tools_with_repetition_guard([_fixed_observation_tool(_MISSING_ACTION_OBSERVATION)])[0]

    with _active_agent_context():
        first = await tool.ainvoke({"color": "green"})
        second = await tool.ainvoke({"color": "green"})

    assert json.loads(first).get("guarded") is None
    assert json.loads(second).get("guarded") is None


@pytest.mark.asyncio
async def test_guard_captures_one_structured_observation_per_invocation(ledger_observer):
    tool = wrap_tools_with_repetition_guard([
        _fixed_observation_tool('{"browser_automation_target": {"browser": "Safari"}}')
    ])[0]

    with _active_agent_context():
        await tool.ainvoke({"action": "inspect"})

    assert len(ledger_observer) == 1
    assert ledger_observer[0]["tool_name"] == "browser_interact"
    assert ledger_observer[0]["observation"].startswith('{"browser_automation_target"')
    assert ledger_observer[0]["invocation_id"].endswith(":1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "observation"),
    [
        ("browser_interact", '{"browser_automation_target": {"browser": "Safari"}}'),
        ("external_catalog", '{"discovery_receipts": [{"id": "connection-1"}]}'),
        ("iterative_work", '{"success": true, "result": {"items": []}}'),
    ],
)
async def test_guard_observes_direct_tool_families_natively(
    ledger_observer,
    tool_name,
    observation,
):
    tool = wrap_tools_with_repetition_guard([
        _fixed_observation_tool(observation, name=tool_name)
    ])[0]

    with _active_agent_context():
        returned = await tool.ainvoke({"action": "inspect"})

    assert returned == observation
    assert ledger_observer[0]["tool_name"] == tool_name
    assert ledger_observer[0]["observation"] == observation


@pytest.mark.asyncio
async def test_different_invalid_input_hashes_do_not_share_counter():
    tool = wrap_tools_with_repetition_guard([_fixed_observation_tool(_MISSING_ACTION_OBSERVATION)])[0]

    with _active_agent_context():
        # Five distinct malformed inputs: none reaches the per-signature repair count.
        for value in ("green", "blue", "red", "teal", "amber"):
            result = await tool.ainvoke({"color": value})
            assert json.loads(result).get("guarded") is None


def test_guard_diagnostics_do_not_store_raw_values():
    diagnostic = classify_invalid_tool_observation(
        "browser_interact", {"password": "secret"}, _MISSING_ACTION_OBSERVATION
    )
    assert diagnostic is not None

    agent_context: dict[str, Any] = {}
    record_invalid_tool_call(agent_context, diagnostic)

    serialized = json.dumps(agent_context)
    assert "secret" not in serialized
    assert agent_context["tool_call_repetition_guard_events"]


def test_validation_signatures_separate_by_field_list():
    signature_arguments = build_tool_call_signature(
        "load_tool_family", {"arguments": "x"}, "validation_error", validation_fields=["arguments"]
    )
    signature_family = build_tool_call_signature(
        "load_tool_family", {"arguments": "x"}, "validation_error", validation_fields=["family_names"]
    )

    assert signature_arguments != signature_family


@pytest.mark.asyncio
async def test_wrapped_tool_preserves_handle_validation_error():
    async def _echo_items(items: List[str]) -> list[str]:
        return items

    base_tool = StructuredTool.from_function(
        func=_echo_items,
        coroutine=_echo_items,
        name="load_tool_family",
        description="list tool",
        args_schema=StringListInput,
    )
    normalize_structured_tool_args_schema(base_tool)
    handler = base_tool.handle_validation_error

    wrapped = wrap_tools_with_repetition_guard([base_tool])[0]

    assert isinstance(wrapped, RepetitionGuardedTool)
    assert wrapped.handle_validation_error is handler

    context: dict[str, Any] = {}
    token = set_current_agent_context(context)
    try:
        result = await wrapped.ainvoke({"items": '{"family": "browser"}'})
    finally:
        reset_current_agent_context(token)

    assert "validation failed" in result


def test_nonconforming_objects_are_left_unchanged():
    sentinel = object()

    wrapped = wrap_tools_with_repetition_guard([sentinel])

    assert wrapped == [sentinel]


def test_already_wrapped_tools_are_not_double_wrapped():
    wrapped_once = wrap_tools_with_repetition_guard(
        [_fixed_observation_tool(_MISSING_ACTION_OBSERVATION)]
    )
    wrapped_twice = wrap_tools_with_repetition_guard(wrapped_once)

    assert wrapped_twice[0] is wrapped_once[0]


def test_ledger_capture_flags_validation_failure_text_as_not_succeeded():
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
        _is_recognized_invalid_tool_call,
        _opaque_observation_evidence,
    )

    assert _is_recognized_invalid_tool_call(
        tool_name="shell_service_execute_command",
        tool_input={"color": "green"},
        observation=_VALIDATION_OBSERVATION,
    ) is True

    evidence = _opaque_observation_evidence(
        tool_name="shell_service_execute_command",
        observation=_VALIDATION_OBSERVATION,
        error=None,
        succeeded=False,
    )
    assert evidence["success"] is False


def test_ledger_capture_still_marks_genuine_text_result_as_succeeded():
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
        _is_recognized_invalid_tool_call,
    )

    assert _is_recognized_invalid_tool_call(
        tool_name="shell_service_execute_command",
        tool_input={"command": "ls"},
        observation="total 0\ndrwxr-xr-x  2 user  staff  64 Jan 1 00:00 .",
    ) is False


@pytest.mark.asyncio
async def test_guard_returns_tool_message_when_invoked_as_a_tool_call():
    from langchain_core.messages import ToolMessage

    tool = wrap_tools_with_repetition_guard([_fixed_observation_tool("page loaded")])[0]
    with _active_agent_context():
        result = await tool.ainvoke(
            {
                "name": "browser_interact",
                "args": {"action": "click"},
                "id": "call-1",
                "type": "tool_call",
            }
        )

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "call-1"
    assert result.name == "browser_interact"
    assert result.content == "page loaded"


@pytest.mark.asyncio
async def test_guard_returns_raw_observation_without_tool_call_id():
    tool = wrap_tools_with_repetition_guard([_fixed_observation_tool("page loaded")])[0]
    with _active_agent_context():
        result = await tool.ainvoke({"action": "click"})

    assert result == "page loaded"


@pytest.mark.asyncio
async def test_guard_wraps_repair_observation_in_tool_message():
    from langchain_core.messages import ToolMessage

    tool = wrap_tools_with_repetition_guard([_fixed_observation_tool(_MISSING_ACTION_OBSERVATION)])[0]
    results = []
    with _active_agent_context():
        for index in range(REPAIR_OBSERVATION_REPEAT_COUNT):
            results.append(
                await tool.ainvoke(
                    {
                        "name": "browser_interact",
                        "args": {"color": "green"},
                        "id": f"call-{index}",
                        "type": "tool_call",
                    }
                )
            )

    assert all(isinstance(result, ToolMessage) for result in results)
    assert results[-1].tool_call_id == f"call-{REPAIR_OBSERVATION_REPEAT_COUNT - 1}"
    assert results[-1].content != _MISSING_ACTION_OBSERVATION
