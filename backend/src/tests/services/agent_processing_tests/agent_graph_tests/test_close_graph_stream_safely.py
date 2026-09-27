"""Regression tests for the benign aclose() re-entrancy race guard.

See agent_graph_runtime._close_graph_stream_safely: graph_stream.aclose() is
called from a finally block after a cancelled __anext__() task may still be
mid-unwind, which can raise a specific, narrow RuntimeError from CPython's
async generator machinery. These tests exercise that guard directly with
fake stream objects instead of standing up a full LangGraph app.
"""

from __future__ import annotations

import logging

import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_graph_runtime import (
    _close_graph_stream_safely,
)


class _FakeStreamRaisingBenignRace:
    def __init__(self) -> None:
        self.close_attempts = 0

    async def aclose(self) -> None:
        self.close_attempts += 1
        raise RuntimeError("aclose(): asynchronous generator is already running")


class _FakeStreamRaisingOtherRuntimeError:
    async def aclose(self) -> None:
        raise RuntimeError("aclose(): asynchronous generator is already running elsewhere")


class _FakeStreamClosingCleanly:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeStreamWithoutAclose:
    pass


@pytest.mark.asyncio
async def test_swallows_the_specific_benign_generator_race(caplog):
    stream = _FakeStreamRaisingBenignRace()
    with caplog.at_level(logging.WARNING):
        await _close_graph_stream_safely(stream)
    assert stream.close_attempts == 1
    assert any(
        "Suppressed benign graph-stream aclose() re-entrancy race" in message
        for message in caplog.messages
    )


@pytest.mark.asyncio
async def test_reraises_an_unrelated_runtime_error():
    stream = _FakeStreamRaisingOtherRuntimeError()
    with pytest.raises(RuntimeError) as raised:
        await _close_graph_stream_safely(stream)
    assert str(raised.value) == "aclose(): asynchronous generator is already running elsewhere"


@pytest.mark.asyncio
async def test_closes_normally_when_there_is_no_race():
    stream = _FakeStreamClosingCleanly()
    await _close_graph_stream_safely(stream)
    assert stream.closed is True


@pytest.mark.asyncio
async def test_no_op_when_stream_has_no_aclose():
    stream = _FakeStreamWithoutAclose()
    await _close_graph_stream_safely(stream)
