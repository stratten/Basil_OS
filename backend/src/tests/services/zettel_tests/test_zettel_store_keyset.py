"""Deterministic newest-first ordering, keyset cursors, and local-day grouping in the zettel store."""

from __future__ import annotations

import time

import pytest

from api.services.zettel import store
from api.services.zettel.sources.base import ZettelDraft

TIED = "2026-07-27T15:00:00+00:00"


@pytest.fixture()
def new_york_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _card(conn, kind: str, source_id: str, occurred_at: str) -> None:
    store.insert_card(
        conn,
        ZettelDraft(
            source_kind=kind,
            source_id=source_id,
            event_type=kind,
            occurred_at=occurred_at,
            title=source_id,
        ),
    )


def _seed(conn) -> None:
    _card(conn, "agent_task", "a-1", TIED)
    _card(conn, "agent_task", "a-2", TIED)
    _card(conn, "transcription", "t-1", TIED)
    _card(conn, "agent_task", "older", "2026-07-27T09:00:00+00:00")
    conn.commit()


def test_ties_order_by_kind_then_id_descending(conn):
    _seed(conn)
    rows = store.query_entries(conn, limit=10)
    assert [(row["source_kind"], row["source_id"]) for row in rows] == [
        ("transcription", "t-1"),
        ("agent_task", "a-2"),
        ("agent_task", "a-1"),
        ("agent_task", "older"),
    ]


def test_before_key_excludes_the_key_and_everything_newer(conn):
    _seed(conn)
    rows = store.query_entries(conn, limit=10, before=(TIED, "agent_task", "a-2"))
    assert [row["source_id"] for row in rows] == ["a-1", "older"]


def test_with_keyset_before_composes_with_and_without_filters():
    assert store.with_keyset_before("", [], None) == ("", [])
    clause, params = store.with_keyset_before("", [], ("t", "k", "i"))
    assert clause == "WHERE " + store.KEYSET_BEFORE_CLAUSE
    assert params == ["t", "k", "i"]
    clause, params = store.with_keyset_before("WHERE occurred_at >= ?", ["s"], ("t", "k", "i"))
    assert clause == "WHERE occurred_at >= ? AND " + store.KEYSET_BEFORE_CLAUSE
    assert params == ["s", "t", "k", "i"]


def test_day_counts_use_local_calendar_day(conn, new_york_tz):
    _card(conn, "agent_task", "late", "2026-07-28T03:30:00+00:00")
    _card(conn, "agent_task", "noon", "2026-07-28T16:00:00+00:00")
    conn.commit()
    assert store.count_entries_by(conn, dimension="day") == {
        "2026-07-27": 1,
        "2026-07-28": 1,
    }
