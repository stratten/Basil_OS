"""Tests for per-call model recovery inside the inner agent loop."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import api.services.model_usage_service as model_usage_service
from api.services.agent_processing.lifecycle.execution_graph.agent_execution_core import (
    ModelUnavailableBeforeFirstResponse,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery import (
    COMPACTED_TOOL_RESULT,
    EMPTY_GENERATION_MESSAGE,
    MAX_COMPACTION_LEVEL,
    THREAD_COMPACTION_LEVEL,
    TRANSIENT_RETRIES,
    AgentRunFlags,
    ModelRecoveryMiddleware,
    compact_messages,
    max_compaction_level,
)
from api.services.agent_processing.lifecycle.execution_graph.conversation_turns import (
    RECAP_HEADER,
    is_turn_input,
    mark_turn_input,
)
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LocalModelContextWindowExceeded,
)
from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError


class StubRequest:
    def __init__(self, messages):
        self.messages = list(messages)

    def override(self, **kwargs):
        return StubRequest(kwargs.get("messages", self.messages))


def _conversation_with_tool_results(count: int, task_chars: int = 50_000):
    messages = [HumanMessage(content="x" * task_chars)]
    for index in range(count):
        call_id = f"call-{index}"
        messages.append(
            AIMessage(content="", tool_calls=[{"name": "shell_service_execute_command", "args": {}, "id": call_id, "type": "tool_call"}])
        )
        messages.append(ToolMessage(content=f"result-{index}", tool_call_id=call_id))
    return messages


def _middleware(flags=None, completed_model_calls=1):
    middleware = ModelRecoveryMiddleware(flags or AgentRunFlags(), completed_model_calls=completed_model_calls)
    middleware.backoff_base_seconds = 0
    return middleware


def _tool_contents(messages):
    return [message.content for message in messages if isinstance(message, ToolMessage)]


def test_compaction_level_one_keeps_three_recent_tool_results():
    compacted = compact_messages(_conversation_with_tool_results(5), 1)

    assert _tool_contents(compacted) == [
        COMPACTED_TOOL_RESULT,
        COMPACTED_TOOL_RESULT,
        "result-2",
        "result-3",
        "result-4",
    ]
    assert compacted[0].content == "x" * 50_000


def test_compaction_level_two_keeps_one_result_and_trims_task_text():
    compacted = compact_messages(_conversation_with_tool_results(3), 2, actual_tokens=9_000, max_tokens=8_000)

    assert _tool_contents(compacted) == [COMPACTED_TOOL_RESULT, COMPACTED_TOOL_RESULT, "result-2"]
    assert len(compacted[0].content) < 50_000


def test_compaction_never_mutates_the_original_messages():
    original = _conversation_with_tool_results(5)

    compact_messages(original, 2, actual_tokens=9_000, max_tokens=8_000)

    assert _tool_contents(original) == [f"result-{index}" for index in range(5)]


@pytest.mark.asyncio
async def test_typed_transient_error_retries_then_succeeds():
    attempts = []

    async def handler(_request):
        attempts.append(1)
        if len(attempts) <= TRANSIENT_RETRIES:
            raise TransientModelError("busy")
        return AIMessage(content="ok")

    response = await _middleware().awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)

    assert response.content == "ok"
    assert len(attempts) == TRANSIENT_RETRIES + 1


@pytest.mark.asyncio
async def test_transient_error_reraises_after_retries():
    attempts = []

    async def handler(_request):
        attempts.append(1)
        raise TransientModelError("still busy")

    with pytest.raises(TransientModelError):
        await _middleware().awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)
    assert len(attempts) == TRANSIENT_RETRIES + 1


@pytest.mark.asyncio
async def test_empty_generation_retries_once_then_succeeds():
    attempts = []
    flags = AgentRunFlags()

    async def handler(_request):
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("No generation chunks were returned")
        return AIMessage(content="ok")

    response = await _middleware(flags).awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)

    assert response.content == "ok"
    assert flags.empty_generation_failure is False


@pytest.mark.asyncio
async def test_second_empty_generation_ends_with_controlled_message():
    flags = AgentRunFlags()

    async def handler(_request):
        raise ValueError("No generation chunks were returned")

    response = await _middleware(flags).awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)

    assert response.content == EMPTY_GENERATION_MESSAGE
    assert flags.empty_generation_failure is True
    assert flags.terminal() is True


@pytest.mark.asyncio
async def test_context_overflow_compacts_then_succeeds():
    seen_requests = []

    async def handler(request):
        seen_requests.append(request)
        if len(seen_requests) <= MAX_COMPACTION_LEVEL:
            raise LocalModelContextWindowExceeded(9_000, 8_000)
        return AIMessage(content="ok")

    middleware = _middleware()
    response = await middleware.awrap_model_call(StubRequest(_conversation_with_tool_results(4)), handler)

    assert response.content == "ok"
    assert middleware.compaction_level == MAX_COMPACTION_LEVEL
    assert _tool_contents(seen_requests[-1].messages)[-1] == "result-3"
    assert _tool_contents(seen_requests[-1].messages)[:3] == [COMPACTED_TOOL_RESULT] * 3


@pytest.mark.asyncio
async def test_context_overflow_after_max_compaction_stops_run():
    flags = AgentRunFlags()
    attempts = []

    async def handler(_request):
        attempts.append(1)
        raise LocalModelContextWindowExceeded(9_000, 8_000)

    middleware = ModelRecoveryMiddleware(flags, completed_model_calls=1, context_window_tokens=16_000, model_label="Local Qwen")
    middleware.backoff_base_seconds = 0
    response = await middleware.awrap_model_call(StubRequest(_conversation_with_tool_results(2)), handler)

    assert response.content.startswith("Stopped: this task needed more context than Local Qwen's 8,000-token context window holds (it needed about 9,000 tokens)")
    assert "2 tool step(s) completed" in response.content
    assert "raise its context window in Settings" in response.content
    assert flags.context_window_exceeded == {
        "actual_tokens": 9_000,
        "max_tokens": 8_000,
        "model": "Local Qwen",
        "completed_steps": 2,
        "compaction_attempts": MAX_COMPACTION_LEVEL,
        "message": response.content,
    }
    assert flags.terminal() is True
    assert len(attempts) == MAX_COMPACTION_LEVEL + 1


@pytest.mark.asyncio
async def test_context_overflow_without_counts_uses_the_configured_window():
    flags = AgentRunFlags()

    async def handler(_request):
        raise RuntimeError("This model's maximum context length exceeded")

    middleware = ModelRecoveryMiddleware(flags, completed_model_calls=1, context_window_tokens=16_384, model_label="")
    middleware.backoff_base_seconds = 0
    response = await middleware.awrap_model_call(StubRequest(_conversation_with_tool_results(1)), handler)

    assert "the selected model's 16,384-token context window holds," in response.content
    assert "it needed about" not in response.content
    assert flags.context_window_exceeded["max_tokens"] == 16_384
    assert flags.context_window_exceeded["actual_tokens"] is None


@pytest.mark.asyncio
async def test_unreachable_first_call_raises_fallback_signal(monkeypatch):
    monkeypatch.setattr(model_usage_service, "is_model_unreachable_error", lambda _error: True)
    original = RuntimeError("cannot connect")

    async def handler(_request):
        raise original

    with pytest.raises(ModelUnavailableBeforeFirstResponse) as raised:
        await _middleware(completed_model_calls=0).awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)
    assert raised.value.original_error is original


@pytest.mark.asyncio
async def test_unreachable_after_completed_call_reraises_original(monkeypatch):
    monkeypatch.setattr(model_usage_service, "is_model_unreachable_error", lambda _error: True)

    async def handler(_request):
        raise RuntimeError("cannot connect")

    with pytest.raises(RuntimeError, match="cannot connect"):
        await _middleware(completed_model_calls=1).awrap_model_call(StubRequest([HumanMessage(content="hi")]), handler)


@pytest.mark.asyncio
async def test_successful_call_counts_toward_fallback_eligibility(monkeypatch):
    monkeypatch.setattr(model_usage_service, "is_model_unreachable_error", lambda _error: True)
    middleware = _middleware(completed_model_calls=0)

    async def ok_handler(_request):
        return AIMessage(content="ok")

    async def failing_handler(_request):
        raise RuntimeError("cannot connect")

    await middleware.awrap_model_call(StubRequest([HumanMessage(content="hi")]), ok_handler)
    with pytest.raises(RuntimeError, match="cannot connect"):
        await middleware.awrap_model_call(StubRequest([HumanMessage(content="hi")]), failing_handler)


def _threaded_conversation(task_chars: int = 2_000):
    return [
        mark_turn_input(HumanMessage(content="Current request: first question")),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "old", "type": "tool_call"}]),
        ToolMessage(content="old result", tool_call_id="old"),
        AIMessage(content="First answer."),
        mark_turn_input(HumanMessage(content="CONTEXT " + "x" * task_chars + "\n\nCurrent request: second question")),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "new", "type": "tool_call"}]),
        ToolMessage(content="new result", tool_call_id="new"),
    ]


async def _ok(_request):
    return AIMessage(content="ok")


def test_thread_level_exists_only_with_earlier_turns():
    assert max_compaction_level(_threaded_conversation()) == THREAD_COMPACTION_LEVEL
    assert max_compaction_level(_conversation_with_tool_results(2)) == MAX_COMPACTION_LEVEL
    assert max_compaction_level([mark_turn_input(HumanMessage(content="only turn"))]) == MAX_COMPACTION_LEVEL


def test_level_two_trims_the_current_request_not_the_first_turn():
    original = _threaded_conversation(50_000)

    compacted = compact_messages(original, 2)

    assert compacted[0].content == "Current request: first question"
    assert len(compacted[4].content) < len(original[4].content)
    assert compacted[4].content.endswith("Current request: second question")


def test_level_three_condenses_earlier_turns_into_a_recap():
    compacted = compact_messages(_threaded_conversation(), THREAD_COMPACTION_LEVEL)

    assert compacted[0].content.startswith(RECAP_HEADER)
    assert "User: first question" in compacted[0].content
    assert "You: First answer." in compacted[0].content
    assert compacted[0].content.endswith("Current request: second question")
    assert is_turn_input(compacted[0])
    assert [type(message).__name__ for message in compacted[1:]] == ["AIMessage", "ToolMessage"]
    assert compacted[2].content == "new result"


@pytest.mark.asyncio
async def test_proactive_compaction_runs_before_the_first_call():
    seen = []

    async def handler(request):
        seen.append(request)
        return AIMessage(content="ok")

    middleware = ModelRecoveryMiddleware(AgentRunFlags(), completed_model_calls=1, prompt_budget_tokens=1_000)
    response = await middleware.awrap_model_call(StubRequest(_conversation_with_tool_results(4, task_chars=6_000)), handler)

    assert response.content == "ok"
    assert len(seen) == 1
    assert middleware.compaction_level == MAX_COMPACTION_LEVEL
    assert len(seen[0].messages[0].content) < 6_000


@pytest.mark.asyncio
async def test_prompt_within_budget_is_left_alone():
    middleware = ModelRecoveryMiddleware(AgentRunFlags(), completed_model_calls=1, prompt_budget_tokens=100_000)

    await middleware.awrap_model_call(StubRequest(_conversation_with_tool_results(4, task_chars=6_000)), _ok)

    assert middleware.compaction_level == 0


@pytest.mark.asyncio
async def test_proactive_compaction_reaches_the_thread_level():
    seen = []

    async def handler(request):
        seen.append(request)
        return AIMessage(content="ok")

    middleware = ModelRecoveryMiddleware(AgentRunFlags(), completed_model_calls=1, prompt_budget_tokens=10)
    await middleware.awrap_model_call(StubRequest(_threaded_conversation()), handler)

    assert middleware.compaction_level == THREAD_COMPACTION_LEVEL
    assert seen[0].messages[0].content.startswith(RECAP_HEADER)


@pytest.mark.asyncio
async def test_overflow_on_a_thread_uses_three_levels_before_stopping():
    flags = AgentRunFlags()
    attempts = []

    async def handler(_request):
        attempts.append(1)
        raise LocalModelContextWindowExceeded(9_000, 8_000)

    response = await _middleware(flags).awrap_model_call(StubRequest(_threaded_conversation()), handler)

    assert len(attempts) == THREAD_COMPACTION_LEVEL + 1
    assert response.content.startswith("Stopped: this task needed more context than")
    assert flags.context_window_exceeded["compaction_attempts"] == THREAD_COMPACTION_LEVEL
    assert flags.terminal() is True
