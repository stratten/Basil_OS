"""The system prompt and bound tools must not change when only the clock moves, so the provider's prompt cache keeps matching."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from api.services.agent_processing.lifecycle.execution_graph import system_prompts
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery import prefix_fingerprint


class _Args(BaseModel):
    text: str = ""


def _tool(name: str) -> StructuredTool:
    async def _run(text: str = "") -> str:
        return "ok"

    return StructuredTool.from_function(coroutine=_run, name=name, description=f"{name} tool", args_schema=_Args)


def _stub_sections(monkeypatch) -> None:
    monkeypatch.setattr(system_prompts, "build_working_memory_prompt_section", lambda: "\n\nWORKING MEMORY:\nnone\n")
    monkeypatch.setattr(system_prompts, "build_skill_catalog_prompt_section", lambda: "\n\nSKILLS:\nnone\n")
    monkeypatch.setattr(system_prompts, "build_screen_context_prompt_section", lambda: "\n\nSCREEN:\nnone\n")


def test_system_prompt_is_identical_across_calls_and_has_no_clock(monkeypatch):
    _stub_sections(monkeypatch)

    first = system_prompts.get_agent_system_prompt(user_profile_context="Test User")
    second = system_prompts.get_agent_system_prompt(user_profile_context="Test User")

    assert first == second
    assert "Current time:" not in first
    assert "Current date:" not in first
    assert "{current_time}" not in first and "{current_date}" not in first


def test_runtime_context_carries_date_time_communication_and_skill():
    moment = datetime(2026, 10, 13, 10, 1, 44, tzinfo=timezone.utc)

    block = system_prompts.build_turn_runtime_context(
        communication_context_section="\n\nCOMMUNICATION:\nx\n",
        preloaded_skill_section="\n\nSELECTED SAVED SKILL:\nbody\n",
        now=moment,
    )

    assert "Current date: Tuesday, October 13, 2026" in block
    assert "Current time: 10:01:44 UTC" in block
    assert "COMMUNICATION:" in block
    assert "SELECTED SAVED SKILL:" in block


def test_runtime_context_differs_when_only_the_clock_differs():
    early = system_prompts.build_turn_runtime_context(now=datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc))
    late = system_prompts.build_turn_runtime_context(now=datetime(2026, 10, 13, 10, 5, 0, tzinfo=timezone.utc))

    assert early != late


def test_prefix_fingerprint_changes_with_tools_but_not_with_message_content():
    tools = [_tool("alpha")]
    base = SimpleNamespace(system_prompt="You are Basil.", system_message=None, tools=tools, messages=["one"])
    same_prefix = SimpleNamespace(system_prompt="You are Basil.", system_message=None, tools=tools, messages=["one", "two"])
    more_tools = SimpleNamespace(system_prompt="You are Basil.", system_message=None, tools=[*tools, _tool("beta")], messages=["one"])
    new_prompt = SimpleNamespace(system_prompt="You are Basil at 10:01:44.", system_message=None, tools=tools, messages=["one"])

    assert prefix_fingerprint(base) == prefix_fingerprint(same_prefix)
    assert prefix_fingerprint(base) != prefix_fingerprint(more_tools)
    assert prefix_fingerprint(base) != prefix_fingerprint(new_prompt)


def test_strip_runtime_context_returns_only_the_request():
    block = system_prompts.build_turn_runtime_context(now=datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc))

    assert system_prompts.strip_runtime_context(f"{block}\n\nPaint the wall") == "Paint the wall"
    assert system_prompts.strip_runtime_context("Paint the wall") == "Paint the wall"
