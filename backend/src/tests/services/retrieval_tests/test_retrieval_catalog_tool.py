from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.internal_basil_tools import retrieval_tool
from api.services.retrieval.registry import build_default_retrieval_registry


def test_default_registry_exposes_stable_source_descriptors():
    descriptors = build_default_retrieval_registry().describe_sources()
    by_kind = {descriptor["source_kind"]: descriptor for descriptor in descriptors}

    assert list(by_kind) == sorted(by_kind)
    assert by_kind["meeting"] == {
        "source_kind": "meeting",
        "display_name": "Recorded Basil meetings",
        "authority": "primary",
        "evidence_kind": "observed Basil meeting recording and transcript",
        "browse_guidance": "Use for recorded meetings in a requested time range; cards are grouped logical meetings.",
        "detail_guidance": "Use detail for current merged transcript, metadata, and meeting analyses.",
        "supported_actions": ["browse", "search", "aggregate", "detail"],
    }
    assert by_kind["assistant_output"]["authority"] == "derived"
    assert "catalog" not in by_kind["meeting"]["supported_actions"]


@pytest.mark.asyncio
async def test_retrieval_tool_catalog_action_returns_live_descriptors(monkeypatch):
    expected = {
        "success": True,
        "action": "catalog",
        "sources": [{"source_kind": "meeting", "authority": "primary"}],
    }
    monkeypatch.setattr(
        retrieval_tool,
        "get_unified_retrieval_service",
        lambda: SimpleNamespace(catalog=lambda: expected),
    )

    tool = retrieval_tool.create_retrieval_tool()
    response = json.loads(await tool.ainvoke({"action": "catalog"}))

    assert response == expected
