"""Paging, compact view, date-only parsing, and output budget for query_unified_history."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from .conftest import NonClosingConnection
from api.services.agent_processing.tools.internal_basil_tools.unified_history_tool import (
    _parse_time,
    _query_unified_history_impl,
    create_unified_history_tool,
)
from api.services.zettel import store
from api.services.zettel.sources.base import ZettelDraft

RANGE = {"start_time": "2026-07-27T00:00:00+00:00", "end_time": "2026-07-28T00:00:00+00:00"}


@pytest.fixture()
def new_york_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture()
def history_db(conn, monkeypatch):
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure import (
        connection as db_connection,
    )
    import api.dependencies as dependencies

    monkeypatch.setattr(
        db_connection, "get_sync_connection", lambda *a, **k: NonClosingConnection(conn)
    )
    monkeypatch.setattr(
        dependencies, "get_sqlite_knowledge_service", lambda: SimpleNamespace(db_path=":memory:")
    )
    return conn


def _card(conn, source_id: str, occurred_at: str, summary: str = "summary") -> None:
    store.insert_card(
        conn,
        ZettelDraft(
            source_kind="agent_task",
            source_id=source_id,
            event_type="agent_task",
            occurred_at=occurred_at,
            title=source_id,
            summary=summary,
        ),
    )


def test_date_only_value_is_local_midnight(new_york_tz):
    assert _parse_time("2026-07-25", datetime.now(timezone.utc)) == "2026-07-25T04:00:00+00:00"


def test_invalid_calendar_date_falls_back_to_default():
    default = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert _parse_time("2026-13-40", default) == default.isoformat()


@pytest.mark.asyncio
async def test_history_pages_cover_every_event_once(history_db):
    for index in range(5):
        _card(history_db, f"task-{index}", f"2026-07-27T1{index}:00:00+00:00")
    history_db.commit()
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        payload = json.loads(await _query_unified_history_impl(**RANGE, limit=2, cursor=cursor))
        pages += 1
        assert payload["success"] is True
        assert payload["total_in_range"] == 5
        assert all("narrative" not in event and "payload" not in event for event in payload["events"])
        seen.extend(event["source_id"] for event in payload["events"])
        cursor = payload["next_cursor"]
        if cursor is None:
            break
        assert pages < 10
    assert seen == ["task-4", "task-3", "task-2", "task-1", "task-0"]
    assert pages == 3


@pytest.mark.asyncio
async def test_history_rejects_malformed_cursor(history_db):
    payload = json.loads(await _query_unified_history_impl(**RANGE, cursor="not-a-cursor"))
    assert payload["success"] is False
    assert "next_cursor" in payload["error"]


@pytest.mark.asyncio
async def test_history_tool_applies_output_budget(history_db):
    for index in range(10):
        _card(history_db, f"long-{index}", f"2026-07-27T0{index}:00:00+00:00", summary="s" * 500)
    history_db.commit()
    tool = create_unified_history_tool(max_output_chars=4_000)
    payload = json.loads(await tool.ainvoke({**RANGE, "limit": 10, "view": "full"}))
    assert payload["count"] < 10
    assert payload["next_cursor"] is not None
    assert payload["total_in_range"] == 10


@pytest.mark.asyncio
async def test_history_group_counts_still_cover_the_whole_range(history_db):
    for index in range(4):
        _card(history_db, f"task-{index}", f"2026-07-27T1{index}:00:00+00:00")
    history_db.commit()
    payload = json.loads(
        await _query_unified_history_impl(**RANGE, limit=1, group_by="source_kind")
    )
    assert payload["count"] == 1
    assert payload["grouped_counts"] == {"agent_task": 4}
    assert payload["truncated"] is True
