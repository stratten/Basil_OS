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


def test_context_trimmed_notice_names_the_characters_removed_and_protects_attachments():
    notice = budget.context_trimmed_notice(
        {"model": "Local Qwen", "window_tokens": 32_768, "request_chars_removed": 4_000, "fixed_over_limit": False}
    )

    assert notice == (
        "To fit Local Qwen's 32,768-token context window, Basil removed about 4,000 characters of earlier context from your request "
        "(files and folders you attached are never removed), so the answer may miss details from it. "
        + budget.CONTEXT_WINDOW_FIX_HINT
    )


def test_context_trimmed_notice_says_when_the_tools_alone_fill_the_window():
    notice = budget.context_trimmed_notice(
        {"model": "Local Qwen", "window_tokens": 32_768, "fixed_prompt_tokens": 30_100, "request_chars_removed": 0, "fixed_over_limit": True}
    )

    assert notice == (
        "Basil's system prompt and tools alone use about 30,100 tokens of Local Qwen's 32,768-token context window, "
        "so there is little or no room for your request and the answer may be incomplete or fail. "
        + budget.CONTEXT_WINDOW_FIX_HINT
    )


def test_context_trimmed_notice_combines_both_causes_in_one_message():
    notice = budget.context_trimmed_notice(
        {"model": "Local Qwen", "window_tokens": 32_768, "fixed_prompt_tokens": 30_100, "request_chars_removed": 1_500, "fixed_over_limit": True}
    )

    assert notice.count(budget.CONTEXT_WINDOW_FIX_HINT) == 1
    assert "tools alone use about 30,100 tokens" in notice
    assert "removed about 1,500 characters" in notice


def test_context_trimmed_notice_is_empty_when_nothing_was_cut_and_the_fixed_prompt_fits():
    assert budget.context_trimmed_notice({"model": "Local Qwen", "request_chars_removed": 0, "fixed_over_limit": False}) == ""
    assert budget.context_trimmed_notice({}) == ""


def test_the_answer_gets_the_notice_appended_after_a_blank_line():
    details = {"model": "Local Qwen", "window_tokens": 32_768, "request_chars_removed": 4_000, "fixed_over_limit": False}

    text = budget.with_context_trimmed_notice("The answer.\n", {"output": "x", "context_trimmed": details})

    assert text == "The answer.\n\n" + budget.context_trimmed_notice(details)


def test_the_answer_is_unchanged_without_a_cut_or_after_a_context_overflow_or_when_already_noted():
    details = {"model": "Local Qwen", "window_tokens": 32_768, "request_chars_removed": 4_000}
    notice = budget.context_trimmed_notice(details)

    assert budget.with_context_trimmed_notice("The answer.", {"output": "x"}) == "The answer."
    assert budget.with_context_trimmed_notice("The answer.", None) == "The answer."
    assert budget.with_context_trimmed_notice("The answer.", {"context_trimmed": "not a dict"}) == "The answer."
    assert budget.with_context_trimmed_notice("The answer.", {"context_trimmed": {"request_chars_removed": 0}}) == "The answer."
    assert (
        budget.with_context_trimmed_notice("Stopped.", {"context_window_exceeded": {"model": "Local Qwen"}, "context_trimmed": details})
        == "Stopped."
    )
    already = f"The answer.\n\n{notice}"
    assert budget.with_context_trimmed_notice(already, {"context_trimmed": details}) == already


def test_a_context_cut_recorded_by_the_run_flags_reaches_the_answer_text():
    from api.services.agent_processing.lifecycle.execution_graph.agent_loop_model_recovery import AgentRunFlags

    flags = AgentRunFlags(
        context_trimmed={"model": "Local Qwen", "window_tokens": 32_768, "fixed_prompt_tokens": 30_100, "request_chars_removed": 0, "fixed_over_limit": True}
    )
    result = {"output": "x", **flags.as_result_fields()}

    text = budget.with_context_trimmed_notice("The answer.", result)

    assert text.startswith("The answer.\n\nBasil's system prompt and tools alone use about 30,100 tokens")
    assert text.endswith(budget.CONTEXT_WINDOW_FIX_HINT)


def test_context_trimmed_notice_falls_back_to_generic_wording_when_the_model_and_window_are_unknown():
    notice = budget.context_trimmed_notice({"request_chars_removed": 2_000})

    assert notice.startswith("To fit the selected model's context window, Basil removed about 2,000 characters")
