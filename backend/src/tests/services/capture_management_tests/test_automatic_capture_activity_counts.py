"""Tests for the durable automatic-capture activity count used by the
Capture Management "Activities Captured" figures.

This is distinct from the raw screenshot *file* counts in
capture_management_service.py: an activity row can outlive its screenshot
file (e.g. dedup compaction removes the file but keeps the activity), so a
correct "how many captures happened" figure has to come from the database,
not the filesystem.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService


def _insert_activity(
    conn: sqlite3.Connection,
    *,
    activity_id: str,
    timestamp: datetime,
    automatic: bool,
) -> None:
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, window_title) VALUES (?, ?, ?, ?)",
        (activity_id, timestamp.isoformat(), "TestApp", "Window"),
    )
    if automatic:
        conn.execute(
            "INSERT INTO activity_metadata (activity_id, key, value) VALUES (?, 'automatic_capture', 'True')",
            (activity_id,),
        )


@pytest.fixture
def knowledge_service(tmp_path: Path) -> SQLiteKnowledgeService:
    db_path = tmp_path / "knowledge_base.db"
    return SQLiteKnowledgeService(db_path)


@pytest.mark.asyncio
async def test_counts_only_automatic_capture_activities(knowledge_service: SQLiteKnowledgeService) -> None:
    now = datetime.now()
    conn = sqlite3.connect(str(knowledge_service.db_path))
    try:
        _insert_activity(conn, activity_id="auto-1", timestamp=now, automatic=True)
        _insert_activity(conn, activity_id="auto-2", timestamp=now, automatic=True)
        _insert_activity(conn, activity_id="manual-1", timestamp=now, automatic=False)
        conn.commit()
    finally:
        conn.close()

    count = await knowledge_service.count_automatic_captures_since(None)

    assert count == 2


@pytest.mark.asyncio
async def test_counts_respect_the_cutoff_timestamp(knowledge_service: SQLiteKnowledgeService) -> None:
    now = datetime.now()
    conn = sqlite3.connect(str(knowledge_service.db_path))
    try:
        _insert_activity(conn, activity_id="recent", timestamp=now, automatic=True)
        _insert_activity(conn, activity_id="old", timestamp=now - timedelta(days=40), automatic=True)
        conn.commit()
    finally:
        conn.close()

    cutoff = now - timedelta(days=29)
    count = await knowledge_service.count_automatic_captures_since(cutoff)

    assert count == 1


@pytest.mark.asyncio
async def test_returns_zero_when_no_automatic_captures_exist(knowledge_service: SQLiteKnowledgeService) -> None:
    count = await knowledge_service.count_automatic_captures_since(None)

    assert count == 0


@pytest.mark.asyncio
async def test_counts_beyond_the_thousand_row_limit_used_by_search_activities(
    knowledge_service: SQLiteKnowledgeService,
) -> None:
    """Regression guard: count_automatic_captures_since must not silently cap
    results the way search_activities(limit=1000) does at real capture volume."""
    now = datetime.now()
    conn = sqlite3.connect(str(knowledge_service.db_path))
    try:
        for i in range(1200):
            _insert_activity(conn, activity_id=f"auto-{i}", timestamp=now, automatic=True)
        conn.commit()
    finally:
        conn.close()

    count = await knowledge_service.count_automatic_captures_since(None)

    assert count == 1200
