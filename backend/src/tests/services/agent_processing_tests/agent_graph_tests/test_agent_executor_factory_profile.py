"""LangChain factory uses runtime profile for token limits (OpenAI direct)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.claude_model import ClaudeModel
from api.core.models.reasoning.openai_model import OpenAIModel
from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
    create_langchain_llm,
)


def test_create_langchain_openai_passes_resolved_max_tokens():
    model = OpenAIModel(Path("/tmp"), {ModelCapability.REASONING})
    model.state = ModelState.READY
    model.api_key = "sk-test"
    model.model_name = "gpt-5.1"

    coordinator = MagicMock()
    coordinator._llm_model = model

    with patch("langchain_openai.ChatOpenAI") as ctor:
        ctor.return_value = MagicMock(name="ChatOpenAI")
        out = create_langchain_llm(coordinator)
        assert out is not None
        kwargs = ctor.call_args.kwargs
        assert kwargs["max_tokens"] >= 1
        assert kwargs["model"] == "gpt-5.1"
        assert kwargs["streaming"] is True


def test_create_langchain_anthropic_omits_registry_deprecated_temperature():
    model = ClaudeModel(Path("/tmp"), {ModelCapability.REASONING})
    model.state = ModelState.READY
    model.api_key = "sk-ant-test"
    model.model_name = "claude-opus-4-8"

    coordinator = MagicMock()
    coordinator._llm_model = model

    with patch("langchain_anthropic.ChatAnthropic") as ctor:
        ctor.return_value = MagicMock(name="ChatAnthropic")
        out = create_langchain_llm(coordinator)
        assert out is not None
        kwargs = ctor.call_args.kwargs
        assert kwargs["model"] == "claude-opus-4-8"
        assert kwargs["max_tokens"] >= 1
        assert kwargs["streaming"] is True
        assert "temperature" not in kwargs


def test_create_langchain_openai_reasoning_model_uses_responses_api():
    model = OpenAIModel(Path("/tmp"), {ModelCapability.REASONING})
    model.state = ModelState.READY
    model.api_key = "sk-test"
    model.model_name = "gpt-5.6-terra"

    coordinator = MagicMock()
    coordinator._llm_model = model

    with patch("langchain_openai.ChatOpenAI") as ctor:
        ctor.return_value = MagicMock(name="ChatOpenAI")
        out = create_langchain_llm(coordinator)
        assert out is not None
        kwargs = ctor.call_args.kwargs
        assert kwargs["model"] == "gpt-5.6-terra"
        assert kwargs["use_responses_api"] is True
        assert kwargs["output_version"] == "responses/v1"
        assert kwargs["reasoning"] == {"effort": "medium"}


def test_create_langchain_openai_non_reasoning_model_stays_chat_completions():
    model = OpenAIModel(Path("/tmp"), {ModelCapability.REASONING})
    model.state = ModelState.READY
    model.api_key = "sk-test"
    model.model_name = "gpt-4o"

    coordinator = MagicMock()
    coordinator._llm_model = model

    with patch("langchain_openai.ChatOpenAI") as ctor:
        ctor.return_value = MagicMock(name="ChatOpenAI")
        out = create_langchain_llm(coordinator)
        assert out is not None
        kwargs = ctor.call_args.kwargs
        assert kwargs["model"] == "gpt-4o"
        assert "use_responses_api" not in kwargs
        assert "output_version" not in kwargs
        assert "reasoning" not in kwargs


def _claude_coordinator(model_name: str) -> MagicMock:
    model = ClaudeModel(Path("/tmp"), {ModelCapability.REASONING})
    model.state = ModelState.READY
    model.api_key = "sk-ant-test"
    model.model_name = model_name
    coordinator = MagicMock()
    coordinator._llm_model = model
    return coordinator


def test_create_langchain_anthropic_enables_prompt_caching():
    with patch("langchain_anthropic.ChatAnthropic") as ctor:
        ctor.return_value = MagicMock(name="ChatAnthropic")
        create_langchain_llm(_claude_coordinator("claude-haiku-4-5-20251001"))
        kwargs = ctor.call_args.kwargs
        assert kwargs["model_kwargs"] == {"cache_control": {"type": "ephemeral"}}


def test_anthropic_request_payload_carries_top_level_cache_control():
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = create_langchain_llm(_claude_coordinator("claude-opus-4-8"))
    payload = llm._get_request_payload([SystemMessage("system"), HumanMessage("hello")])
    assert payload["cache_control"] == {"type": "ephemeral"}
    assert payload["model"] == "claude-opus-4-8"


def test_llm_output_log_fields_report_prompt_cache_usage():
    from langchain_core.messages import AIMessage

    from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
        _llm_output_log_fields,
    )

    cached = AIMessage(
        content="done",
        usage_metadata={
            "input_tokens": 9000,
            "output_tokens": 10,
            "total_tokens": 9010,
            "input_token_details": {"cache_read": 8000, "cache_creation": 1200},
        },
    )
    fields = _llm_output_log_fields(cached)
    assert "input_tokens=9000" in fields
    assert "cache_read=8000" in fields
    assert "cache_write=1200" in fields

    uncached = _llm_output_log_fields(AIMessage(content=""))
    assert "input_tokens=None" in uncached
    assert "cache_read=None" in uncached
    assert "cache_write=None" in uncached
