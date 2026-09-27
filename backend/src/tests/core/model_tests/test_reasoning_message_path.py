"""Tests for the messages-native entry points on BaseReasoningModel."""

from typing import Any, AsyncGenerator, Dict, List, Optional

import pytest

from api.core.models.base_model import ModelMetadata, ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.base_reasoning import BaseReasoningModel


class _PlainGenerateAdapter(BaseReasoningModel):
    """Adapter whose generate_response rejects preserve_thinking."""

    def __init__(self) -> None:
        self.generate_calls: List[Dict[str, Any]] = []
        self.state = ModelState.READY
        self.max_context_length = 8192

    async def load(self) -> None:
        pass

    async def unload(self) -> None:
        pass

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1024,
    ) -> str:
        self.generate_calls.append(
            {"prompt": prompt, "context": context, "max_tokens": max_tokens}
        )
        return "ok"

    def _generate(self, prompt: str, max_tokens: int = 1024) -> str:
        raise NotImplementedError

    async def _generate_async(self, prompt: str, max_tokens: int = 1024) -> str:
        return await self.generate_response(prompt, max_tokens=max_tokens)

    def get_metadata(self) -> ModelMetadata:
        return ModelMetadata(
            name="fake",
            version="1",
            capabilities={ModelCapability.REASONING},
        )

    def validate(self) -> bool:
        return True


class _MessagesTrackingAdapter(_PlainGenerateAdapter):
    """Records whether chat_completion reached generate_from_messages."""

    def __init__(self) -> None:
        super().__init__()
        self.messages_entry_used = False

    async def generate_from_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        preserve_thinking: bool = False,
    ) -> str:
        self.messages_entry_used = True
        return await super().generate_from_messages(
            messages, max_tokens=max_tokens, preserve_thinking=preserve_thinking
        )


class _RealStreamingAdapter(_PlainGenerateAdapter):
    """Adapter with genuine token streaming, as Solar and the auth proxy have."""

    def __init__(self) -> None:
        super().__init__()
        self.stream_calls: List[Dict[str, Any]] = []

    async def _generate_response_streaming(
        self, prompt: str, max_tokens: int = 4000
    ) -> AsyncGenerator[str, None]:
        self.stream_calls.append({"prompt": prompt, "max_tokens": max_tokens})
        for word in ("real", "tokens"):
            yield word


class _ThinkingCapableAdapter(BaseReasoningModel):
    """Adapter that accepts preserve_thinking like LlamaCppModel."""

    def __init__(self) -> None:
        self.last_kwargs: Dict[str, Any] = {}
        self.state = ModelState.READY
        self.max_context_length = 8192

    async def load(self) -> None:
        pass

    async def unload(self) -> None:
        pass

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1024,
        preserve_thinking: bool = False,
    ) -> str:
        self.last_kwargs = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "preserve_thinking": preserve_thinking,
        }
        return "streamed"

    def _generate(self, prompt: str, max_tokens: int = 1024) -> str:
        raise NotImplementedError

    async def _generate_async(self, prompt: str, max_tokens: int = 1024) -> str:
        return await self.generate_response(prompt, max_tokens=max_tokens)

    def get_metadata(self) -> ModelMetadata:
        return ModelMetadata(
            name="fake-thinking",
            version="1",
            capabilities={ModelCapability.REASONING},
        )

    def validate(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_default_generate_from_messages_stringifies_for_adapters_without_override():
    adapter = _PlainGenerateAdapter()
    messages = [{"role": "user", "content": "hello"}]
    result = await adapter.generate_from_messages(messages)
    assert result == "ok"
    assert adapter.generate_calls
    assert "hello" in adapter.generate_calls[0]["prompt"]


@pytest.mark.asyncio
async def test_preserve_thinking_is_not_passed_to_adapters_that_reject_it():
    adapter = _PlainGenerateAdapter()
    chunks = []
    async for token in adapter._generate_from_messages_streaming(
        [{"role": "user", "content": "hi"}]
    ):
        chunks.append(token)
    assert chunks == list("ok")
    assert "preserve_thinking" not in adapter.generate_calls[-1]


@pytest.mark.asyncio
async def test_preserve_thinking_is_passed_when_adapter_accepts_it():
    adapter = _ThinkingCapableAdapter()
    chunks = []
    async for token in adapter._generate_from_messages_streaming(
        [{"role": "user", "content": "hi"}]
    ):
        chunks.append(token)
    assert adapter.last_kwargs.get("preserve_thinking") is True


@pytest.mark.asyncio
async def test_adapters_with_real_streaming_still_stream_through_the_messages_path():
    """The messages path must not cost Solar and the auth proxy their streaming.

    It also pins the recursion this method invited: routing to itself instead of
    to _generate_response_streaming yields nothing here before it blows the stack.
    """
    adapter = _RealStreamingAdapter()
    chunks = []
    async for token in adapter._generate_from_messages_streaming(
        [{"role": "user", "content": "hi"}]
    ):
        chunks.append(token)
    assert chunks == ["real", "tokens"]
    assert not adapter.generate_calls, "fell back to non-streaming generation"


@pytest.mark.asyncio
async def test_an_explicit_budget_reaches_the_adapter_streaming_override():
    adapter = _RealStreamingAdapter()
    async for _ in adapter._generate_from_messages_streaming(
        [{"role": "user", "content": "hi"}], max_tokens=123
    ):
        pass
    assert adapter.stream_calls[-1]["max_tokens"] == 123


@pytest.mark.asyncio
async def test_chat_completion_routes_through_the_messages_entry_point():
    adapter = _MessagesTrackingAdapter()
    result = await adapter.chat_completion([{"role": "user", "content": "hello"}])
    assert result["content"] == "ok"
    assert adapter.messages_entry_used is True
