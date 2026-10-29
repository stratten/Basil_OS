"""Silence detection and retry behavior for provider token streams."""

import asyncio
from typing import Any, List

import pytest

from api.core.models.reasoning.streaming_contract import StreamEvent, terminal_from_provider_reason
from api.services.agent_processing.lifecycle.execution_graph.provider_stream_watchdog import (
    ProviderStreamIdleTimeout,
    watch_provider_stream,
)

_TICK = 0.01


async def _events(*items: Any, pause_before: float = 0.0):
    if pause_before:
        await asyncio.sleep(pause_before)
    for item in items:
        yield item


async def _collect(stream, **kwargs) -> List[Any]:
    return [event async for event in watch_provider_stream(stream, tick_seconds=_TICK, **kwargs)]


@pytest.mark.asyncio
async def test_events_pass_through_in_order_and_the_stream_ends():
    assert await _collect(_events(1, 2, 3)) == [1, 2, 3]


@pytest.mark.asyncio
async def test_silence_past_a_threshold_announces_once_per_threshold():
    announced: List[float] = []

    async def on_quiet(idle: float) -> None:
        announced.append(idle)

    result = await _collect(
        _events("late", pause_before=0.12),
        on_quiet=on_quiet,
        notice_after_seconds=(0.03, 0.08),
    )

    assert result == ["late"]
    assert len(announced) == 2
    assert announced[0] >= 0.03
    assert announced[1] >= 0.08


@pytest.mark.asyncio
async def test_an_event_resets_the_silence_so_a_threshold_can_fire_again():
    announced: List[float] = []

    async def on_quiet(idle: float) -> None:
        announced.append(idle)

    async def stream():
        await asyncio.sleep(0.06)
        yield "first"
        await asyncio.sleep(0.06)
        yield "second"

    await _collect(stream(), on_quiet=on_quiet, notice_after_seconds=(0.03,))

    assert len(announced) == 2


@pytest.mark.asyncio
async def test_steady_keepalives_never_announce_or_time_out():
    announced: List[float] = []

    async def on_quiet(idle: float) -> None:
        announced.append(idle)

    async def stream():
        for _ in range(8):
            await asyncio.sleep(0.02)
            yield StreamEvent(keepalive=True)

    result = await _collect(
        stream(),
        on_quiet=on_quiet,
        notice_after_seconds=(0.05,),
        idle_timeout_seconds=0.05,
    )

    assert len(result) == 8
    assert announced == []


@pytest.mark.asyncio
async def test_silence_past_the_idle_limit_raises_and_closes_the_stream():
    closed = asyncio.Event()

    async def stream():
        try:
            await asyncio.sleep(5)
            yield "never"
        finally:
            closed.set()

    with pytest.raises(ProviderStreamIdleTimeout) as raised:
        await _collect(stream(), idle_timeout_seconds=0.05)

    assert raised.value.idle_seconds >= 0.05
    assert closed.is_set()


@pytest.mark.asyncio
async def test_no_idle_limit_means_a_slow_stream_is_only_announced():
    announced: List[float] = []

    async def on_quiet(idle: float) -> None:
        announced.append(idle)

    result = await _collect(
        _events("slow", pause_before=0.1),
        on_quiet=on_quiet,
        notice_after_seconds=(0.03,),
        idle_timeout_seconds=None,
    )

    assert result == ["slow"]
    assert len(announced) == 1


@pytest.mark.asyncio
async def test_a_provider_error_inside_the_stream_propagates_unchanged():
    async def stream():
        yield "ok"
        raise ValueError("provider exploded")

    seen: List[Any] = []
    with pytest.raises(ValueError, match="provider exploded"):
        async for event in watch_provider_stream(stream(), tick_seconds=_TICK):
            seen.append(event)

    assert seen == ["ok"]


@pytest.mark.asyncio
async def test_closing_the_consumer_early_closes_the_source_stream():
    closed = asyncio.Event()

    async def stream():
        try:
            for index in range(100):
                yield index
        finally:
            closed.set()

    watched = watch_provider_stream(stream(), tick_seconds=_TICK)
    first = await watched.__anext__()
    await watched.aclose()

    assert first == 0
    assert closed.is_set()


def test_keepalive_events_are_not_terminal_and_carry_no_text():
    event = StreamEvent(keepalive=True)

    assert event.keepalive is True
    assert event.text == ""
    assert event.is_terminal is False
    assert StreamEvent(terminal=terminal_from_provider_reason("end_turn")).keepalive is False
