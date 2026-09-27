"""Unit tests for the auth-proxy SSE stream consumer.

These verify that the streamed auth-service response is folded correctly into a
StreamAccumulator: content deltas are forwarded live (the mechanism that drives
live reasoning), tool-call deltas are reassembled by index, and the
trial_balance / error / [DONE] control events are honored.
"""

import json
from typing import AsyncIterator, List

import pytest

from api.services.agent_processing.lifecycle.execution_graph.auth_proxy_stream import (
    apply_chunk,
    consume_auth_proxy_stream,
    StreamAccumulator,
)


async def _lines(items: List[str]) -> AsyncIterator[str]:
    for item in items:
        yield item


def _data(chunk: dict) -> str:
    return f"data: {json.dumps(chunk)}"


@pytest.mark.asyncio
async def test_content_deltas_accumulate_and_forward():
    forwarded: List[str] = []

    async def on_delta(delta: str) -> None:
        forwarded.append(delta)

    lines = _lines([
        _data({"id": "req-1", "choices": [{"delta": {"content": "Hello"}}]}),
        "",
        _data({"choices": [{"delta": {"content": " world"}}]}),
        "",
        "data: [DONE]",
    ])

    acc = await consume_auth_proxy_stream(lines, on_delta)

    assert acc.content == "Hello world"
    assert forwarded == ["Hello", " world"]
    assert acc.request_id == "req-1"


@pytest.mark.asyncio
async def test_tool_call_deltas_reassemble_by_index():
    lines = _lines([
        _data({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_a", "function": {"name": "search", "arguments": "{\"q\":"}}
        ]}}]}),
        _data({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "\"basil\"}"}}
        ]}}]}),
        "data: [DONE]",
    ])

    acc = await consume_auth_proxy_stream(lines, None)

    merged = acc.merged_tool_calls()
    assert len(merged) == 1
    assert merged[0]["id"] == "call_a"
    assert merged[0]["function"]["name"] == "search"
    assert merged[0]["function"]["arguments"] == '{"q":"basil"}'
    # as_openai_response feeds the adapter's existing _parse_tool_calls unchanged
    assert acc.as_openai_response()["choices"][0]["message"]["tool_calls"] == merged


@pytest.mark.asyncio
async def test_trial_balance_event_is_captured():
    lines = _lines([
        _data({"choices": [{"delta": {"content": "hi"}}]}),
        "event: trial_balance_update",
        _data({"remaining_usd": 1.23, "remaining_cents": 123, "is_exhausted": False}),
        "",
        "data: [DONE]",
    ])

    acc = await consume_auth_proxy_stream(lines, None)

    assert acc.content == "hi"
    assert acc.trial_balance == {
        "remaining_usd": 1.23,
        "remaining_cents": 123,
        "is_exhausted": False,
    }


@pytest.mark.asyncio
async def test_stream_error_is_recorded_without_content():
    lines = _lines([
        _data({"error": "upstream exploded", "code": "boom"}),
        "data: [DONE]",
    ])

    acc = await consume_auth_proxy_stream(lines, None)

    assert acc.stream_error == "upstream exploded"
    assert acc.content == ""
    assert acc.merged_tool_calls() == []


@pytest.mark.asyncio
async def test_done_sentinel_halts_further_consumption():
    forwarded: List[str] = []

    async def on_delta(delta: str) -> None:
        forwarded.append(delta)

    lines = _lines([
        _data({"choices": [{"delta": {"content": "before"}}]}),
        "data: [DONE]",
        _data({"choices": [{"delta": {"content": "after"}}]}),
    ])

    acc = await consume_auth_proxy_stream(lines, on_delta)

    assert acc.content == "before"
    assert forwarded == ["before"]


def test_apply_chunk_tracks_usage_and_ignores_empty_choices():
    acc = StreamAccumulator()
    assert apply_chunk(acc, {"choices": []}) == ""
    apply_chunk(acc, {"usage": {"prompt_tokens": 10, "completion_tokens": 4}})
    assert acc.input_tokens == 10
    assert acc.output_tokens == 4
