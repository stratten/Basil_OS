"""Tests for the staged tool-loading executor loop and its termination predicate."""

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


def _tool(name: str):
    return SimpleNamespace(name=name, description=f"{name} description", args_schema=None)


def _load_step(family: str):
    action = AgentAction(tool="load_tool_family", tool_input={"family_names": [family]}, log="load")
    observation = json.dumps({"loaded_families": [family], "suggested_families": [family]})
    return (action, observation)


def _work_step(tool_name: str):
    action = AgentAction(tool=tool_name, tool_input={}, log="work")
    return (action, "done")


def _make_state(context=None):
    return SimpleNamespace(
        context={} if context is None else context,
        available_tools=SimpleNamespace(
            tools=[
                _tool("applescript_service_execute_applescript"),
                _tool("applescript_service_generate_and_execute_applescript"),
                _tool("shell_service_execute_command"),
                _tool("email_service_search_emails"),
                _tool("file_service_prepare_file_by_path"),
                _tool("retrieve_basil_history"),
            ]
        ),
        selected_skill_section="",
        user_agent_task="create a placeholder calendar event",
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
    """Drive the loop with canned per-pass results and record invocations."""
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


@pytest.mark.asyncio
async def test_failure_repro_now_reaches_applescript(stub_executor):
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("automation")], "output": ""},
        {"intermediate_steps": [_load_step("automation")], "output": ""},
        {"intermediate_steps": [_work_step("applescript_service_generate_and_execute_applescript")], "output": "Event created"},
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 3
    assert result.agent_output == "Event created"
    executed_tools = [step[0].tool for step in result.intermediate_steps]
    assert "applescript_service_generate_and_execute_applescript" in executed_tools


@pytest.mark.asyncio
async def test_normal_completion_breaks_after_single_pass(stub_executor):
    stub_executor.canned.append({"intermediate_steps": [], "output": "Here is your answer"})

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 1
    assert result.loaded_families == []
    assert result.agent_output == "Here is your answer"


@pytest.mark.asyncio
async def test_genuine_new_family_continues_without_correction(stub_executor):
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("email")], "output": ""},
        {"intermediate_steps": [_work_step("email_service_search_emails")], "output": "Found messages"},
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 2
    assert result.loaded_families == ["email"]
    assert "REDUNDANT TOOL-FAMILY LOAD DETECTED" not in stub_executor.calls["inputs"][1]


@pytest.mark.asyncio
async def test_redundant_reload_is_bounded_by_pass_budget(stub_executor):
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("automation")], "output": ""},
        {"intermediate_steps": [_load_step("automation")], "output": ""},
        {"intermediate_steps": [_load_step("automation")], "output": ""},
        {"intermediate_steps": [_load_step("automation")], "output": ""},
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 4
    assert result.loaded_families == []
    assert "REDUNDANT TOOL-FAMILY LOAD DETECTED" in stub_executor.calls["inputs"][1]


@pytest.mark.asyncio
async def test_prepared_file_receives_one_source_selection_replan(stub_executor, monkeypatch):
    monkeypatch.setattr(
        "api.services.retrieval.factory.get_unified_retrieval_service",
        lambda: SimpleNamespace(
            catalog=lambda: {
                "sources": [
                    {
                        "source_kind": "meeting",
                        "authority": "primary",
                        "evidence_kind": "observed Basil meeting recording and transcript",
                    }
                ]
            }
        ),
    )
    prepared = {
        "success": True,
        "result": {
            "result_kind": "prepared",
            "file_path": "/tmp/tracking.csv",
            "file_name": "tracking.csv",
            "file_type": "csv",
            "extracted_text": "Call Name on Calendar,Actual meeting",
        },
    }
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("file")], "output": ""},
        {
            "intermediate_steps": [
                (
                    AgentAction(
                        tool="file_service_prepare_file_by_path",
                        tool_input={"path": "/tmp/tracking.csv"},
                        log="prepare",
                    ),
                    json.dumps(prepared),
                )
            ],
            "output": json.dumps(prepared),
        },
        {
            "intermediate_steps": [_work_step("retrieve_basil_history")],
            "output": "Compared the selected local records.",
        },
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 3
    assert "INPUT DISCOVERY HANDOFF:" in stub_executor.calls["inputs"][2]
    assert '"source_kind": "meeting"' in stub_executor.calls["inputs"][2]
    assert "retrieve_basil_history" in stub_executor.tool_surfaces[2]
    assert [step[0].tool for step in result.intermediate_steps][-1] == "retrieve_basil_history"


@pytest.mark.asyncio
async def test_baseline_tools_survive_specialized_family_load(stub_executor):
    """After loading a specialized family, automation/shell fallbacks stay bound."""
    stub_executor.canned.extend([
        {"intermediate_steps": [_load_step("email")], "output": ""},
        {
            "intermediate_steps": [
                _work_step("applescript_service_generate_and_execute_applescript")
            ],
            "output": "Event created",
        },
    ])

    result = await run_staged_tool_loading(_make_request())

    assert stub_executor.calls["count"] == 2
    # Pass 1 is the expanded surface after loading the specialized "email" family.
    expanded_surface = stub_executor.tool_surfaces[1]
    assert "applescript_service_generate_and_execute_applescript" in expanded_surface
    assert "applescript_service_execute_applescript" in expanded_surface
    assert "shell_service_execute_command" in expanded_surface
    assert "email_service_search_emails" in expanded_surface
    executed_tools = [step[0].tool for step in result.intermediate_steps]
    assert "applescript_service_generate_and_execute_applescript" in executed_tools


@pytest.mark.asyncio
async def test_delegated_supervision_binds_delegated_agent_without_family_load(stub_executor):
    request = _make_request(
        context={"delegated_supervision": {"delegated_agent_run_id": "delegated-run"}}
    )
    request.state.available_tools.tools.extend(
        [_tool("delegated_agent"), _tool("provider_catalog")]
    )
    stub_executor.canned.append(
        {
            "intermediate_steps": [_work_step("delegated_agent")],
            "output": "Delegated child settled",
        }
    )

    result = await run_staged_tool_loading(request)

    assert stub_executor.calls["count"] == 1
    assert result.loaded_families == ["delegation"]
    assert "delegated_agent" in stub_executor.tool_surfaces[0]
    assert "provider_catalog" not in stub_executor.tool_surfaces[0]


