"""Unit coverage for the opt-in cheap/tool-less path in call_agent_model_with_messages.

These tests are deterministic and never touch a live model or the network. They
verify that:
  - a search-capable cloud model, when the caller opts out of web search, is
    routed through generate_from_messages with web search forced off and the token
    cap forwarded (and chat_completion is NOT used), and
  - a model without _supports_web_search falls through to the standard
    chat_completion path unchanged even when web search is opted out, and
  - the default arguments (no opt-in) preserve the original chat_completion
    behavior, proving the other call_agent_model_with_messages consumers are
    unaffected.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from api.services.agent_processing.lifecycle.execution_graph.agent_model_caller import (
    call_agent_model_with_messages,
)


class _Metadata:
    def __init__(self, source: str):
        self.source = source


class _SearchCapableCloudModel:
    """Mimics Claude/OpenAI: exposes _supports_web_search and generate_from_messages."""

    def __init__(self) -> None:
        self.from_messages_calls: list[dict] = []
        self.generate_calls: list[dict] = []
        self.chat_completion_calls: list[list] = []

    def _supports_web_search(self) -> bool:
        return True

    def get_metadata(self) -> _Metadata:
        return _Metadata("anthropic_api")

    async def generate_from_messages(
        self,
        messages,
        *,
        max_tokens=None,
        preserve_thinking=False,
        enable_web_search=True,
    ) -> str:
        self.from_messages_calls.append(
            {
                "messages": messages,
                "max_tokens": max_tokens,
                "enable_web_search": enable_web_search,
            }
        )
        return '{"slug": null, "reason": "no relevant skill"}'

    async def generate_response(
        self, prompt: str, max_tokens: int = 1024, enable_web_search: bool = True
    ) -> str:
        self.generate_calls.append(
            {"prompt": prompt, "max_tokens": max_tokens, "enable_web_search": enable_web_search}
        )
        return "should-not-be-used"

    async def chat_completion(self, messages):
        self.chat_completion_calls.append(messages)
        return {"content": "should-not-be-used"}


class _PlainChatModel:
    """Mimics a non-search model (e.g. local transformers): no _supports_web_search."""

    def __init__(self) -> None:
        self.generate_calls: list[dict] = []
        self.chat_completion_calls: list[list] = []

    def get_metadata(self) -> _Metadata:
        return _Metadata("transformers")

    async def generate_response(self, prompt: str, max_tokens: int = 1024) -> str:
        self.generate_calls.append({"prompt": prompt, "max_tokens": max_tokens})
        return "unused"

    async def chat_completion(self, messages):
        self.chat_completion_calls.append(messages)
        return {"content": "standard chat answer"}


_MESSAGES = [
    {"role": "system", "content": "You are a classifier."},
    {"role": "user", "content": "pick a slug or null"},
]


@pytest.mark.asyncio
async def test_cheap_path_forwards_no_search_and_cap_on_capable_model():
    model = _SearchCapableCloudModel()

    result = await call_agent_model_with_messages(
        model, _MESSAGES, enable_web_search=False, max_tokens=400
    )

    assert result == '{"slug": null, "reason": "no relevant skill"}'
    assert len(model.from_messages_calls) == 1
    assert model.from_messages_calls[0]["messages"] == _MESSAGES
    assert model.from_messages_calls[0]["enable_web_search"] is False
    assert model.from_messages_calls[0]["max_tokens"] == 400
    assert model.generate_calls == []
    assert model.chat_completion_calls == []


@pytest.mark.asyncio
async def test_non_capable_model_falls_through_to_chat_completion():
    model = _PlainChatModel()

    result = await call_agent_model_with_messages(
        model, _MESSAGES, enable_web_search=False, max_tokens=400
    )

    assert result == "standard chat answer"
    assert model.generate_calls == []
    assert len(model.chat_completion_calls) == 1


@pytest.mark.asyncio
async def test_default_args_preserve_chat_completion_behavior():
    model = _SearchCapableCloudModel()

    result = await call_agent_model_with_messages(model, _MESSAGES)

    assert result == "should-not-be-used"
    assert len(model.chat_completion_calls) == 1
    assert model.from_messages_calls == []
    assert model.generate_calls == []


class _LocalLlamaModel:
    def __init__(self) -> None:
        self.model_name = "Qwen-qwen3-coder-30b-a3b-instruct-q4km"
        self.llm = object()
        self.model_path = type("P", (), {"stem": "qwen3-coder-30b-a3b-instruct-q4km"})()
        self.max_context_length = 32768
        self.max_tokens_to_sample = 65536
        self.native_execution_lock = object()

    def get_metadata(self) -> _Metadata:
        return _Metadata("llama.cpp")

    def apply_registry_config(self, config: dict) -> None:
        self.registry_config = config


@pytest.mark.asyncio
async def test_local_decision_call_honors_explicit_320_token_budget(monkeypatch):
    captured: dict = {}

    class _Adapter:
        async def ainvoke(self, _messages):
            return type("R", (), {"content": "decision"})()

    def fake_create(model, **kwargs):
        captured.update(kwargs)
        return _Adapter()

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.execution_graph.agent_model_caller.create_langchain_llm_from_llama_cpp",
        fake_create,
    )
    model = _LocalLlamaModel()

    result = await call_agent_model_with_messages(
        model,
        _MESSAGES,
        enable_web_search=False,
        max_tokens=320,
        purpose="decision",
    )

    assert result == "decision"
    assert captured["requested_output_tokens"] == 320
    assert captured["purpose"] == "decision"


@pytest.mark.asyncio
async def test_local_agent_execution_uses_registry_budget_when_unspecified(monkeypatch):
    captured: dict = {}

    class _Adapter:
        max_tokens = 0

        async def ainvoke(self, _messages):
            return type("R", (), {"content": "agent"})()

    def fake_create(model, **kwargs):
        captured.update(kwargs)
        adapter = _Adapter()
        from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile
        from api.core.models.reasoning.streaming_contract import resolve_generation_budget

        profile = resolve_runtime_model_profile(model)
        budget = resolve_generation_budget(model, purpose=kwargs.get("purpose", "general"))
        adapter.max_tokens = budget.effective_output_tokens
        return adapter

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.execution_graph.agent_model_caller.create_langchain_llm_from_llama_cpp",
        fake_create,
    )
    model = _LocalLlamaModel()

    result = await call_agent_model_with_messages(
        model,
        _MESSAGES,
        purpose="agent_execution",
    )

    assert result == "agent"
    assert captured["purpose"] == "agent_execution"
    assert captured.get("requested_output_tokens") is None
    from api.core.models.reasoning.streaming_contract import resolve_generation_budget

    expected = resolve_generation_budget(model, purpose="agent_execution").effective_output_tokens
    assert expected == 8192
    assert expected not in {4096, 65536}
