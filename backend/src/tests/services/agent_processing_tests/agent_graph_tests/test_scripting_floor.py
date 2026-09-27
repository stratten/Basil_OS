"""Tests for the last-resort scripting floor in the staged executor loop."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_classic.schema import AgentAction

from api.services.agent_processing.lifecycle.execution_graph import staged_execution_loop
from api.services.agent_processing.lifecycle.execution_graph.staged_execution_loop import (
    StagedExecutionRequest,
    run_staged_tool_loading,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.staged_tool_loading_repair import (
    scripting_floor_owed,
)

FLOOR_MARKER = "MANDATORY LAST-RESORT SCRIPTING FLOOR"


def _tool(name: str):
    return SimpleNamespace(name=name, description=f"{name} description", args_schema=None)


def _load_step(family: str):
    action = AgentAction(tool="load_tool_family", tool_input={"family_names": [family]}, log="load")
    observation = json.dumps({"loaded_families": [family], "suggested_families": [family]})
    return (action, observation)


def _ok_step(tool_name: str):
    return (AgentAction(tool=tool_name, tool_input={}, log="work"), "done")


def _failed_step(tool_name: str):
    observation = json.dumps({"success": False, "error": "operation failed"})
    return (AgentAction(tool=tool_name, tool_input={}, log="work"), observation)


def _make_state(context=None):
    return SimpleNamespace(
        context={} if context is None else context,
        available_tools=SimpleNamespace(
            tools=[
                _tool("applescript_service_execute_applescript"),
                _tool("applescript_service_generate_and_execute_applescript"),
                _tool("shell_service_execute_command"),
                _tool("email_service_search_emails"),
            ]
        ),
        selected_skill_section="",
        user_agent_task="inspect the headers of the latest email",
    )


def _make_request(context=None):
    return StagedExecutionRequest(
        langchain_llm=object(),
        state=_make_state(context),
        user_profile_context="",
        communication_context_section="",
        custom_instructions_section="",
        selected_skill_section="",
        live_callbacks=[],
        cancel_event=None,
    )


@pytest.fixture
def stub_executor(monkeypatch):
    calls = {"count": 0, "inputs": []}
    canned: list[dict] = []
    tool_surfaces: list[list[str]] = []

    async def fake_execute(agent_executor, user_input, callbacks, cancel_event):
        calls["count"] += 1
        calls["inputs"].append(user_input)
        index = min(calls["count"] - 1, len(canned) - 1)
        return canned[index], user_input

    def fake_create_agent_executor(*args, **kwargs):
        tools = args[1] if len(args) > 1 else (kwargs.get("tools") or [])
        tool_surfaces.append([str(getattr(item, "name", "") or "") for item in tools])
        return object()

    monkeypatch.setattr(staged_execution_loop, "create_agent_executor", fake_create_agent_executor)
    monkeypatch.setattr(staged_execution_loop, "execute_with_token_retry", fake_execute)
    monkeypatch.setattr(staged_execution_loop, "set_current_agent_context", lambda ctx: object())
    monkeypatch.setattr(staged_execution_loop, "reset_current_agent_context", lambda token: None)
    monkeypatch.setattr(staged_execution_loop, "format_chain_context", lambda state: state.user_agent_task)

    return SimpleNamespace(calls=calls, canned=canned, tool_surfaces=tool_surfaces)


# --- scripting_floor_owed truth table ---------------------------------------

def test_owed_when_specialized_step_failed_and_no_script():
    steps = [_load_step("email"), _failed_step("email_service_search_emails")]
    assert scripting_floor_owed(steps) is True


def test_not_owed_when_scripting_already_attempted():
    steps = [_load_step("email"), _failed_step("applescript_service_execute_applescript")]
    assert scripting_floor_owed(steps) is False


def test_not_owed_on_clean_run():
    steps = [_load_step("email"), _ok_step("email_service_search_emails")]
    assert scripting_floor_owed(steps) is False


def test_owed_on_unavailable_tool_observation():
    action = AgentAction(tool="email_service_read_headers", tool_input={}, log="x")
    steps = [(action, "email_service_read_headers is not a valid tool")]
    assert scripting_floor_owed(steps) is True


def test_not_owed_when_successful_output_merely_mentions_error():
    """A succeeding step whose output text contains the word 'error' (e.g. a log
    summary) must NOT trip the floor: success is the tool's structured flag, not
    keyword-matched content."""
    action = AgentAction(tool="file_service_read_file", tool_input={}, log="x")
    steps = [
        _load_step("file"),
        (action, "Summary: the log contained 3 error lines and a traceback."),
    ]
    assert scripting_floor_owed(steps) is False


# --- loop behavior -----------------------------------------------------------

@pytest.mark.asyncio
async def test_floor_fires_once_when_blocked_and_no_script(stub_executor):
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("email")], "output": ""},
        {"intermediate_steps": [_failed_step("email_service_search_emails")], "output": "I cannot read headers"},
        {"intermediate_steps": [_ok_step("applescript_service_execute_applescript")], "output": "Headers inspected"},
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 3
    assert FLOOR_MARKER in stub_executor.calls["inputs"][2]
    executed = [step[0].tool for step in result.intermediate_steps]
    assert "applescript_service_execute_applescript" in executed
    assert result.agent_output == "Headers inspected"


@pytest.mark.asyncio
async def test_floor_does_not_fire_on_clean_run(stub_executor):
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("email")], "output": ""},
        {"intermediate_steps": [_ok_step("email_service_search_emails")], "output": "Found messages"},
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 2
    assert all(FLOOR_MARKER not in text for text in stub_executor.calls["inputs"])
    assert result.agent_output == "Found messages"


@pytest.mark.asyncio
async def test_floor_does_not_fire_when_script_already_tried(stub_executor):
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("email")], "output": ""},
        {"intermediate_steps": [_failed_step("applescript_service_execute_applescript")], "output": "script failed"},
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 2
    assert all(FLOOR_MARKER not in text for text in stub_executor.calls["inputs"])


@pytest.mark.asyncio
async def test_floor_fires_at_most_once_even_if_forced_pass_fails(stub_executor):
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("email")], "output": ""},
        {"intermediate_steps": [_failed_step("email_service_search_emails")], "output": "cannot"},
        {"intermediate_steps": [_failed_step("applescript_service_execute_applescript")], "output": "script also failed"},
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 3
    assert result.agent_output == "script also failed"
