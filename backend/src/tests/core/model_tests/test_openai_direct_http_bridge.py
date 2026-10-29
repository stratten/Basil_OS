"""Ensure OpenAI direct HTTP streaming paths yield via the async bridge (non-blocking)."""

from __future__ import annotations

from pathlib import Path

import pytest

from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.openai_model import OpenAIModel


class _FakeDirectHTTPStreamer:
    """Minimal stand-in for OpenAIDirectHTTPStreaming used inside streaming helpers."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def stream_responses_api(self, **kwargs):  # noqa: ARG002
        yield "hello"
        yield " "
        yield "world"

    def stream_chat_completions_api(self, **kwargs):  # noqa: ARG002
        yield "chat"
        yield "-"
        yield "ok"


@pytest.fixture
def loaded_openai_stub(monkeypatch):
    monkeypatch.setattr(
        "api.core.models.reasoning.openai_supporting_files.direct_http_streaming.OpenAIDirectHTTPStreaming",
        _FakeDirectHTTPStreamer,
    )
    model = OpenAIModel(Path("/tmp/nonexistent-model-path"), {ModelCapability.NONE})
    model.state = ModelState.READY
    model.api_key = "test-key"
    model.model_name = "gpt-4o"
    return model


@pytest.mark.asyncio
async def test_stream_with_responses_api_bridges_sync_iterator(loaded_openai_stub):
    model = loaded_openai_stub
    collected: list[str] = []
    async for token in model._stream_with_responses_api(
        [{"role": "user", "content": "hi"}],
        max_tokens=32,
        enable_web_search=False,
    ):
        collected.append(token)
    assert "".join(collected) == "hello world"


@pytest.mark.asyncio
async def test_stream_with_chat_completions_api_bridges_sync_iterator(loaded_openai_stub):
    model = loaded_openai_stub
    collected: list[str] = []
    async for token in model._stream_with_chat_completions_api(
        [{"role": "user", "content": "hi"}],
        max_tokens=32,
        enable_web_search=False,
    ):
        collected.append(token)
    assert "".join(collected) == "chat-ok"
