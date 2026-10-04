"""A batched ``load_tool_family`` call that newly loads families must end the executor pass."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool

from api.services.agent_processing.lifecycle.execution_graph.staged_agent_executor import (
    StagedAgentExecutor,
    batched_family_load_observation,
)


def _loader_observation(newly_loaded: list[str]) -> str:
    return json.dumps({"loaded_families": ["file"], "newly_loaded_families": newly_loaded})


def _executor(planned_steps: list[Any], calls: list[str]) -> StagedAgentExecutor:
    async def load_tool_family(family_names: list[str]) -> str:
        calls.append("load_tool_family")
        return _loader_observation([name for name in family_names if name == "file"])

    async def browser_tabs(action: str) -> str:
        calls.append("browser_tabs")
        return "tabs listed"

    async def shell_command(command: str) -> str:
        calls.append("shell_command")
        return "ran"

    tools = [
        StructuredTool.from_function(coroutine=load_tool_family, name="load_tool_family", description="load", return_direct=True),
        StructuredTool.from_function(coroutine=browser_tabs, name="browser_tabs", description="tabs"),
        StructuredTool.from_function(coroutine=shell_command, name="shell_command", description="shell"),
    ]
    remaining = list(planned_steps)

    def plan(_inputs: dict) -> Any:
        return remaining.pop(0)

    return StagedAgentExecutor(agent=RunnableLambda(plan), tools=tools, return_intermediate_steps=True)


def test_batched_new_family_load_ends_pass_and_keeps_every_completed_call():
    calls: list[str] = []
    executor = _executor(
        [
            [
                AgentAction("load_tool_family", {"family_names": ["file"]}, ""),
                AgentAction("browser_tabs", {"action": "list"}, ""),
            ],
            [AgentAction("shell_command", {"command": "echo late"}, "")],
            AgentFinish({"output": "should not be reached"}, ""),
        ],
        calls,
    )

    result = asyncio.run(executor.ainvoke({"input": "task"}))

    assert calls == ["load_tool_family", "browser_tabs"]
    assert json.loads(result["output"])["newly_loaded_families"] == ["file"]
    assert [step[0].tool for step in result["intermediate_steps"]] == ["load_tool_family", "browser_tabs"]


def test_batched_reload_of_available_family_does_not_end_pass():
    calls: list[str] = []
    executor = _executor(
        [
            [
                AgentAction("load_tool_family", {"family_names": ["browser"]}, ""),
                AgentAction("browser_tabs", {"action": "list"}, ""),
            ],
            AgentFinish({"output": "done"}, ""),
        ],
        calls,
    )

    result = asyncio.run(executor.ainvoke({"input": "task"}))

    assert result["output"] == "done"
    assert calls == ["load_tool_family", "browser_tabs"]


def test_single_new_family_load_still_returns_directly():
    calls: list[str] = []
    executor = _executor(
        [
            AgentAction("load_tool_family", {"family_names": ["file"]}, ""),
            AgentFinish({"output": "should not be reached"}, ""),
        ],
        calls,
    )

    result = asyncio.run(executor.ainvoke({"input": "task"}))

    assert calls == ["load_tool_family"]
    assert json.loads(result["output"])["newly_loaded_families"] == ["file"]


def test_batched_family_load_observation_ignores_malformed_and_non_loader_steps():
    loader = AgentAction("load_tool_family", {}, "")
    other = AgentAction("browser_tabs", {}, "")

    assert batched_family_load_observation([(loader, _loader_observation(["file"]))]) is None
    assert batched_family_load_observation([(loader, "not json"), (other, "ok")]) is None
    assert batched_family_load_observation([(other, _loader_observation(["file"])), (other, "ok")]) is None
    assert batched_family_load_observation([(loader, {"newly_loaded_families": ["email"]}), (other, "ok")]) == {
        "newly_loaded_families": ["email"]
    }
