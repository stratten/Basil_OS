"""Regression coverage for Anthropic adaptive-thinking tool continuations."""

from __future__ import annotations

from anthropic.types import (
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    SignatureDelta,
    ThinkingBlock,
)
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

_TEST_MODEL = "claude-sonnet-5"
_TOOL_CALL_ID = "toolu_basil_thinking_replay"


def _signature_only_thinking_chunk() -> dict[str, object]:
    """Reproduce the empty-thinking start followed only by a signature delta."""
    llm = ChatAnthropic(model=_TEST_MODEL)
    start_chunk, start_event = llm._make_message_chunk_from_anthropic_event(
        RawContentBlockStartEvent(
            content_block=ThinkingBlock(thinking="", signature="", type="thinking"),
            index=0,
            type="content_block_start",
        ),
        stream_usage=True,
        coerce_content_to_string=False,
        block_start_event=None,
    )
    assert start_chunk is None
    assert start_event is not None

    signature_chunk, _ = llm._make_message_chunk_from_anthropic_event(
        RawContentBlockDeltaEvent(
            delta=SignatureDelta(signature="sig_basil_thinking_replay", type="signature_delta"),
            index=0,
            type="content_block_delta",
        ),
        stream_usage=True,
        coerce_content_to_string=False,
        block_start_event=start_event,
    )
    assert signature_chunk is not None
    assert isinstance(signature_chunk.content, list)
    assert len(signature_chunk.content) == 1
    thinking_block = signature_chunk.content[0]
    assert isinstance(thinking_block, dict)
    return thinking_block


def test_signature_only_thinking_replays_in_tool_continuation() -> None:
    thinking_block = _signature_only_thinking_chunk()
    assert thinking_block == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig_basil_thinking_replay",
        "index": 0,
    }

    assistant_message = AIMessage(
        content=[
            thinking_block,
            {
                "type": "tool_use",
                "id": _TOOL_CALL_ID,
                "name": "run_shell_command",
                "input": {"command": "/usr/bin/uname -s"},
            },
        ]
    )
    payload = ChatAnthropic(model=_TEST_MODEL)._get_request_payload(
        [
            HumanMessage(content="Report the operating system."),
            assistant_message,
            ToolMessage(
                content="Darwin",
                tool_call_id=_TOOL_CALL_ID,
                additional_kwargs={"name": "run_shell_command"},
            ),
        ]
    )

    replayed_assistant_content = payload["messages"][1]["content"]
    assert replayed_assistant_content[0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig_basil_thinking_replay",
    }
    assert replayed_assistant_content[1]["type"] == "tool_use"
    assert replayed_assistant_content[1]["id"] == _TOOL_CALL_ID
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"
    assert payload["messages"][2]["content"][0]["tool_use_id"] == _TOOL_CALL_ID
