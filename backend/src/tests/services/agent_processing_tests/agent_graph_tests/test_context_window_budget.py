"""Context-window resolution and prompt-size estimates used for proactive compaction."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

import api.core.models.models_registry.schema as registry_schema
from api.services.agent_processing.lifecycle.execution_graph import context_window_budget as budget


class _Llama:
    def n_ctx(self):
        return 8192


def _echo(text: str = "") -> str:
    return text


@pytest.mark.asyncio
async def test_adapter_answer_wins_over_other_sources():
    class Adapter:
        max_tokens = 1024

        async def aresolve_effective_context_window(self):
            return 16384

    assert await budget.resolve_context_window_tokens(Adapter(), {"model_id": "ignored"}) == 16384


@pytest.mark.asyncio
async def test_llama_window_then_registry_then_none(monkeypatch):
    monkeypatch.setattr(
        registry_schema,
        "get_model",
        lambda model_id: {"context_window": 200_000} if model_id == "claude-test" else None,
    )

    assert await budget.resolve_context_window_tokens(SimpleNamespace(_llama_instance=_Llama()), None) == 8192
    assert await budget.resolve_context_window_tokens(SimpleNamespace(), {"model_id": "claude-test"}) == 200_000
    assert await budget.resolve_context_window_tokens(SimpleNamespace(), {"model_id": "unknown"}) is None
    assert await budget.resolve_context_window_tokens(SimpleNamespace(), None) is None


@pytest.mark.asyncio
async def test_failing_adapter_lookup_falls_through():
    class Broken:
        async def aresolve_effective_context_window(self):
            raise RuntimeError("probe failed")

    assert await budget.resolve_context_window_tokens(Broken(), None) is None


def test_prompt_budget_subtracts_output_reserve_and_margin():
    assert budget.prompt_budget_tokens(SimpleNamespace(max_tokens=4096), 32_768) == 32_768 - 4096 - 1638
    assert budget.prompt_budget_tokens(SimpleNamespace(max_tokens=64_000), 16_384) == 16_384 - 4096 - 819
    assert budget.prompt_budget_tokens(SimpleNamespace(), 2_048) == budget.MIN_PROMPT_BUDGET_TOKENS
    assert budget.prompt_budget_tokens(SimpleNamespace(), None) is None
    assert budget.prompt_budget_tokens(SimpleNamespace(), 0) is None


def test_estimate_counts_text_tool_calls_and_tool_schemas():
    tool = StructuredTool.from_function(func=_echo, name="echo", description="Echo text back")
    args_text = '{"text": "' + "b" * 30 + '"}'
    messages = [
        HumanMessage(content="a" * 300),
        AIMessage(content="", tool_calls=[{"name": "echo", "args": {"text": "b" * 30}, "id": "c1", "type": "tool_call"}]),
    ]
    cache = {}

    base = budget.estimate_prompt_tokens(messages)
    with_extras = budget.estimate_prompt_tokens(messages, system_text="s" * 90, tools=[tool], tool_chars_cache=cache)

    assert base == int((300 + len("echo") + len(args_text)) / budget.CHARS_PER_TOKEN_ESTIMATE) + 1
    assert with_extras > base + 30
    assert cache["echo"] > 0


def test_model_display_label_prefers_the_registry_display_name(monkeypatch):
    monkeypatch.setattr(
        registry_schema,
        "get_model",
        lambda model_id: {"display_name": "Local Qwen"} if model_id == "local-qwen" else None,
    )
    llm = SimpleNamespace(model_name="adapter-name", model_identifier="qwen2.5:1.5b")

    assert budget.model_display_label(llm, {"model_id": "local-qwen"}) == "Local Qwen"
    assert budget.model_display_label(llm, {"model_id": "unregistered"}) == "unregistered"
    assert budget.model_display_label(llm, None) == "adapter-name"
    assert budget.model_display_label(SimpleNamespace(model_identifier="qwen2.5:1.5b"), {}) == "qwen2.5:1.5b"
    assert budget.model_display_label(SimpleNamespace(), None) == ""


def test_context_window_exceeded_text_names_the_model_window_and_fix():
    message = budget.context_window_exceeded_message(
        model_label="Local Qwen", window_tokens=16_384, actual_tokens=17_200, completed_steps=3
    )
    reason = budget.context_window_exceeded_reason({"model": "Local Qwen", "max_tokens": 16_384, "actual_tokens": 17_200})
    unknown = budget.context_window_exceeded_reason({})

    assert message == (
        "Stopped: this task needed more context than Local Qwen's 16,384-token context window holds (it needed about 17,200 tokens), "
        "even after Basil removed older tool results. 3 tool step(s) completed before it stopped. "
        + budget.CONTEXT_WINDOW_FIX_HINT
    )
    assert reason == (
        "This task needed more context than Local Qwen's 16,384-token context window holds (it needed about 17,200 tokens). "
        + budget.CONTEXT_WINDOW_FIX_HINT
    )
    assert unknown.startswith("This task needed more context than the selected model's context window holds. ")
