"""Regression tests for cloud adapter generate_from_messages overrides.

Verifies that Claude and OpenAI adapters send real role-tagged message arrays
with system hoisted into the provider's native system parameter, rather than
flattening everything into a single user turn.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.models.base_model import ModelState
from api.core.models.reasoning.claude_model import ClaudeModel
from api.core.models.reasoning.openai_model import OpenAIModel


class _FakeStream:
    def __init__(self, message) -> None:
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get_final_message(self):
        return self._message


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeNonTextBlock:
    """A block the extractor must skip: no ``text``, and not a tool block."""

    def __init__(self, block_type: str) -> None:
        self.type = block_type


class _FakeResponsesContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponsesOutput:
    def __init__(self, content: List[_FakeResponsesContent]) -> None:
        self.content = content


class _FakeResponsesResponse:
    def __init__(self, output: List[_FakeResponsesOutput]) -> None:
        self.output = output


def _openai_model_for_responses_api() -> OpenAIModel:
    model = OpenAIModel.__new__(OpenAIModel)
    model.state = ModelState.READY
    model.max_output_tokens = 8192
    model.model_name = "gpt-4.1"
    model._requires_responses_api = lambda: True  # type: ignore[method-assign]
    model._supports_web_search = lambda: False  # type: ignore[method-assign]
    model._get_reasoning_effort = lambda: None  # type: ignore[method-assign]
    model._async_client = MagicMock()
    model._async_client.responses.create = AsyncMock(
        return_value=_FakeResponsesResponse(
            [_FakeResponsesOutput([_FakeResponsesContent('{"ok": true}')])]
        )
    )
    return model


_MESSAGES = [
    {"role": "system", "content": "You classify JSON."},
    {"role": "user", "content": '{"task": "pick one"}'},
]


@pytest.mark.asyncio
async def test_claude_generate_from_messages_hoists_system_and_disables_search():
    model = ClaudeModel.__new__(ClaudeModel)
    model.state = ModelState.READY
    model.max_output_tokens = 8192
    model.temperature = 0.1
    model.model_name = "claude-sonnet-5"
    model._async_client = MagicMock()
    model._client = MagicMock()
    model._supports_web_search = lambda: True  # type: ignore[method-assign]
    model._get_web_search_tool_config = lambda: [{"type": "web_search"}]  # type: ignore[method-assign]
    model._get_base_model_id = lambda: "claude-sonnet-5"  # type: ignore[method-assign]
    model._apply_thinking_to_api_params = lambda params: None  # type: ignore[method-assign]

    # Deliberately not stubbed: the real extractor runs so this covers the
    # method generate_response and generate_from_messages now share.
    fake_message = MagicMock()
    fake_message.content = [_FakeContentBlock('{"ok": true}')]

    captured: Dict[str, Any] = {}

    def _capture_stream(**kwargs):
        captured.update(kwargs)
        return _FakeStream(fake_message)

    model._async_client.messages.stream = _capture_stream

    result = await model.generate_from_messages(
        _MESSAGES,
        max_tokens=400,
        enable_web_search=False,
    )

    assert result == '{"ok": true}'
    assert captured["system"] == "You classify JSON."
    assert captured["messages"] == [{"role": "user", "content": '{"task": "pick one"}'}]
    assert "tools" not in captured


def test_claude_extract_text_concatenates_text_blocks_and_skips_others():
    """The shared extractor joins text blocks and ignores blocks without text."""
    model = ClaudeModel.__new__(ClaudeModel)

    response = MagicMock()
    response.content = [
        _FakeContentBlock("first half. "),
        _FakeNonTextBlock("thinking"),
        _FakeContentBlock("second half."),
    ]

    assert model._extract_text_from_message(response) == "first half. second half."


@pytest.mark.asyncio
async def test_openai_responses_api_hoists_system_into_instructions():
    """A single user turn still collapses to the simple string input format."""
    model = _openai_model_for_responses_api()

    result = await model.generate_from_messages(
        _MESSAGES,
        max_tokens=300,
        enable_web_search=False,
    )

    assert result == '{"ok": true}'
    call_kwargs = model._async_client.responses.create.await_args.kwargs
    assert call_kwargs["instructions"] == "You classify JSON."
    assert call_kwargs["input"] == '{"task": "pick one"}'
    assert call_kwargs["max_output_tokens"] == 300
    assert call_kwargs["tools"] is None


@pytest.mark.asyncio
async def test_openai_responses_api_sends_message_array_for_multi_turn():
    """Multi-turn history reaches the Responses API as a real message array."""
    model = _openai_model_for_responses_api()

    await model.generate_from_messages(
        [
            {"role": "system", "content": "You classify JSON."},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
        ],
        max_tokens=500,
        enable_web_search=False,
    )

    call_kwargs = model._async_client.responses.create.await_args.kwargs
    assert call_kwargs["instructions"] == "You classify JSON."
    assert call_kwargs["input"] == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]


@pytest.mark.asyncio
async def test_openai_generate_from_messages_uses_chat_completions_messages():
    model = OpenAIModel.__new__(OpenAIModel)
    model.state = ModelState.READY
    model.max_output_tokens = 8192
    model.model_name = "gpt-4o"
    model._requires_responses_api = lambda: False  # type: ignore[method-assign]
    model._supports_web_search = lambda: False  # type: ignore[method-assign]
    model._convert_to_openai_format = OpenAIModel._convert_to_openai_format.__get__(  # type: ignore[method-assign]
        model, OpenAIModel
    )
    model._async_client = MagicMock()

    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content='{"slug": null}'))]
    model._async_client.chat.completions.create = AsyncMock(return_value=response)

    result = await model.generate_from_messages(
        _MESSAGES,
        max_tokens=300,
        enable_web_search=False,
    )

    assert result == '{"slug": null}'
    call_kwargs = model._async_client.chat.completions.create.await_args.kwargs
    assert call_kwargs["messages"][0]["role"] == "system"
    assert call_kwargs["messages"][0]["content"] == "You classify JSON."
    assert call_kwargs["messages"][1]["role"] == "user"
    assert call_kwargs["max_tokens"] == 300
