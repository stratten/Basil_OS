"""Unit tests for live agent-loop reasoning streaming (P1)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_progress_system import (
    LiveProgressCallbackHandler,
)
from api.services.agent_processing.lifecycle.runtime.turn_timing import TurnTiming


def test_extract_reasoning_text_delta_plain_string():
    handler = LiveProgressCallbackHandler(notifier=MagicMock(), todo_id="t1")
    assert handler._extract_reasoning_text_delta("hello") == "hello"


def test_extract_reasoning_text_delta_content_blocks():
    handler = LiveProgressCallbackHandler(notifier=MagicMock(), todo_id="t1")
    chunk = SimpleNamespace(
        content=[
            {"type": "text", "text": "visible "},
            {"type": "thinking", "thinking": "internal"},
        ]
    )
    assert handler._extract_reasoning_text_delta("", chunk) == "visible internal"


def test_extract_reasoning_text_delta_ignores_tool_only_chunks():
    handler = LiveProgressCallbackHandler(notifier=MagicMock(), todo_id="t1")
    chunk = SimpleNamespace(tool_call_chunks=[{"name": "recall_agent_tasks", "args": "{}"}])
    assert handler._extract_reasoning_text_delta("", chunk) == ""


def test_extract_reasoning_text_delta_chat_generation_chunk():
    """Real LangChain chat models (ChatAnthropic/ChatOpenAI) pass a
    ChatGenerationChunk whose payload is at .message.content, not .content."""
    handler = LiveProgressCallbackHandler(notifier=MagicMock(), todo_id="t1")
    # thinking-only delta: token is empty, content lives under .message.content,
    # and there is no top-level .content attribute (mirrors ChatGenerationChunk).
    message = SimpleNamespace(content=[{"type": "thinking", "thinking": "reasoning…"}])
    chunk = SimpleNamespace(message=message, text="")
    assert handler._extract_reasoning_text_delta("", chunk) == "reasoning…"


def test_extract_reasoning_text_delta_generation_chunk_text_fallback():
    """A plain GenerationChunk exposes only .text."""
    handler = LiveProgressCallbackHandler(notifier=MagicMock(), todo_id="t1")
    chunk = SimpleNamespace(text="partial answer")
    assert handler._extract_reasoning_text_delta("", chunk) == "partial answer"


@pytest.mark.asyncio
async def test_stream_reasoning_delta_coalesces_until_threshold():
    broadcasts = []

    async def _capture(event):
        broadcasts.append(event)

    ws_manager = SimpleNamespace(broadcast=AsyncMock(side_effect=_capture))
    notifier = SimpleNamespace(_websocket_manager=ws_manager)
    timing = TurnTiming(agent_task_id="t1")
    handler = LiveProgressCallbackHandler(
        notifier=notifier,
        todo_id="t1",
        turn_timing=timing,
    )
    handler._reasoning_coalesce_min_chars = 80

    short = "x" * 40
    await handler._stream_reasoning_delta(short)
    assert broadcasts == []

    await handler._stream_reasoning_delta("y" * 40)
    await asyncio.sleep(0.01)
    assert len(broadcasts) == 1
    assert broadcasts[0]["event_type"] == "agent_progress_update"
    assert broadcasts[0]["thinking_complete"] is False
    assert len(broadcasts[0]["thinking"]) >= 80
    assert "first_reasoning_token" in timing.spans_ms


@pytest.mark.asyncio
async def test_completed_cloud_thinking_is_retained_from_the_emitted_ui_segment():
    broadcasts = []

    async def _capture(event):
        broadcasts.append(event)

    notifier = SimpleNamespace(
        _websocket_manager=SimpleNamespace(broadcast=AsyncMock(side_effect=_capture))
    )
    handler = LiveProgressCallbackHandler(notifier=notifier, todo_id="t1")
    response = SimpleNamespace(
        generations=[[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="I will use the available history before preparing the answer.",
                    tool_calls=[{"name": "query_unified_history"}],
                )
            )
        ]]
    )

    await handler.on_llm_end(response)
    await asyncio.sleep(0.01)

    assert broadcasts[0]["thinking_complete"] is True
    assert broadcasts[0]["thinking_iteration"] == 1
    assert handler.get_thinking_history() == [{
        "iteration": 1,
        "text": "I will use the available history before preparing the answer.",
        "is_complete": True,
    }]


@pytest.mark.asyncio
async def test_completed_anthropic_thinking_blocks_are_retained_from_the_emitted_ui_segment():
    broadcasts = []

    async def _capture(event):
        broadcasts.append(event)

    notifier = SimpleNamespace(
        _websocket_manager=SimpleNamespace(broadcast=AsyncMock(side_effect=_capture))
    )
    handler = LiveProgressCallbackHandler(notifier=notifier, todo_id="t1")
    response = SimpleNamespace(
        generations=[[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[{
                        "type": "thinking",
                        "thinking": "I will inspect the available files before proposing cleanup actions.",
                    }],
                    tool_calls=[{"name": "file_service_list_directory"}],
                )
            )
        ]]
    )

    await handler.on_llm_end(response)
    await asyncio.sleep(0.01)

    assert broadcasts[0]["thinking_complete"] is True
    assert handler.get_thinking_history() == [{
        "iteration": 1,
        "text": "I will inspect the available files before proposing cleanup actions.",
        "is_complete": True,
    }]
