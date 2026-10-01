"""Cancellation, stall, and phase-heartbeat behavior of the local llama.cpp adapter."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LlamaCppLangChainAdapter,
    LocalModelGenerationStalled,
)
from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError


def _chunk(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}}]}


class _SlowLlama:
    """Stands in for llama_cpp.Llama with a lazily evaluated, observable token stream."""

    def __init__(self, *, total_chunks: int = 200, delay: float = 0.05, stall_after: int | None = None) -> None:
        self.total_chunks = total_chunks
        self.delay = delay
        self.stall_after = stall_after
        self.calls = 0
        self.yielded = 0
        self.closed = threading.Event()

    def n_ctx(self) -> int:
        return 32_768

    def tokenize(self, text: bytes, *_args: Any, **_kwargs: Any) -> list[int]:
        return list(range(max(1, len(text) // 4)))

    def create_chat_completion(self, **_kwargs: Any):
        self.calls += 1

        def _stream():
            try:
                for index in range(self.total_chunks):
                    if self.stall_after is not None and index == self.stall_after:
                        time.sleep(1.0)
                    time.sleep(self.delay)
                    self.yielded += 1
                    yield _chunk(f"t{index} ")
            finally:
                self.closed.set()

        return _stream()


def _adapter(llama: _SlowLlama) -> LlamaCppLangChainAdapter:
    adapter = LlamaCppLangChainAdapter(model_name="test-model")
    adapter._llama_instance = llama
    adapter._QUEUE_POLL_SECONDS = 0.05
    return adapter


async def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_cancel_stops_native_generation_and_releases_the_lock():
    llama = _SlowLlama()
    adapter = _adapter(llama)
    task = asyncio.create_task(adapter._agenerate([HumanMessage(content="hi")]))
    assert await _wait_until(lambda: llama.yielded >= 3)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _wait_until(llama.closed.is_set)
    assert llama.yielded < llama.total_chunks
    assert adapter._native_execution_lock.acquire(timeout=2.0) is True
    adapter._native_execution_lock.release()


@pytest.mark.asyncio
async def test_mid_stream_stall_raises_a_transient_error():
    llama = _SlowLlama(total_chunks=10, delay=0.01, stall_after=2)
    adapter = _adapter(llama)
    adapter._MID_STREAM_STALL_SECONDS = 0.2

    with pytest.raises(LocalModelGenerationStalled) as raised:
        await adapter._agenerate([HumanMessage(content="hi")])

    assert isinstance(raised.value, TransientModelError)
    assert await _wait_until(llama.closed.is_set)


@pytest.mark.asyncio
async def test_queued_request_reports_waiting_phase_and_skips_generation_after_cancel():
    llama = _SlowLlama(total_chunks=3, delay=0.01)
    adapter = _adapter(llama)
    phases: list[str] = []

    def _callback(tokens: int, thinking: Any, complete: bool, phase: str = "generating") -> None:
        phases.append(phase)

    _callback.accepts_phase = True
    adapter._activity_callback = _callback

    adapter._native_execution_lock.acquire()
    try:
        task = asyncio.create_task(adapter._agenerate([HumanMessage(content="hi")]))
        assert await _wait_until(lambda: "waiting_for_model" in phases)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        adapter._native_execution_lock.release()

    await asyncio.sleep(0.2)
    assert llama.calls == 0


@pytest.mark.asyncio
async def test_three_argument_callbacks_keep_working():
    llama = _SlowLlama(total_chunks=3, delay=0.01)
    adapter = _adapter(llama)
    calls: list[tuple] = []
    adapter._activity_callback = lambda tokens, thinking, complete: calls.append((tokens, thinking, complete))

    result = await adapter._agenerate([HumanMessage(content="hi")])

    assert "t0" in result.generations[0].message.content
    assert calls
    assert llama.calls == 1
