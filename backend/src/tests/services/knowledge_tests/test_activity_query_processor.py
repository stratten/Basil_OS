from __future__ import annotations

import pytest

from api import dependencies
from api.core.knowledge.query.activity_query_processor import ActivityQueryProcessor


@pytest.mark.asyncio
async def test_activity_query_processor_calls_sqlite_without_legacy_month_window() -> None:
    captured: dict[str, object] = {}

    class _KnowledgeService:
        async def search_activities(self, **kwargs):
            captured.update(kwargs)
            return []

    processor = ActivityQueryProcessor(_KnowledgeService())

    activities = await processor._search_activities_with_context(
        time_range=None,
        text_search="project",
        metadata_filters=None,
        limit=10,
    )

    assert activities == []
    assert captured == {
        "time_range": None,
        "text_search": "project",
        "metadata_filters": None,
        "limit": 10,
    }


def test_knowledge_service_compatibility_alias_returns_sqlite_singleton(monkeypatch) -> None:
    expected = object()
    dependencies.get_knowledge_service.cache_clear()
    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", lambda: expected)

    assert dependencies.get_knowledge_service() is expected
    assert dependencies.get_knowledge_service() is expected
    dependencies.get_knowledge_service.cache_clear()
