"""Unit coverage for web_search model-aware routing.

These tests are deterministic and never touch a live model or the network. They
verify that:
  - a local / non-native-search active model is handed off to the browser-driven
    path (no generate_response call), and
  - a cloud / native-search active model keeps the native web search path, and
  - when no model is pinned, the routing branches on the resolved model's
    registry capability.
"""

from __future__ import annotations

import json

import pytest

import api.dependencies as api_dependencies
import api.services.model_usage_service as model_usage_module
from api.services.agent_processing.tools.external_services import web_search_tool


class _FakeModel:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.generate_calls: list[dict] = []

    async def generate_response(self, prompt: str, max_tokens: int = 1024, enable_web_search: bool = False) -> str:
        self.generate_calls.append({
            "prompt": prompt,
            "max_tokens": max_tokens,
            "enable_web_search": enable_web_search,
        })
        return "Synthesized native web answer."


def _install_fake_resolution(monkeypatch, model: _FakeModel) -> None:
    """Make the in-function model resolution return ``model``."""

    class _FakeUsageService:
        def __init__(self, _service):
            pass

        async def get_model_for_task(self, capabilities, explicit_model_id=None):
            return model

    monkeypatch.setattr(api_dependencies, "get_model_service", lambda: object())
    monkeypatch.setattr(model_usage_module, "ModelUsageService", _FakeUsageService)


@pytest.mark.asyncio
async def test_local_model_hands_off_to_browser(monkeypatch):
    monkeypatch.setattr(
        web_search_tool, "get_current_agent_context",
        lambda: {"model_id": "Qwen-qwen35-4b"},
    )
    monkeypatch.setattr(web_search_tool, "has_feature", lambda model_id, feature: False)

    # Adversarial: prove no model is resolved on the local path. If resolution
    # were attempted, this would raise instead of returning a handoff.
    def _boom():
        raise AssertionError("model resolution must not happen for a local model")

    monkeypatch.setattr(api_dependencies, "get_model_service", _boom)

    result = await web_search_tool._web_search_impl(query="latest react release", focus="release notes")
    parsed = json.loads(result)

    assert parsed["success"] is False
    assert parsed["web_access"] == "browser_required"
    assert parsed["model_used"] == "Qwen-qwen35-4b"
    assert parsed["suggested_search_url"].startswith("https://lite.duckduckgo.com/lite/?q=")
    assert "latest+react+release" in parsed["suggested_search_url"]
    assert any('browser_inspect(focus="content")' in step for step in parsed["next_actions"])
    assert parsed["search_results"] is None


@pytest.mark.asyncio
async def test_cloud_model_uses_native_search(monkeypatch):
    fake_model = _FakeModel("claude-sonnet-4")

    monkeypatch.setattr(
        web_search_tool, "get_current_agent_context",
        lambda: {"model_id": "claude-sonnet-4"},
    )
    monkeypatch.setattr(web_search_tool, "has_feature", lambda model_id, feature: True)
    _install_fake_resolution(monkeypatch, fake_model)

    result = await web_search_tool._web_search_impl(query="current price of a standing desk")
    parsed = json.loads(result)

    assert parsed["success"] is True
    assert parsed["has_web_access"] is True
    assert parsed["model_used"] == "claude-sonnet-4"
    assert parsed["search_results"] == "Synthesized native web answer."
    assert len(fake_model.generate_calls) == 1
    assert fake_model.generate_calls[0]["enable_web_search"] is True


@pytest.mark.asyncio
async def test_unpinned_local_preferred_model_hands_off(monkeypatch):
    # No model_id in context: routing must branch on the resolved model.
    fake_model = _FakeModel("Qwen-qwen3-8b")

    monkeypatch.setattr(web_search_tool, "get_current_agent_context", lambda: {})
    monkeypatch.setattr(web_search_tool, "has_feature", lambda model_id, feature: False)
    _install_fake_resolution(monkeypatch, fake_model)

    result = await web_search_tool._web_search_impl(query="who won the match")
    parsed = json.loads(result)

    assert parsed["success"] is False
    assert parsed["web_access"] == "browser_required"
    assert parsed["model_used"] == "Qwen-qwen3-8b"
    # The native path must never run on a non-capable model.
    assert fake_model.generate_calls == []
