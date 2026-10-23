"""retrieve_basil_history paging arguments and per-model output budget plumbing."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    register_optional_tools,
)
from api.services.agent_processing.tools.internal_basil_tools import (
    retrieval_tool,
    unified_history_tool,
)


def test_cursor_is_rejected_outside_browse():
    with pytest.raises(ValidationError, match="cursor is only valid"):
        retrieval_tool.RetrievalToolInput(action="search", query="budget", cursor="abc")


def test_browse_defaults_to_compact_view():
    assert retrieval_tool.RetrievalToolInput(action="browse").view == "compact"


@pytest.mark.asyncio
async def test_browse_forwards_cursor_view_and_budget(monkeypatch):
    captured: dict = {}

    def browse(request):
        captured["request"] = request
        return {"success": True, "action": "browse", "events": [], "next_cursor": None}

    monkeypatch.setattr(
        retrieval_tool,
        "get_unified_retrieval_service",
        lambda: SimpleNamespace(browse=browse),
    )
    tool = retrieval_tool.create_retrieval_tool(max_output_chars=12_345)
    response = json.loads(
        await tool.ainvoke({"action": "browse", "cursor": "c1", "start_time": "2026-07-27"})
    )
    request = captured["request"]
    assert response["success"] is True
    assert request.cursor == "c1"
    assert request.view == "compact"
    assert request.max_output_chars == 12_345
    assert request.limit == 20
    assert request.start == "2026-07-27"


def test_retrieval_description_teaches_paging_and_day_first_reviews():
    description = retrieval_tool.create_retrieval_tool().description
    assert "next_cursor" in description
    assert "group_by='day'" in description
    assert "local midnight" in description


def test_optional_registry_passes_the_factory_output_budget(monkeypatch):
    calls: dict = {}

    def fake_retrieval(profile=None, max_output_chars=None):
        calls["retrieval"] = max_output_chars
        return SimpleNamespace(name="retrieve_basil_history")

    def fake_history(profile=None, max_output_chars=None):
        calls["history"] = max_output_chars
        return SimpleNamespace(name="query_unified_history")

    monkeypatch.setattr(retrieval_tool, "create_retrieval_tool", fake_retrieval)
    monkeypatch.setattr(unified_history_tool, "create_unified_history_tool", fake_history)
    factory = SimpleNamespace(
        logger=logging.getLogger("test.optional_registry"),
        profile=None,
        max_tool_output_chars=33_333,
        allow_child_interaction_tools=False,
        allow_provider_catalog=False,
        allow_delegated_agent=False,
    )
    tools: list = []
    tool_map: dict = {}
    warnings: list = []
    register_optional_tools(factory, tools, tool_map, warnings)
    assert calls == {"retrieval": 33_333, "history": 33_333}
    assert tool_map["retrieval.basil_history"].name == "retrieve_basil_history"
    assert tool_map["retrieval.unified_history"].name == "query_unified_history"
