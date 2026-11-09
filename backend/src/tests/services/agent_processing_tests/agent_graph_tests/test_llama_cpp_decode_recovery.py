"""The agent loop's llama.cpp adapter recovers from a native memory failure by reloading the context at half size."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from api.core.models.reasoning.local_model_failure import LocalModelDecodeError, LocalModelFailureKind, parse_decode_failure
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import LlamaCppLangChainAdapter


def _chunk(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}}]}


class _Llama:
    """A native context whose chat stream raises, or yields the given chunks."""

    def __init__(self, *, fail_with: str | None = None, fail_after: int = 0, chunks: tuple[str, ...] = ("ok",), n_ctx: int = 32768) -> None:
        self.fail_with = fail_with
        self.fail_after = fail_after
        self.chunks = chunks
        self._n_ctx = n_ctx
        self.calls = 0

    def n_ctx(self) -> int:
        return self._n_ctx

    def tokenize(self, text: bytes, *_args: Any, **_kwargs: Any) -> list[int]:
        return list(range(max(1, len(text) // 4)))

    def create_chat_completion(self, **_kwargs: Any):
        self.calls += 1

        def _stream():
            for index, text in enumerate(self.chunks):
                if self.fail_with and index == self.fail_after:
                    raise RuntimeError(self.fail_with)
                yield _chunk(text)
            if self.fail_with and self.fail_after >= len(self.chunks):
                raise RuntimeError(self.fail_with)

        return _stream()


class _Wrapper:
    """Stands in for LlamaCppModel: reloads onto a replacement context at half the size."""

    def __init__(self, llm: _Llama, replacement: _Llama | None) -> None:
        self.llm = llm
        self.replacement = replacement
        self.reloads: list[int] = []

    def _reload_after_memory_failure(self, failure) -> int | None:
        if parse_decode_failure(RuntimeError(f"llama_decode returned {failure.code}")) is None or failure.kind is not LocalModelFailureKind.MEMORY:
            return None
        if self.replacement is None:
            return None
        self.llm = self.replacement
        self.reloads.append(self.replacement.n_ctx())
        return self.replacement.n_ctx()


def _adapter(llama: _Llama, wrapper: _Wrapper | None) -> LlamaCppLangChainAdapter:
    adapter = LlamaCppLangChainAdapter(model_name="test-model", context_window=32768)
    adapter._llama_instance = llama
    adapter._llama_wrapper = wrapper
    adapter._QUEUE_POLL_SECONDS = 0.05
    return adapter


@pytest.mark.asyncio
async def test_a_memory_failure_before_the_first_chunk_reloads_and_the_call_succeeds():
    broken = _Llama(fail_with="llama_decode returned -3", chunks=())
    healthy = _Llama(chunks=("hello ", "world"), n_ctx=16384)
    wrapper = _Wrapper(broken, healthy)
    adapter = _adapter(broken, wrapper)

    result = await adapter._agenerate([HumanMessage(content="hi")])

    assert "hello world" in result.generations[0].message.content
    assert wrapper.reloads == [16384]
    assert adapter._llama_instance is healthy
    assert adapter.context_window == 16384
    assert broken.calls == 1 and healthy.calls == 1


@pytest.mark.asyncio
async def test_a_second_failure_after_the_reload_raises_the_typed_error():
    broken = _Llama(fail_with="llama_decode returned -3", chunks=())
    still_broken = _Llama(fail_with="llama_decode returned -3", chunks=(), n_ctx=16384)
    adapter = _adapter(broken, _Wrapper(broken, still_broken))

    with pytest.raises(LocalModelDecodeError) as raised:
        await adapter._agenerate([HumanMessage(content="hi")])

    assert raised.value.kind is LocalModelFailureKind.MEMORY
    assert raised.value.retried_at_context == 16384
    assert "ran out of memory" in str(raised.value)


@pytest.mark.asyncio
async def test_a_failure_after_text_was_streamed_is_not_replayed():
    broken = _Llama(fail_with="llama_decode returned -3", fail_after=1, chunks=("partial ", "more"))
    healthy = _Llama(chunks=("never used",), n_ctx=16384)
    wrapper = _Wrapper(broken, healthy)
    adapter = _adapter(broken, wrapper)

    with pytest.raises(LocalModelDecodeError) as raised:
        await adapter._agenerate([HumanMessage(content="hi")])

    assert raised.value.retried_at_context is None
    assert wrapper.reloads == []
    assert healthy.calls == 0


@pytest.mark.asyncio
async def test_a_prompt_that_does_not_fit_is_reported_without_a_reload():
    llama = _Llama(fail_with="llama_decode returned 1", chunks=())
    wrapper = _Wrapper(llama, _Llama(n_ctx=16384))
    adapter = _adapter(llama, wrapper)

    with pytest.raises(LocalModelDecodeError) as raised:
        await adapter._agenerate([HumanMessage(content="hi")])

    assert raised.value.kind is LocalModelFailureKind.CONTEXT_FULL
    assert wrapper.reloads == []


@pytest.mark.asyncio
async def test_an_adapter_without_a_wrapper_still_reports_the_typed_error():
    llama = _Llama(fail_with="llama_decode returned -3", chunks=())
    adapter = _adapter(llama, None)

    with pytest.raises(LocalModelDecodeError) as raised:
        await adapter._agenerate([HumanMessage(content="hi")])

    assert raised.value.retried_at_context is None


@pytest.mark.asyncio
async def test_other_native_errors_pass_through_unchanged():
    llama = _Llama(fail_with="something unrelated broke", chunks=())
    adapter = _adapter(llama, _Wrapper(llama, None))

    with pytest.raises(RuntimeError, match="something unrelated broke"):
        await adapter._agenerate([HumanMessage(content="hi")])


@pytest.mark.asyncio
async def test_an_adapter_follows_the_wrapper_to_a_context_reloaded_by_someone_else():
    stale = _Llama(chunks=("stale",))
    live = _Llama(chunks=("fresh",), n_ctx=16384)
    wrapper = SimpleNamespace(llm=live)
    adapter = _adapter(stale, wrapper)

    result = await adapter._agenerate([HumanMessage(content="hi")])

    assert "fresh" in result.generations[0].message.content
    assert stale.calls == 0
    assert adapter.context_window == 16384
