"""The repetition guard escalates identical ``executable_not_found`` shell failures instead of letting a model retry forever."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_call_repetition_guard import (
    REPAIR_OBSERVATION_REPEAT_COUNT,
    STOP_REPEAT_COUNT,
    RepeatedInvalidToolCallStop,
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
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_command_line_recovery import (
    executable_not_found_message,
)

_WHOLE_LINE = "find /Users/someone/secret-project -type f 2>/dev/null | wc -l"

_EXECUTABLE_NOT_FOUND_OBSERVATION = json.dumps(
    {
        "success": False,
        "result": {
            "success": False,
            "stdout": "",
            "stderr": executable_not_found_message(_WHOLE_LINE),
            "exit_code": -1,
            "error_type": "executable_not_found",
        },
        "error": executable_not_found_message(_WHOLE_LINE),
        "service": "shell_service",
        "method": "execute_command",
    },
    ensure_ascii=False,
)

_NON_DETERMINISTIC_FAILURE_OBSERVATION = json.dumps(
    {
        "success": False,
        "result": {"success": False, "stderr": "ls: /nope: No such file or directory", "exit_code": 1},
        "error": "ls: /nope: No such file or directory",
    },
    ensure_ascii=False,
)


class ShellInput(BaseModel):
    command: str
    args: Optional[List[str]] = None


@pytest.fixture(autouse=True)
def ledger_observer(monkeypatch):
    async def capture_observation(self, **kwargs):
        return None

    monkeypatch.setattr(ToolLedgerCaptureCoordinator, "capture_observation", capture_observation)


def _shell_tool(observation: str) -> StructuredTool:
    async def _impl(**kwargs: Any) -> str:
        return observation

    return StructuredTool.from_function(
        func=_impl,
        coroutine=_impl,
        name="shell_service_execute_command",
        description="shell test tool",
        args_schema=ShellInput,
    )


@contextmanager
def _active_agent_context() -> Iterator[dict[str, Any]]:
    token = set_current_agent_context({"agent_task_id": "test-task"})
    try:
        yield get_current_agent_context()
    finally:
        reset_current_agent_context(token)


def _call(index: int) -> dict[str, Any]:
    return {
        "name": "shell_service_execute_command",
        "args": {"command": _WHOLE_LINE},
        "id": f"call-{index}",
        "type": "tool_call",
    }


def test_classifies_executable_not_found_from_the_shell_envelope():
    diagnostic = classify_invalid_tool_observation(
        "shell_service_execute_command", {"command": _WHOLE_LINE}, _EXECUTABLE_NOT_FOUND_OBSERVATION
    )

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "executable_not_found"
    assert "secret-project" not in json.dumps(diagnostic)


def test_classifies_error_type_reported_at_the_top_level_of_the_payload():
    observation = json.dumps({"success": False, "error_type": "executable_not_found", "stderr": "x"})
    diagnostic = classify_invalid_tool_observation("shell_service_execute_command", {"command": "x y"}, observation)

    assert diagnostic is not None
    assert diagnostic["invalid_kind"] == "executable_not_found"


def test_ordinary_nonzero_exit_is_not_guarded():
    assert (
        classify_invalid_tool_observation(
            "shell_service_execute_command", {"command": "ls", "args": ["/nope"]}, _NON_DETERMINISTIC_FAILURE_OBSERVATION
        )
        is None
    )


def test_successful_shell_result_is_not_guarded():
    observation = json.dumps({"success": True, "result": {"success": True, "stdout": "5\n", "exit_code": 0}})
    assert classify_invalid_tool_observation("shell_service_execute_command", {"command": "ls"}, observation) is None


def test_actionable_message_names_the_contract_and_the_bash_route():
    message = executable_not_found_message(_WHOLE_LINE)

    assert message.startswith("Executable not found: ")
    assert "`args`" in message
    assert "['-lc'" in message
    assert "Do not repeat this exact call" in message


@pytest.mark.asyncio
async def test_third_identical_failure_gets_a_repair_observation_with_next_actions():
    tool = wrap_tools_with_repetition_guard([_shell_tool(_EXECUTABLE_NOT_FOUND_OBSERVATION)])[0]
    results = []
    with _active_agent_context():
        for index in range(REPAIR_OBSERVATION_REPEAT_COUNT):
            results.append(await tool.ainvoke(_call(index)))

    assert all(isinstance(result, ToolMessage) for result in results)
    assert results[0].content == _EXECUTABLE_NOT_FOUND_OBSERVATION
    repair = json.loads(results[-1].content)
    assert repair["guarded"] is True
    assert repair["invalid_kind"] == "executable_not_found"
    assert f"failed {REPAIR_OBSERVATION_REPEAT_COUNT} times with the same error" in repair["error"]
    assert any("bash" in action for action in repair["next_actions"])
    assert "secret-project" not in results[-1].content


@pytest.mark.asyncio
async def test_sixth_identical_failure_stops_the_run_cleanly():
    tool = wrap_tools_with_repetition_guard([_shell_tool(_EXECUTABLE_NOT_FOUND_OBSERVATION)])[0]
    with _active_agent_context():
        for index in range(STOP_REPEAT_COUNT - 1):
            await tool.ainvoke(_call(index))
        with pytest.raises(RepeatedInvalidToolCallStop) as stop:
            await tool.ainvoke(_call(STOP_REPEAT_COUNT - 1))

    assert stop.value.diagnostic["invalid_kind"] == "executable_not_found"
    assert stop.value.repeat_count == STOP_REPEAT_COUNT


@pytest.mark.asyncio
async def test_different_inputs_do_not_share_a_counter():
    tool = wrap_tools_with_repetition_guard([_shell_tool(_EXECUTABLE_NOT_FOUND_OBSERVATION)])[0]
    with _active_agent_context():
        for index in range(STOP_REPEAT_COUNT + 2):
            result = await tool.ainvoke(
                {
                    "name": "shell_service_execute_command",
                    "args": {"command": f"find /tmp/dir-{index} -type f"},
                    "id": f"call-{index}",
                    "type": "tool_call",
                }
            )
            assert result.content == _EXECUTABLE_NOT_FOUND_OBSERVATION
