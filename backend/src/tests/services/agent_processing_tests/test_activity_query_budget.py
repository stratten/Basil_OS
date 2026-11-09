"""query_activities stays inside the tool output budget and says how to ask for the rest."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

import api.dependencies as dependencies
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    register_optional_tools,
)
from api.services.agent_processing.tools.internal_basil_tools import activity_query_tool
from api.services.agent_processing.tools.internal_basil_tools.activity_query_budget import (
    DEFAULT_ACTIVITY_OUTPUT_CHARS,
    MIN_ACTIVITY_OUTPUT_CHARS,
    continuation_fields,
    fit_activities_to_budget,
    resolve_activity_budget,
)


def _record(index: int, text_chars: int = 1_000) -> dict:
    return {
        "id": f"a{index}",
        "timestamp": f"2026-11-05T10:{index // 60:02d}:{index % 60:02d}.000100",
        "app_name": "Cursor",
        "window_title": f"window {index}",
        "extracted_text": "x" * text_chars,
        "duration": 5.0,
        "ai_analysis": None,
        "capture_frequency_minutes": 1,
    }


def _stored_activity(index: int, text_chars: int) -> SimpleNamespace:
    record = _record(index, text_chars)
    return SimpleNamespace(
        id=record["id"],
        timestamp=datetime.fromisoformat(record["timestamp"]),
        app_name=record["app_name"],
        window_title=record["window_title"],
        extracted_text=record["extracted_text"],
        duration=record["duration"],
        ai_analysis=None,
        capture_frequency_minutes=1,
    )


@pytest.fixture
def stored(monkeypatch):
    """Make the tool read these activities, newest first, as the database does."""
    holder: dict = {"activities": []}

    async def search_activities(**kwargs):
        return list(holder["activities"])

    monkeypatch.setattr(
        dependencies,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(search_activities=search_activities),
    )
    return holder


def test_the_budget_defaults_and_has_a_floor():
    assert resolve_activity_budget(None) == DEFAULT_ACTIVITY_OUTPUT_CHARS == 60_000
    assert resolve_activity_budget(10) == MIN_ACTIVITY_OUTPUT_CHARS
    assert resolve_activity_budget(33_333) == 33_333


def test_records_that_fit_are_all_kept():
    kept, omitted = fit_activities_to_budget([_record(i, 100) for i in range(5)], 60_000)
    assert len(kept) == 5 and omitted == []


def test_the_leading_run_that_fits_is_kept_in_order_and_the_rest_is_omitted():
    records = [_record(i, 2_000) for i in range(40)]
    kept, omitted = fit_activities_to_budget(records, 20_000)
    assert 0 < len(kept) < 40
    assert kept + omitted == records


def test_the_first_record_is_kept_even_when_it_alone_exceeds_the_budget():
    records = [_record(0, 80_000), _record(1, 100)]
    kept, omitted = fit_activities_to_budget(records, 60_000)
    assert [r["id"] for r in kept] == ["a0"]
    assert [r["id"] for r in omitted] == ["a1"]


def test_no_records_gives_nothing_to_keep_or_omit():
    assert fit_activities_to_budget([], 60_000) == ([], [])


def test_a_newest_first_hint_gives_an_end_time_the_tool_reads_back_as_the_same_moment():
    omitted = [_record(7)]
    fields = continuation_fields(omitted, "newest", 60_000)
    boundary = fields["next_window"]["end_time"]
    parsed = activity_query_tool._parse_time_parameter(boundary)
    assert parsed.replace(tzinfo=None) == datetime.fromisoformat(omitted[0]["timestamp"])
    assert omitted[0]["timestamp"] <= boundary
    assert fields["budget_trimmed"] is True and fields["omitted_count"] == 1


def test_an_oldest_first_hint_gives_a_start_time_that_includes_the_first_omitted_record():
    omitted = [_record(7)]
    fields = continuation_fields(omitted, "oldest", 60_000)
    boundary = fields["next_window"]["start_time"]
    assert omitted[0]["timestamp"] >= boundary
    assert _record(6)["timestamp"] < boundary


def test_a_missing_timestamp_gives_a_message_without_a_next_window():
    fields = continuation_fields([{"id": "a1", "timestamp": None}], "newest", 60_000)
    assert "next_window" not in fields
    assert "narrow the time range" in fields["message"]


@pytest.mark.parametrize("count, phrase", [(1, "1 more matching activity was left out"), (3, "3 more matching activities were left out")])
def test_the_message_counts_what_was_left_out(count, phrase):
    fields = continuation_fields([_record(i) for i in range(count)], "newest", 60_000)
    assert phrase in fields["message"]
    assert "60,000 characters" in fields["message"]


@pytest.mark.asyncio
async def test_a_small_result_keeps_its_old_shape_and_has_no_trim_fields(stored):
    stored["activities"] = [_stored_activity(i, 200) for i in (3, 2, 1)]
    output = await activity_query_tool._query_activities_impl(start_time="today", max_output_chars=60_000)
    response = json.loads(output)
    assert list(response) == ["success", "count", "activities", "query_params"]
    assert response["count"] == 3
    assert "budget_trimmed" not in response and "next_window" not in response


@pytest.mark.asyncio
async def test_a_large_result_is_cut_to_the_budget_and_names_the_next_window(stored):
    stored["activities"] = [_stored_activity(i, 5_000) for i in range(59, -1, -1)]
    output = await activity_query_tool._query_activities_impl(start_time="today", limit=60, max_output_chars=30_000)
    response = json.loads(output)
    assert len(output) <= 30_000
    assert response["budget_trimmed"] is True
    assert response["count"] + response["omitted_count"] == 60
    assert response["activities"][0]["id"] == "a59"
    assert "end_time" in response["next_window"]
    assert response["activities"][-1]["timestamp"] > response["next_window"]["end_time"][:26]


@pytest.mark.asyncio
async def test_without_a_budget_the_default_ceiling_applies(stored):
    stored["activities"] = [_stored_activity(i, 5_000) for i in range(59, -1, -1)]
    output = await activity_query_tool._query_activities_impl(start_time="today", limit=60)
    assert len(output) <= DEFAULT_ACTIVITY_OUTPUT_CHARS
    assert json.loads(output)["budget_trimmed"] is True


@pytest.mark.asyncio
async def test_one_oversized_record_is_still_returned(stored):
    stored["activities"] = [_stored_activity(2, 70_000), _stored_activity(1, 100)]
    response = json.loads(await activity_query_tool._query_activities_impl(start_time="today", max_output_chars=60_000))
    assert response["count"] == 1 and response["omitted_count"] == 1
    assert response["activities"][0]["id"] == "a2"


@pytest.mark.asyncio
async def test_the_oldest_first_order_trims_from_the_newest_end(stored):
    stored["activities"] = [_stored_activity(i, 5_000) for i in range(59, -1, -1)]
    response = json.loads(
        await activity_query_tool._query_activities_impl(start_time="today", limit=60, sort_order="oldest", max_output_chars=30_000)
    )
    assert response["activities"][0]["id"] == "a0"
    assert "start_time" in response["next_window"]


@pytest.mark.asyncio
async def test_the_tool_built_with_a_budget_applies_it(stored):
    stored["activities"] = [_stored_activity(i, 5_000) for i in range(59, -1, -1)]
    tool = activity_query_tool.create_activity_query_tool(max_output_chars=12_000)
    output = await tool.ainvoke({"start_time": "today", "limit": 60})
    assert len(output) <= 12_000
    assert json.loads(output)["budget_trimmed"] is True


@pytest.mark.asyncio
async def test_a_database_error_still_returns_the_old_error_shape(monkeypatch):
    async def broken(**kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", lambda: SimpleNamespace(search_activities=broken))
    response = json.loads(await activity_query_tool._query_activities_impl(start_time="today", max_output_chars=60_000))
    assert response == {"success": False, "error": "database is locked", "activities": []}


def test_the_registry_passes_the_factory_output_budget(monkeypatch):
    calls: dict = {}

    def fake_activity_tool(profile=None, max_output_chars=None):
        calls["activity"] = max_output_chars
        return SimpleNamespace(name="query_activities")

    monkeypatch.setattr(activity_query_tool, "create_activity_query_tool", fake_activity_tool)
    factory = SimpleNamespace(
        logger=logging.getLogger("test.optional_registry"),
        profile=None,
        max_tool_output_chars=33_333,
        allow_child_interaction_tools=False,
        allow_provider_catalog=False,
        allow_delegated_agent=False,
    )
    tool_map: dict = {}
    register_optional_tools(factory, [], tool_map, [])
    assert calls == {"activity": 33_333}
    assert tool_map["activity.query"].name == "query_activities"
