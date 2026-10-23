"""Regression tests for how LlamaCppModel handles inline reasoning in output.

Reasoning markers are model-family knowledge, so recognizing them belongs to the
adapter rather than to callers. These tests drive a fake llm and never load a real
GGUF, which is why they live apart from the model-loading tests in this directory.
"""

from typing import Any, Dict

import pytest

from langchain_core.messages import HumanMessage

from api.core.models.base_model import ModelState
from api.core.models.reasoning.base_reasoning import (
    DEFAULT_STREAMING_MAX_TOKENS,
    ReasoningTruncatedError,
    has_unterminated_reasoning,
    strip_inline_reasoning,
)
from api.core.models.reasoning.llama_cpp_model import (
    DEFAULT_MAX_TOKENS,
    LocalCompletionTelemetry,
    LlamaCppModel,
    LlamaCppTokenizerWrapper,
    shutdown_cached_llama_cpp_models,
)

_OPEN = "<think>"
_CLOSE = "</think>"


class _FakeLlm:
    """Stands in for llama_cpp.Llama, recording which completion API was used."""

    def __init__(
        self,
        text: str,
        finish_reason: str,
        *,
        usage: dict[str, int] | None = None,
        tokenizer_tokens: list[int] | None = None,
    ) -> None:
        self._text = text
        self._finish_reason = finish_reason
        self._usage = usage
        self._tokenizer_tokens = tokenizer_tokens
        self.calls: list[str] = []
        self.last_messages: list[Dict[str, str]] | None = None
        self.last_max_tokens: int | None = None

    def tokenize(self, text: bytes) -> list[int]:
        if self._tokenizer_tokens is not None:
            return list(self._tokenizer_tokens)
        return list(range(len(text.decode("utf-8").split())))

    def n_ctx(self) -> int:
        return 32_768

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append("chat_stream" if kwargs.get("stream") else "chat")
        self.last_messages = kwargs.get("messages")
        self.last_max_tokens = kwargs.get("max_tokens")
        if kwargs.get("stream"):
            return iter(
                [
                    {"choices": [{"delta": {"content": self._text[: len(self._text) // 2]}}]},
                    {"choices": [{"delta": {"content": self._text[len(self._text) // 2 :]}}]},
                    {"choices": [{"delta": {}, "finish_reason": self._finish_reason}]},
                ]
            )
        payload: Dict[str, Any] = {
            "choices": [
                {"message": {"content": self._text}, "finish_reason": self._finish_reason}
            ]
        }
        if self._usage is not None:
            payload["usage"] = dict(self._usage)
        return payload

    def create_completion(self, *_: Any, **__: Any) -> Dict[str, Any]:
        self.calls.append("completion")
        return {"choices": [{"text": self._text, "finish_reason": self._finish_reason}]}


class _CloseableFakeLlm:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _model(
    text: str,
    finish_reason: str = "stop",
    *,
    usage: dict[str, int] | None = None,
    tokenizer_tokens: list[int] | None = None,
) -> LlamaCppModel:
    """A ready model wired to a fake llm, bypassing __init__ and any file load."""
    model = LlamaCppModel.__new__(LlamaCppModel)
    model.state = ModelState.READY
    model.llm = _FakeLlm(
        text,
        finish_reason,
        usage=usage,
        tokenizer_tokens=tokenizer_tokens,
    )
    model._local_generation = {}
    model._reasoning_mode = "tagged"
    return model


@pytest.mark.asyncio
async def test_closed_reasoning_block_is_stripped_to_the_answer():
    model = _model(f"{_OPEN}weighing options{_CLOSE}\nThe answer.")
    assert await model.generate_response("prompt") == "The answer."


@pytest.mark.asyncio
async def test_answer_drafted_inside_reasoning_does_not_escape():
    """Models rehearse the answer while reasoning; only the real one may survive."""
    model = _model(
        f'{_OPEN}draft: {{"narrative": "DRAFT"}}{_CLOSE}{{"narrative": "FINAL"}}'
    )
    assert await model.generate_response("prompt") == '{"narrative": "FINAL"}'


@pytest.mark.asyncio
async def test_unterminated_reasoning_raises_instead_of_leaking_chain_of_thought():
    """Truncation means no answer was produced, so callers are told rather than
    handed raw reasoning or a bare empty string."""
    model = _model(f"{_OPEN}I should start by", finish_reason="length")
    with pytest.raises(ReasoningTruncatedError) as exc:
        await model.generate_response("prompt")
    assert "length" in str(exc.value)


@pytest.mark.asyncio
async def test_preserve_thinking_keeps_markers_and_never_raises():
    """The conversation UI parses the tags itself, so streaming must be exempt."""
    raw = f"{_OPEN}still reasoning"
    model = _model(raw, finish_reason="length")
    assert await model.generate_response("prompt", preserve_thinking=True) == raw


@pytest.mark.asyncio
async def test_unparseable_chatml_falls_back_to_the_completion_api():
    """The warning claimed a fallback that a raise had made unreachable."""
    model = _model("completion answer")
    result = await model.generate_response("<|im_start|>user\nhello<|im_end|>\n")
    assert result == "completion answer"
    assert model.llm.calls == ["completion"]


@pytest.mark.asyncio
async def test_well_formed_chatml_still_uses_the_chat_api():
    model = _model("chat answer")
    prompt = "<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n"
    assert await model.generate_response(prompt) == "chat answer"
    assert model.llm.calls == ["chat"]


def test_shared_helpers_treat_closed_and_unclosed_blocks_alike():
    assert strip_inline_reasoning(f"{_OPEN}r{_CLOSE}answer", _OPEN, _CLOSE) == "answer"
    assert strip_inline_reasoning(f"answer{_OPEN}r", _OPEN, _CLOSE) == "answer"
    assert has_unterminated_reasoning(f"{_OPEN}r", _OPEN, _CLOSE) is True
    assert has_unterminated_reasoning(f"{_OPEN}r{_CLOSE}a", _OPEN, _CLOSE) is False


@pytest.mark.asyncio
async def test_plain_prompt_is_sent_as_a_single_user_message():
    model = _model("hello answer")
    await model.generate_response("hello")
    assert model.llm.calls == ["chat"]
    assert model.llm.last_messages == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_plain_prompt_no_longer_uses_raw_completion():
    """Regression guard for the zero-output failure on document-shaped prompts."""
    model = _model('{"narrative": "ok", "is_open": false}')
    await model.generate_response("Summarize this activity log entry.")
    assert "completion" not in model.llm.calls


@pytest.mark.asyncio
async def test_generate_from_messages_passes_messages_through_unchanged():
    conversation = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Follow up"},
    ]
    model = _model("final answer")
    await model.generate_from_messages(conversation)
    assert model.llm.calls == ["chat"]
    assert model.llm.last_messages == conversation


@pytest.mark.asyncio
async def test_messages_streaming_preserves_reasoning_markers():
    """The conversation UI parses thinking tags from streamed output."""
    raw = f"{_OPEN}reasoning here{_CLOSE}visible answer"
    model = _model(raw)
    chunks = []
    async for token in model._generate_from_messages_streaming(
        [{"role": "user", "content": "hi"}]
    ):
        chunks.append(token)
    assert _OPEN in "".join(chunks)


@pytest.mark.asyncio
async def test_budgetless_streaming_keeps_the_larger_streaming_default():
    """chat_completion_streaming names no budget, and the UI renders a full reply.

    Routing it through generate_from_messages must not hand it that method's
    smaller single-shot default, or chat answers truncate where they did not before.
    """
    model = _model("answer")
    model.n_ctx = 262144
    async for _ in model.chat_completion_streaming([{"role": "user", "content": "hi"}]):
        pass
    assert model.llm.last_max_tokens == DEFAULT_STREAMING_MAX_TOKENS


@pytest.mark.asyncio
async def test_budgetless_single_shot_keeps_the_smaller_default():
    """The non-streaming default is unchanged; only the streaming path is larger."""
    model = _model("answer")
    await model.generate_from_messages([{"role": "user", "content": "hi"}])
    assert model.llm.last_max_tokens == DEFAULT_MAX_TOKENS


@pytest.mark.asyncio
async def test_explicit_budget_is_not_overridden_by_either_default():
    model = _model("answer")
    model.n_ctx = 262144
    async for _ in model._generate_from_messages_streaming(
        [{"role": "user", "content": "hi"}], max_tokens=77
    ):
        pass
    assert model.llm.last_max_tokens == 77


@pytest.mark.asyncio
async def test_messages_streaming_uses_native_chat_stream_deltas():
    model = _model("first second")
    chunks = [
        chunk
        async for chunk in model._generate_from_messages_streaming(
            [{"role": "user", "content": "hi"}], max_tokens=23
        )
    ]
    assert chunks == ["first ", "second"]
    assert model.llm.calls == ["chat_stream"]
    assert model.llm.last_messages == [{"role": "user", "content": "hi"}]
    assert model.llm.last_max_tokens == 23


@pytest.mark.asyncio
async def test_messages_streaming_keeps_inline_reasoning_for_the_consumer():
    raw = f"{_OPEN}reasoning{_CLOSE}visible answer"
    model = _model(raw)
    streamed = "".join(
        [
            chunk
            async for chunk in model._generate_from_messages_streaming(
                [{"role": "user", "content": "hi"}]
            )
        ]
    )
    assert streamed == raw
    assert model.llm.calls == ["chat_stream"]


def test_shutdown_cached_llama_cpp_models_closes_and_clears_cache(monkeypatch):
    from api.core.models.reasoning import llama_cpp_model

    first = _CloseableFakeLlm()
    second = _CloseableFakeLlm()
    monkeypatch.setattr(
        llama_cpp_model,
        "_MODEL_CACHE",
        {"first.gguf": first, "second.gguf": second},
    )

    shutdown_cached_llama_cpp_models()

    assert first.close_calls == 1
    assert second.close_calls == 1
    assert llama_cpp_model._MODEL_CACHE == {}


@pytest.mark.asyncio
async def test_non_thinking_model_returns_plain_completion_unchanged():
    model = _model("Plain answer without reasoning tags.")
    model._reasoning_mode = "none"
    result = await model.generate_from_messages(
        [{"role": "user", "content": "hi"}],
        max_tokens=128,
    )
    assert result == "Plain answer without reasoning tags."


@pytest.mark.asyncio
async def test_non_thinking_langchain_adapter_skips_thinking_history():
    from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile
    from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
        create_langchain_llm_from_llama_cpp,
    )

    model = _model("Tool-ready answer.")
    model.model_path = type("P", (), {"stem": "qwen3-coder-30b-a3b-instruct-q4km"})()
    model.max_context_length = 32768
    model.max_tokens_to_sample = 65536
    model.apply_registry_config(
        {
            "context_window": 32768,
            "max_output_tokens": 65536,
            "location": "local",
            "handler": "llama_cpp",
            "local_generation": {
                "reasoning_mode": "none",
                "sampling": {
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "top_k": 20,
                    "min_p": None,
                    "repeat_penalty": 1.05,
                },
                "output_budgets": {
                    "decision": 512,
                    "structured": 2048,
                    "narrative": 2048,
                    "general": 4096,
                    "agent_execution": 8192,
                    "final_synthesis": 16384,
                },
            },
        }
    )
    profile = resolve_runtime_model_profile(model)
    thinking_updates: list[tuple[int, str | None, bool]] = []

    def activity_callback(tokens: int, thinking: str | None, complete: bool) -> None:
        thinking_updates.append((tokens, thinking, complete))

    adapter = create_langchain_llm_from_llama_cpp(
        model,
        activity_callback=activity_callback,
        profile=profile,
        purpose="agent_execution",
    )
    assert adapter.temperature == 0.7
    assert adapter.top_p == 0.8
    assert adapter.top_k == 20
    assert adapter.repeat_penalty == 1.05
    assert adapter.max_tokens == 8192

    result = await adapter.ainvoke([HumanMessage(content="hi")])
    assert result.content == "Tool-ready answer."
    assert all(update[1] is None for update in thinking_updates)


@pytest.mark.asyncio
async def test_usage_bearing_response_reaches_telemetry_callback_unchanged():
    model = _model(
        f"{_OPEN}reasoning{_CLOSE}The answer.",
        usage={"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
    )
    captured: list[LocalCompletionTelemetry] = []

    result = await model.generate_response(
        "prompt",
        max_tokens=256,
        telemetry_callback=captured.append,
    )

    assert result == "The answer."
    assert len(captured) == 1
    telemetry = captured[0]
    assert telemetry.requested_output_tokens == 256
    assert telemetry.finish_reason == "stop"
    assert telemetry.prompt_tokens == 120
    assert telemetry.completion_tokens == 45
    assert telemetry.total_tokens == 165
    assert telemetry.completion_token_source == "usage"
    assert telemetry.raw_completion_tokens == 45
    assert telemetry.visible_completion_tokens == 2
    assert telemetry.lock_wait_ms >= 0
    assert telemetry.native_duration_ms >= 0


@pytest.mark.asyncio
async def test_missing_usage_uses_tokenizer_fallback_for_raw_and_visible_tokens():
    model = _model(
        f"{_OPEN}reasoning{_CLOSE}visible answer",
        tokenizer_tokens=[1, 2, 3, 4, 5, 6, 7],
    )
    captured: list[LocalCompletionTelemetry] = []

    await model.generate_response("prompt", telemetry_callback=captured.append)

    telemetry = captured[0]
    assert telemetry.completion_tokens is None
    assert telemetry.completion_token_source == "tokenizer_fallback"
    assert telemetry.raw_completion_tokens == 7
    assert telemetry.visible_completion_tokens == 7


@pytest.mark.asyncio
async def test_partial_usage_discards_prompt_and_total_when_completion_uses_fallback():
    model = _model(
        "visible answer",
        usage={"prompt_tokens": 100, "total_tokens": 105},
        tokenizer_tokens=[1, 2],
    )
    captured: list[LocalCompletionTelemetry] = []

    await model.generate_response("prompt", telemetry_callback=captured.append)

    telemetry = captured[0]
    assert telemetry.completion_token_source == "tokenizer_fallback"
    assert telemetry.raw_completion_tokens == 2
    assert telemetry.prompt_tokens is None
    assert telemetry.total_tokens is None


@pytest.mark.asyncio
async def test_tagged_reasoning_raw_token_count_exceeds_visible_token_count():
    raw = f"{_OPEN}long reasoning block with many tokens{_CLOSE}short"
    model = _model(raw, usage={"completion_tokens": 40})
    captured: list[LocalCompletionTelemetry] = []

    await model.generate_response("prompt", telemetry_callback=captured.append)

    telemetry = captured[0]
    assert telemetry.raw_completion_tokens == 40
    assert telemetry.visible_completion_tokens == 1


@pytest.mark.asyncio
async def test_length_finish_inside_reasoning_publishes_telemetry_before_truncation_error():
    model = _model(f"{_OPEN}still reasoning", finish_reason="length")
    captured: list[LocalCompletionTelemetry] = []

    with pytest.raises(ReasoningTruncatedError):
        await model.generate_response("prompt", max_tokens=128, telemetry_callback=captured.append)

    assert len(captured) == 1
    assert captured[0].finish_reason == "length"
    assert captured[0].visible_completion_tokens is None


@pytest.mark.asyncio
async def test_generate_response_string_contract_unchanged_without_callback():
    model = _model(f"{_OPEN}r{_CLOSE}answer")
    assert await model.generate_response("prompt") == "answer"


def test_tokenizer_wrapper_reports_exact_native_counts():
    wrapper = LlamaCppTokenizerWrapper(_FakeLlm("unused", "stop"))
    assert wrapper.exact_token_counts is True
    assert wrapper.encode("three short words") == [0, 1, 2]


@pytest.mark.asyncio
async def test_cached_load_sets_exact_tokenizer_and_native_context(monkeypatch, tmp_path):
    from api.core.models.reasoning import llama_cpp_model

    model_path = tmp_path / "cached.gguf"
    cached_llm = _FakeLlm("unused", "stop")
    monkeypatch.setattr(llama_cpp_model, "_MODEL_CACHE", {str(model_path.resolve()): cached_llm})
    model = LlamaCppModel.__new__(LlamaCppModel)
    model.state = ModelState.UNLOADED
    model.model_path = model_path

    await model.load()

    assert model.llm is cached_llm
    assert model.state == ModelState.READY
    assert isinstance(model.tokenizer, LlamaCppTokenizerWrapper)
    assert model.tokenizer.encode("two words") == [0, 1]
    assert model.max_context_length == 32_768
