"""Tests for registry-driven Anthropic thinking request configuration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.models_registry import get_thinking_request_config
from api.core.models.reasoning.claude_model import ClaudeModel
from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
    create_langchain_llm,
)


def test_get_thinking_request_config_adaptive_sonnet_5():
    cfg = get_thinking_request_config("claude-sonnet-5")
    assert cfg is not None
    # display is registry-driven (default_display) and must be threaded inside the
    # thinking dict so langchain-anthropic can round-trip thinking blocks while streaming.
    assert cfg["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert cfg["effort"] == "high"
    assert cfg["omit_sampling"] is True


def test_get_thinking_request_config_adaptive_display_is_registry_driven():
    """default_display comes from the registry; when absent, no display is emitted."""
    with patch(
        "api.core.models.models_registry.thinking_config.get_model",
        return_value={
            "feature_config": {
                "adaptive_thinking": {"type": "adaptive", "default_effort": "low"}
            }
        },
    ):
        cfg = get_thinking_request_config("hypothetical-adaptive-no-display")
    assert cfg is not None
    assert cfg["thinking"] == {"type": "adaptive"}
    assert "display" not in cfg["thinking"]
    assert cfg["effort"] == "low"


def test_get_thinking_request_config_extended_sonnet_4_6():
    cfg = get_thinking_request_config("claude-sonnet-4-6")
    assert cfg is not None
    assert cfg["thinking"]["type"] == "enabled"
    assert isinstance(cfg["thinking"]["budget_tokens"], int)
    assert cfg["omit_sampling"] is True


def test_get_thinking_request_config_non_thinking_model():
    assert get_thinking_request_config("gpt-4o") is None


def test_create_langchain_anthropic_adaptive_thinking_sonnet_5():
    model = ClaudeModel(Path("/tmp"), {ModelCapability.REASONING})
    model.state = ModelState.READY
    model.api_key = "sk-ant-test"
    model.model_name = "claude-sonnet-5"

    coordinator = MagicMock()
    coordinator._llm_model = model

    with patch("langchain_anthropic.ChatAnthropic") as ctor:
        ctor.return_value = MagicMock(name="ChatAnthropic")
        out = create_langchain_llm(coordinator)
        assert out is not None
        kwargs = ctor.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-5"
        assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert kwargs["effort"] == "high"
        assert "temperature" not in kwargs


def test_claude_model_apply_thinking_to_api_params():
    model = ClaudeModel.__new__(ClaudeModel)
    model.model_name = "claude-sonnet-5"
    api_params = {"model": "claude-sonnet-5", "messages": [], "max_tokens": 4096, "temperature": 0.7}
    model._apply_thinking_to_api_params(api_params)
    assert api_params["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert api_params["output_config"] == {"effort": "high"}
    assert "temperature" not in api_params
