"""Regression coverage for Package 3 of the Context Window Overflow Recovery
plan: execute_with_token_retry resuming with a captured-steps digest (instead
of a blind char trim) on context-window overflow, returning a partial result
when retries are exhausted, and leaving the original oversized-initial-prompt
(zero-captured-steps) path on trim_oldest_context unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from api.services.agent_processing.lifecycle.execution_graph.agent_execution_core import (
    execute_with_token_retry,
)
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LocalModelContextWindowExceeded,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_call_repetition_guard import (
    wrap_tools_with_repetition_guard,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    get_current_agent_context,
    reset_current_agent_context,
    set_current_agent_context,
)


class _ToolInput(BaseModel):
    query: str = None


def _fixed_observation_tool(observation: str, name: str = "search_tool") -> StructuredTool:
    """A repetition-guard-wrapped tool, so every call is mirrored into the
    agent context's captured-action log (the same mechanism
    execute_with_token_retry relies on to recover steps after an overflow).
    """

    async def _impl(**kwargs: Any) -> str:
        return observation

    plain_tool = StructuredTool.from_function(
        func=_impl,
        coroutine=_impl,
        name=name,
        description=f"{name} test tool",
        args_schema=_ToolInput,
    )
    return wrap_tools_with_repetition_guard([plain_tool])[0]


@contextmanager
def _active_agent_context() -> Iterator[dict[str, Any]]:
    context: dict[str, Any] = {"agent_task_id": "test-task"}
    token = set_current_agent_context(context)
    try:
        yield get_current_agent_context()
    finally:
        reset_current_agent_context(token)


@pytest.mark.asyncio
async def test_resumes_with_digest_when_local_overflow_follows_captured_steps():
    tool = _fixed_observation_tool("42 results found")

    class _OverflowThenSuccessExecutor:
        def __init__(self) -> None:
            self.calls = 0
            self.seen_inputs: list[str] = []

        async def ainvoke(self, payload: dict, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            self.seen_inputs.append(payload["input"])
            if self.calls == 1:
                await tool.ainvoke({"query": "first search"})
                raise LocalModelContextWindowExceeded(actual_tokens=40000, max_tokens=32768)
            return {"output": "done", "intermediate_steps": []}

    executor = _OverflowThenSuccessExecutor()
    with _active_agent_context():
        result, final_input = await execute_with_token_retry(
            agent_executor=executor,
            user_input="original task text",
            callbacks=[],
        )

    assert result["output"] == "done"
    assert executor.calls == 2
    # The resumed input must carry a digest of the captured step, not a
    # blind character-trimmed copy of the original prompt.
    assert "42 results found" in final_input
    assert "original task text" in final_input


@pytest.mark.asyncio
async def test_exhausted_retries_return_partial_result_instead_of_raising():
    tool = _fixed_observation_tool("partial result data")

    class _AlwaysOverflowExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, payload: dict, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                await tool.ainvoke({"query": "search one"})
            raise LocalModelContextWindowExceeded(actual_tokens=40000, max_tokens=32768)

    executor = _AlwaysOverflowExecutor()
    with _active_agent_context():
        result, _ = await execute_with_token_retry(
            agent_executor=executor,
            user_input="original task text",
            callbacks=[],
            max_trim_retries=2,
        )

    assert executor.calls == 3
    assert result["context_window_exceeded"] == {"actual_tokens": 40000, "max_tokens": 32768}
    assert len(result["intermediate_steps"]) == 1
    assert result["intermediate_steps"][0][1] == "partial result data"
    assert "context window was exceeded" in result["output"]


@pytest.mark.asyncio
async def test_zero_captured_steps_falls_back_to_char_trim_unchanged():
    class _OverflowNoStepsThenSuccessExecutor:
        def __init__(self) -> None:
            self.calls = 0
            self.seen_inputs: list[str] = []

        async def ainvoke(self, payload: dict, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            self.seen_inputs.append(payload["input"])
            if self.calls == 1:
                raise LocalModelContextWindowExceeded(actual_tokens=40000, max_tokens=32768)
            return {"output": "done", "intermediate_steps": []}

    long_input = ("padding " * 10000) + "Current request: Do the actual task now."
    executor = _OverflowNoStepsThenSuccessExecutor()
    with _active_agent_context():
        result, final_input = await execute_with_token_retry(
            agent_executor=executor,
            user_input=long_input,
            callbacks=[],
        )

    assert result["output"] == "done"
    assert executor.calls == 2
    # No steps were captured this pass, so the fallback char-trim path (not
    # the digest path) must have run: the trimmed input is shorter than the
    # original and still ends with the untouched task sentence.
    assert len(final_input) < len(long_input)
    assert final_input.endswith("Do the actual task now.")


@pytest.mark.asyncio
async def test_cloud_provider_regex_detection_path_is_unchanged():
    class _CloudOverflowThenSuccessExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, payload: dict, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("prompt is too long: 203619 tokens > 200000 maximum")
            return {"output": "done", "intermediate_steps": []}

    long_input = ("padding " * 10000) + "Current request: do the actual task now."
    executor = _CloudOverflowThenSuccessExecutor()
    with _active_agent_context():
        result, final_input = await execute_with_token_retry(
            agent_executor=executor,
            user_input=long_input,
            callbacks=[],
        )

    assert result["output"] == "done"
    assert executor.calls == 2
    assert final_input.endswith("do the actual task now.")
    assert len(final_input) < len(long_input)
