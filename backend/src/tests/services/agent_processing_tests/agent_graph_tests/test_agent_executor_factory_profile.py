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
