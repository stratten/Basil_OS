"""Unit coverage for select_relevant_skill's opt-out of web search.

Deterministic; no live model. Verifies that skill selection forwards the
cheap/tool-less controls (enable_web_search=False and the decision token cap)
into call_agent_model_with_messages, and that the JSON reply handling for both
a chosen slug and a null selection is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pytest

from api.services.agent_processing.lifecycle.execution_graph import skill_selection
from api.services.agent_processing.lifecycle.execution_graph.skill_selection import (
    _DECISION_MAX_TOKENS,
    select_relevant_skill,
)


@dataclass
class _CatalogEntry:
    slug: str
    title: str
    when_to_use: str
    triggers: List[str] = field(default_factory=list)


def _catalog() -> List[_CatalogEntry]:
    return [
        _CatalogEntry(
            slug="convert-pdf",
            title="Convert PDF To Markdown",
            when_to_use="Use when converting a PDF into clean markdown.",
            triggers=["convert pdf", "pdf to markdown"],
        )
    ]


@pytest.mark.asyncio
async def test_select_relevant_skill_opts_out_of_web_search(monkeypatch):
    captured: dict = {}

    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        captured["enable_web_search"] = enable_web_search
        captured["max_tokens"] = max_tokens
        return '{"slug": "convert-pdf", "reason": "matches the pdf request"}'

    monkeypatch.setattr(skill_selection, "call_agent_model_with_messages", _fake_caller)

    selection = await select_relevant_skill(
        model=object(),
        user_request="please convert this pdf to markdown",
        catalog_entries=_catalog(),
    )

    assert captured["enable_web_search"] is False
    assert captured["max_tokens"] == _DECISION_MAX_TOKENS
    assert selection.slug == "convert-pdf"


@pytest.mark.asyncio
async def test_select_relevant_skill_null_selection_preserved(monkeypatch):
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        return '{"slug": null, "reason": "nothing relevant"}'

    monkeypatch.setattr(skill_selection, "call_agent_model_with_messages", _fake_caller)

    selection = await select_relevant_skill(
        model=object(),
        user_request="tell me a joke",
        catalog_entries=_catalog(),
    )

    assert selection.slug is None
    assert selection.reason == "nothing relevant"
