"""search_activities applies the app filter, the title filter, and the sort order in SQL, before the limit."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Optional

import pytest

import api.dependencies as dependencies
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.tools.internal_basil_tools import activity_query_tool

FIRST_MOMENT = datetime(2024, 3, 1, 8, 0, 0)


@pytest.fixture
def service(tmp_path):
    return SQLiteKnowledgeService(str(tmp_path / "knowledge.db"))


async def _store(service, index: int, app_name: str = "Cursor", window_title: Optional[str] = None) -> str:
    return await service.store_activity(
        timestamp=FIRST_MOMENT + timedelta(minutes=index),
        app_name=app_name,
        window_title=window_title if window_title is not None else f"window {index}",
        extracted_text=f"text {index}",
    )


async def _store_many(service, count: int, app_for=lambda index: "Cursor") -> List[str]:
    return [await _store(service, index, app_name=app_for(index)) for index in range(count)]


def _titles(activities) -> List[str]:
    return [activity.window_title for activity in activities]


@pytest.mark.asyncio
async def test_the_default_keeps_the_newest_rows_newest_first(service):
    await _store_many(service, 30)
    found = await service.search_activities(limit=10)
    assert _titles(found) == [f"window {i}" for i in range(29, 19, -1)]


@pytest.mark.asyncio
async def test_oldest_first_returns_the_true_oldest_rows_in_order(service):
    await _store_many(service, 30)
    found = await service.search_activities(limit=10, newest_first=False)
    assert _titles(found) == [f"window {i}" for i in range(10)]


@pytest.mark.asyncio
async def test_the_app_filter_is_applied_before_the_limit(service):
    # The ten oldest rows are the target app; the newest forty are not, so a limit applied first would find none.
    await _store_many(service, 50, app_for=lambda index: "Target" if index < 10 else "Other")
    found = await service.search_activities(limit=5, app_name="Target")
    assert [activity.app_name for activity in found] == ["Target"] * 5
    assert _titles(found) == [f"window {i}" for i in range(9, 4, -1)]


@pytest.mark.asyncio
async def test_the_app_filter_is_exact_and_case_sensitive(service):
    await _store(service, 0, app_name="Cursor")
    await _store(service, 1, app_name="cursor")
    await _store(service, 2, app_name="Cursor Helper")
    found = await service.search_activities(app_name="Cursor")
    assert _titles(found) == ["window 0"]


@pytest.mark.asyncio
async def test_the_title_filter_is_a_case_insensitive_substring_applied_before_the_limit(service):
    await _store(service, 0, window_title="Quarterly REPORT draft")
    await _store_many_after(service, 1, 40)
    found = await service.search_activities(limit=3, window_title_contains="report")
    assert _titles(found) == ["Quarterly REPORT draft"]


async def _store_many_after(service, start: int, count: int) -> None:
    for index in range(start, start + count):
        await _store(service, index, window_title=f"other {index}")


@pytest.mark.asyncio
async def test_the_title_filter_folds_case_for_non_ascii_letters_like_python_does(service):
    await _store(service, 0, window_title="ÜBER den Wolken")
    await _store(service, 1, window_title="plain")
    found = await service.search_activities(window_title_contains="über")
    assert _titles(found) == ["ÜBER den Wolken"]


@pytest.mark.asyncio
async def test_the_title_filter_treats_percent_as_plain_text_not_a_wildcard(service):
    await _store(service, 0, window_title="100% done")
    await _store(service, 1, window_title="1000 done")
    found = await service.search_activities(window_title_contains="100%")
    assert _titles(found) == ["100% done"]


@pytest.mark.asyncio
async def test_the_filters_combine_with_the_time_range_and_the_sort_order(service):
    await _store_many(service, 20, app_for=lambda index: "Cursor" if index % 2 == 0 else "Other")
    window = {"start": FIRST_MOMENT + timedelta(minutes=4), "end": FIRST_MOMENT + timedelta(minutes=15)}
    found = await service.search_activities(time_range=window, app_name="Cursor", newest_first=False, limit=3)
    assert _titles(found) == ["window 4", "window 6", "window 8"]


@pytest.mark.asyncio
async def test_no_matches_gives_an_empty_list(service):
    await _store_many(service, 5)
    assert await service.search_activities(app_name="Nothing", window_title_contains="zzz") == []


@pytest.fixture
def tool_service(service, monkeypatch):
    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", lambda: service)
    return service


_WIDE_RANGE = {"start_time": "2023-01-01T00:00:00", "end_time": "2025-01-01T00:00:00"}


@pytest.mark.asyncio
async def test_the_tool_returns_the_true_oldest_rows_for_oldest_first(tool_service):
    await _store_many(tool_service, 30)
    response = json.loads(
        await activity_query_tool._query_activities_impl(**_WIDE_RANGE, limit=5, sort_order="oldest", max_output_chars=60_000)
    )
    assert [a["window_title"] for a in response["activities"]] == [f"window {i}" for i in range(5)]


@pytest.mark.asyncio
async def test_the_tool_returns_the_newest_rows_for_newest_first(tool_service):
    await _store_many(tool_service, 30)
    response = json.loads(
        await activity_query_tool._query_activities_impl(**_WIDE_RANGE, limit=5, sort_order="newest", max_output_chars=60_000)
    )
    assert [a["window_title"] for a in response["activities"]] == [f"window {i}" for i in range(29, 24, -1)]


@pytest.mark.asyncio
async def test_the_tool_finds_older_matches_that_an_unfiltered_limit_would_have_cut(tool_service):
    await _store_many(tool_service, 60, app_for=lambda index: "Target" if index < 3 else "Other")
    response = json.loads(
        await activity_query_tool._query_activities_impl(
            **_WIDE_RANGE, limit=2, app_name_filter="Target", max_output_chars=60_000
        )
    )
    assert response["count"] == 2
    assert {a["app_name"] for a in response["activities"]} == {"Target"}
