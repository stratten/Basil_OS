"""Loop control for external_catalog: nested envelope fields are recovered, repeated invalid calls are counted, and an identical call returning an identical result is stopped."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_call_repetition_guard import (
    REPAIR_OBSERVATION_REPEAT_COUNT,
    STOP_REPEAT_COUNT,
    RepeatedInvalidToolCallStop,
    classify_identical_result_call,
    classify_invalid_tool_observation,
    wrap_tools_with_repetition_guard,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    get_current_agent_context,
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.external_services import external_catalog_tool

_INVALID_ENVELOPE = json.dumps(
    {
        "ok": False,
        "error": {
            "kind": "invalid_arguments",
            "message": "call_tool requires connection_id and tool_name",
            "retryable": False,
            "user_action_required": None,
            "raw": {},
        },
    }
)
_NOT_FOUND_ENVELOPE = json.dumps(
    {"ok": False, "error": {"kind": "not_found", "message": "No connection basil-gmail-api", "retryable": False, "user_action_required": None, "raw": {}}}
)
_EMPTY_RESULT = json.dumps({"ok": True, "result": {"content": "Found 0 thread(s)"}})
_NESTED_INPUT = {
    "action": "call_tool",
    "arguments": {"connection_id": "abc", "server_url": "https://x", "tool_name": "search_threads"},
}


class CatalogInput(BaseModel):
    action: str
    query: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None


@pytest.fixture(autouse=True)
def ledger_observer(monkeypatch):
    async def capture_observation(self, **kwargs):
        return None

    monkeypatch.setattr(ToolLedgerCaptureCoordinator, "capture_observation", capture_observation)


def _catalog_tool(results: list[str], name: str = "external_catalog") -> StructuredTool:
    remaining = list(results)

    async def _impl(**kwargs: Any) -> str:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return StructuredTool.from_function(
        func=_impl, coroutine=_impl, name=name, description="catalog test tool", args_schema=CatalogInput
    )


@contextmanager
def _active_agent_context() -> Iterator[dict[str, Any]]:
    token = set_current_agent_context({"agent_task_id": "test-task"})
    try:
        yield get_current_agent_context()
    finally:
        reset_current_agent_context(token)


def _call(index: int, query: str = "in:inbox", name: str = "external_catalog") -> dict[str, Any]:
    return {"name": name, "args": {"action": "call_tool", "query": query}, "id": f"call-{index}", "type": "tool_call"}


# --- classification of the ok:false envelope ---------------------------------------------------


def test_invalid_arguments_envelope_is_classified_as_a_guardable_invalid_call():
    diagnostic = classify_invalid_tool_observation("external_catalog", _NESTED_INPUT, _INVALID_ENVELOPE)

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "missing_required_argument"
    assert "call_tool requires" in diagnostic["error"]
    assert "abc" not in json.dumps(diagnostic)


def test_invalid_arguments_envelope_without_a_requires_phrase_still_counts():
    observation = json.dumps({"ok": False, "error": {"kind": "invalid_arguments", "message": "Unknown action 'x'"}})

    diagnostic = classify_invalid_tool_observation("external_catalog", {"action": "x"}, observation)

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "invalid_arguments"


@pytest.mark.parametrize(
    "observation",
    [
        _NOT_FOUND_ENVELOPE,
        _EMPTY_RESULT,
        json.dumps({"ok": False, "error": {"kind": "schema_required", "message": "inspect the schema", "retryable": True}}),
        json.dumps({"ok": False, "error": {"kind": "auth_expired", "message": "reconnect"}}),
        json.dumps({"ok": False, "error": "invalid_arguments"}),
        json.dumps({"ok": True, "error": {"kind": "invalid_arguments", "message": "x"}}),
    ],
)
def test_other_envelopes_are_not_classified_as_invalid_calls(observation):
    assert classify_invalid_tool_observation("external_catalog", {"action": "call_tool"}, observation) is None


def test_existing_success_false_shape_is_still_classified():
    observation = json.dumps({"success": False, "error": "call_tool requires connection_id and tool_name"})

    diagnostic = classify_invalid_tool_observation("external_catalog", {}, observation)

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "missing_required_argument"


# --- identical-result classification -----------------------------------------------------------


def test_identical_result_is_classified_only_for_opted_in_tools():
    assert classify_identical_result_call("external_catalog", {"a": 1}, _EMPTY_RESULT) is not None
    assert classify_identical_result_call("shell_service_execute_command", {"a": 1}, _EMPTY_RESULT) is None
    assert classify_identical_result_call("external_catalog", {"a": 1}, None) is None


def test_identical_result_signature_changes_with_the_input_or_the_result():
    base = classify_identical_result_call("external_catalog", {"q": "a"}, _EMPTY_RESULT)
    other_input = classify_identical_result_call("external_catalog", {"q": "b"}, _EMPTY_RESULT)
    other_result = classify_identical_result_call("external_catalog", {"q": "a"}, json.dumps({"ok": True, "result": "3 threads"}))

    assert len({base["signature"], other_input["signature"], other_result["signature"]}) == 3
    assert "Found 0" not in json.dumps(base)


# --- wrapped-tool behavior ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_nested_envelope_errors_are_repaired_then_stopped():
    tool = wrap_tools_with_repetition_guard([_catalog_tool([_INVALID_ENVELOPE])])[0]
    with _active_agent_context():
        results = [await tool.ainvoke(_call(index)) for index in range(REPAIR_OBSERVATION_REPEAT_COUNT)]
        repair = json.loads(results[-1].content)
        assert results[0].content == _INVALID_ENVELOPE
        assert repair["guarded"] is True
        assert repair["invalid_kind"] == "missing_required_argument"

        with pytest.raises(RepeatedInvalidToolCallStop) as stop:
            for index in range(REPAIR_OBSERVATION_REPEAT_COUNT, STOP_REPEAT_COUNT):
                await tool.ainvoke(_call(index))

    assert stop.value.repeat_count == STOP_REPEAT_COUNT


@pytest.mark.asyncio
async def test_identical_empty_results_are_repaired_at_three_and_stopped_at_six():
    tool = wrap_tools_with_repetition_guard([_catalog_tool([_EMPTY_RESULT])])[0]
    with _active_agent_context():
        results = [await tool.ainvoke(_call(index)) for index in range(REPAIR_OBSERVATION_REPEAT_COUNT)]
        assert all(isinstance(result, ToolMessage) for result in results)
        assert results[0].content == _EMPTY_RESULT
        assert results[1].content == _EMPTY_RESULT
        repair = json.loads(results[2].content)
        assert repair["guarded"] is True
        assert repair["invalid_kind"] == "repeated_identical_result"
        assert "same result" in repair["error"]
        assert "Found 0" not in results[2].content
        assert any("change the query" in action for action in repair["next_actions"])

        with pytest.raises(RepeatedInvalidToolCallStop) as stop:
            for index in range(REPAIR_OBSERVATION_REPEAT_COUNT, STOP_REPEAT_COUNT):
                await tool.ainvoke(_call(index))

    assert stop.value.diagnostic["invalid_kind"] == "repeated_identical_result"
    assert "returned the same result" in stop.value.agent_output
    assert "invalid arguments" not in stop.value.agent_output


@pytest.mark.asyncio
async def test_changing_the_query_resets_the_identical_result_count():
    tool = wrap_tools_with_repetition_guard([_catalog_tool([_EMPTY_RESULT])])[0]
    with _active_agent_context():
        for index in range(STOP_REPEAT_COUNT * 2):
            result = await tool.ainvoke(_call(index, query=f"query {index}"))
            assert result.content == _EMPTY_RESULT


@pytest.mark.asyncio
async def test_a_changed_result_for_the_same_input_is_counted_separately():
    changed = json.dumps({"ok": True, "result": "2 threads"})
    results_in_order = [_EMPTY_RESULT, _EMPTY_RESULT, changed, changed]
    tool = wrap_tools_with_repetition_guard([_catalog_tool(results_in_order)])[0]
    with _active_agent_context():
        observed = [(await tool.ainvoke(_call(index))).content for index in range(len(results_in_order))]

    assert observed == results_in_order


@pytest.mark.asyncio
async def test_tools_outside_the_opt_in_list_may_repeat_identical_results():
    tool = wrap_tools_with_repetition_guard([_catalog_tool([_EMPTY_RESULT], name="status_poll")])[0]
    with _active_agent_context():
        for index in range(STOP_REPEAT_COUNT * 2):
            result = await tool.ainvoke(_call(index, name="status_poll"))
            assert result.content == _EMPTY_RESULT


# --- the nested-envelope hoist -----------------------------------------------------------------


@pytest.fixture
def recorded_dispatch(monkeypatch):
    seen: dict[str, Any] = {}

    async def fake_call_tool(connection_id, tool_name, arguments, purpose=None):
        seen["call"] = (connection_id, tool_name, arguments)
        return {"ok": True, "result": {}}

    async def fake_describe_server(connection_id):
        seen["describe"] = connection_id
        return {"ok": True, "result": {}}

    monkeypatch.setattr(external_catalog_tool, "_call_tool", fake_call_tool)
    monkeypatch.setattr(external_catalog_tool, "_describe_server", fake_describe_server)
    return seen


@pytest.mark.asyncio
async def test_envelope_fields_nested_in_arguments_are_hoisted(recorded_dispatch):
    result = json.loads(
        await external_catalog_tool._external_catalog_impl(
            action="call_tool",
            arguments={"connection_id": "abc", "server_url": "https://x", "tool_name": "search_threads", "query": "in:inbox"},
        )
    )

    assert result["ok"] is True
    assert recorded_dispatch["call"] == ("abc", "search_threads", {"query": "in:inbox"})


@pytest.mark.asyncio
async def test_an_inner_arguments_object_is_unwrapped(recorded_dispatch):
    await external_catalog_tool._external_catalog_impl(
        action="call_tool",
        arguments={"connection_id": "abc", "tool_name": "search_threads", "arguments": {"query": "in:inbox"}},
    )

    assert recorded_dispatch["call"] == ("abc", "search_threads", {"query": "in:inbox"})


@pytest.mark.asyncio
async def test_only_the_missing_top_level_field_is_filled(recorded_dispatch):
    await external_catalog_tool._external_catalog_impl(
        action="call_tool", connection_id="top", arguments={"connection_id": "nested", "tool_name": "search_threads", "limit": 5}
    )

    assert recorded_dispatch["call"] == ("top", "search_threads", {"connection_id": "nested", "limit": 5})


@pytest.mark.asyncio
async def test_a_complete_top_level_call_is_left_untouched(recorded_dispatch):
    arguments = {"connection_id": "param-of-the-remote-tool", "tool_name": "also-a-param", "query": "x"}

    await external_catalog_tool._external_catalog_impl(
        action="call_tool", connection_id="abc", tool_name="search_threads", arguments=arguments
    )

    assert recorded_dispatch["call"] == ("abc", "search_threads", arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [None, {}, {"query": "in:inbox"}, {"connection_id": "", "tool_name": "  "}, {"connection_id": 7, "tool_name": ["x"]}],
)
async def test_calls_with_nothing_to_hoist_still_fail_with_the_original_message(recorded_dispatch, arguments):
    result = json.loads(await external_catalog_tool._external_catalog_impl(action="call_tool", arguments=arguments))

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert "call_tool requires connection_id and tool_name" in result["error"]["message"]
    assert "call" not in recorded_dispatch


@pytest.mark.asyncio
async def test_describe_server_recovers_a_nested_connection_id(recorded_dispatch):
    await external_catalog_tool._external_catalog_impl(action="describe_server", arguments={"connection_id": "abc"})

    assert recorded_dispatch["describe"] == "abc"
