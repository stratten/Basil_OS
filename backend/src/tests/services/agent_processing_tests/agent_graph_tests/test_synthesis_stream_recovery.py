"""Final synthesis behavior when the provider stream goes silent."""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Dict, List

import pytest

from api.core.models.reasoning.streaming_contract import StreamEvent
from api.services.agent_processing.lifecycle.execution_graph import agent_result_synthesis
from api.services.agent_processing.lifecycle.execution_graph.agent_result_synthesis import (
    stream_synthesized_final_answer,
)
from api.services.agent_processing.lifecycle.execution_graph.provider_stream_watchdog import (
    watch_provider_stream,
)


class _Notifier:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def send_agent_progress_update(self, **kwargs: Any) -> None:
        self.calls.append({"kind": "progress", **kwargs})

    async def send_agent_result_streaming_chunk(self, **kwargs: Any) -> None:
        self.calls.append({"kind": "chunk", **kwargs})

    async def send_agent_result_streaming_complete(self, **kwargs: Any) -> None:
        self.calls.append({"kind": "complete", **kwargs})

    def messages(self) -> List[str]:
        return [call["message"] for call in self.calls if call["kind"] == "progress"]


class _ScriptedModel:
    """Each call to stream_chat_completion plays the next scripted attempt."""

    stream_idle_timeout_seconds = 0.08

    def __init__(self, attempts: List[List[Any]]) -> None:
        self._attempts = attempts
        self.calls = 0

    async def stream_chat_completion(self, _messages, _budget=None):
        script = self._attempts[self.calls]
        self.calls += 1
        for step in script:
            if isinstance(step, (int, float)):
                await asyncio.sleep(step)
            else:
                yield step


@pytest.fixture(autouse=True)
def _fast_watchdog(monkeypatch):
    monkeypatch.setattr(
        agent_result_synthesis,
        "watch_provider_stream",
        functools.partial(watch_provider_stream, tick_seconds=0.01, notice_after_seconds=(0.03,)),
    )


async def _synthesize(model: _ScriptedModel, notifier: _Notifier):
    return await stream_synthesized_final_answer(
        llm_model=model,
        messages=[{"role": "user", "content": "go"}],
        stream_notifier=notifier,
    )


@pytest.mark.asyncio
async def test_a_silent_first_attempt_is_retried_and_the_second_answer_is_delivered():
    model = _ScriptedModel([
        [5.0, StreamEvent(text="never")],
        [StreamEvent(text="Recovered answer.")],
    ])
    notifier = _Notifier()

    result = await _synthesize(model, notifier)

    assert result.text == "Recovered answer."
    assert model.calls == 2
    assert "Still waiting on the model…" in notifier.messages()
    assert "The model stopped responding. Retrying…" in notifier.messages()
    assert notifier.calls[-1]["kind"] == "complete"
    assert notifier.calls[-1]["final_result"] == "Recovered answer."


@pytest.mark.asyncio
async def test_keepalive_events_hold_off_the_retry_during_long_non_text_work():
    model = _ScriptedModel([
        [
            0.04, StreamEvent(keepalive=True),
            0.04, StreamEvent(keepalive=True),
            0.04, StreamEvent(keepalive=True),
            StreamEvent(text="Searched and answered."),
        ],
    ])
    notifier = _Notifier()

    result = await _synthesize(model, notifier)

    assert result.text == "Searched and answered."
    assert model.calls == 1
    assert "The model stopped responding. Retrying…" not in notifier.messages()


@pytest.mark.asyncio
async def test_a_stall_after_text_was_delivered_is_not_retried_and_keeps_the_partial_answer():
    model = _ScriptedModel([
        [StreamEvent(text="Partial answer. "), 5.0, StreamEvent(text="never")],
        [StreamEvent(text="Duplicate answer.")],
    ])
    notifier = _Notifier()

    result = await _synthesize(model, notifier)

    assert model.calls == 1
    assert result.text == "Partial answer. "
    assert result.terminal.error_message
    assert "The model stopped responding. Retrying…" not in notifier.messages()


@pytest.mark.asyncio
async def test_two_silent_attempts_end_in_an_error_terminal_with_no_answer():
    model = _ScriptedModel([[5.0], [5.0]])
    notifier = _Notifier()

    result = await _synthesize(model, notifier)

    assert model.calls == 2
    assert result.text == ""
    assert result.terminal.error_message
    assert notifier.calls[-1]["kind"] == "complete"


@pytest.mark.asyncio
async def test_a_model_without_an_idle_limit_is_announced_but_never_cut_off():
    model = _ScriptedModel([[0.1, StreamEvent(text="Slow local answer.")]])
    model.stream_idle_timeout_seconds = None
    notifier = _Notifier()

    result = await _synthesize(model, notifier)

    assert result.text == "Slow local answer."
    assert model.calls == 1
    assert "Still waiting on the model…" in notifier.messages()
