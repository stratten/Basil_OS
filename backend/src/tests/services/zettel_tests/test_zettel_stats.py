"""count_uncarded per source and the composed stats() the Memories UI reads."""

import pytest

from .conftest import NonClosingConnection
from api.services.zettel.materializer import ZettelMaterializer
from api.services.zettel.sources.configs import AGENT_TASK_CONFIG
from api.services.zettel.sources.screen_source import ScreenActivitySource
from api.services.zettel.sources.table_source import TableZettelSource

pytestmark = pytest.mark.use_temp_home


def _materializer(conn):
    materializer = ZettelMaterializer()
    materializer._connection = lambda: NonClosingConnection(conn)
    return materializer


def _insert_task(conn, task_id, timestamp="2026-07-24 10:00:00"):
    conn.execute(
        "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, "
        "status, created_at, updated_at) VALUES (?, ?, 'p', 'p', 'completed', ?, ?)",
        (task_id, timestamp, timestamp, timestamp),
    )


def test_count_uncarded_tracks_stamping(conn):
    _insert_task(conn, "t1")
    _insert_task(conn, "t2")
    source = TableZettelSource(AGENT_TASK_CONFIG)
    assert source.count_uncarded(conn, since_iso=None) == 2
    for draft in source.find_uncarded(conn, since_iso=None, limit=10):
        source.stamp(conn, draft, draft.entry_id)
    assert source.count_uncarded(conn, since_iso=None) == 0


def test_count_uncarded_respects_window(conn):
    _insert_task(conn, "old", timestamp="2020-01-01 10:00:00")
    source = TableZettelSource(AGENT_TASK_CONFIG)
    assert source.count_uncarded(conn, since_iso="2026-07-01T00:00:00+00:00") == 0
    assert source.count_uncarded(conn, since_iso=None) == 1


def test_screen_count_uncarded_counts_captures(conn):
    for i in range(3):
        conn.execute(
            "INSERT INTO activities (id, timestamp, created_at, app_name, window_title, "
            "extracted_text, ai_analysis, duration, context_hash) VALUES (?, ?, ?, 'App', "
            "'W', 't', '{}', 1.0, 'h')",
            (i, f"2026-07-24 10:0{i}:00", f"2026-07-24 10:0{i}:00"),
        )
    assert ScreenActivitySource().count_uncarded(conn, since_iso=None) == 3


def test_stats_reconcile_collected_and_waiting(conn):
    _insert_task(conn, "t1")
    _insert_task(conn, "t2")
    mat = _materializer(conn)

    before = mat.stats(since_iso=None, enabled_kinds={"agent_task"})
    assert before["collected"] == 0
    assert before["awaiting_collection"] == 2

    mat.run_pass(since_iso=None, enabled_kinds={"agent_task"})

    after = mat.stats(since_iso=None, enabled_kinds={"agent_task"})
    assert after["collected"] == 2
    assert after["awaiting_collection"] == 0
    # Freshly carded rows are pending a summary, none finalized yet.
    assert after["awaiting_summary"] == 2
    assert after["summarized"] == 0
    by_kind = {row["kind"]: row for row in after["by_source"]}
    assert by_kind["agent_task"]["collected"] == 2
    assert by_kind["agent_task"]["awaiting_collection"] == 0


def test_stream_counts_ignore_the_history_window(conn):
    """Stream counts must reflect the engine, which applies no date filter.

    Scoping these to history_days reported "0 summarized" against a database
    holding 197 summarized entries, because every one of their events predated
    a 7-day window while the narrative pass had processed them regardless.
    """
    _insert_task(conn, "ancient", timestamp="2025-02-25 10:00:00")
    mat = _materializer(conn)
    mat.run_pass(since_iso=None, enabled_kinds={"agent_task"})

    stats = mat.stats(since_iso="2026-07-18T00:00:00+00:00", enabled_kinds={"agent_task"})
    assert stats["collected"] == 1
    assert stats["awaiting_summary"] == 1
    # Waiting-to-collect stays window-scoped: carding genuinely will not reach
    # anything older, which is a true statement about that pass.
    assert stats["awaiting_collection"] == 0


def test_collected_closes_over_the_narrative_states(conn):
    """The four tiles read as one funnel, so collected must equal its parts."""
    from api.services.zettel import store

    _insert_task(conn, "t1")
    _insert_task(conn, "t2")
    mat = _materializer(conn)
    mat.run_pass(since_iso=None, enabled_kinds={"agent_task"})

    entry_id = conn.execute("SELECT id FROM zettel_entries LIMIT 1").fetchone()["id"]
    store.write_narrative(
        conn, entry_id, narrative="You did it.", model="m"
    )

    stats = mat.stats(since_iso=None, enabled_kinds={"agent_task"})
    assert stats["summarized"] == 1
    assert stats["awaiting_summary"] == 1
    assert stats["collected"] == (
        stats["summarized"]
        + stats["awaiting_summary"]
        + stats["awaiting_retry"]
        + stats["failed"]
    )


def test_stats_separates_runnable_and_retry_exhausted_pending_entries(conn):
    _insert_task(conn, "runnable")
    _insert_task(conn, "blocked")
    mat = _materializer(conn)
    mat.run_pass(since_iso=None, enabled_kinds={"agent_task"})

    blocked_id = conn.execute(
        "SELECT id FROM zettel_entries WHERE source_id = 'blocked'"
    ).fetchone()["id"]
    conn.execute(
        "UPDATE zettel_entries SET narrative_attempts = 3 WHERE id = ?",
        (blocked_id,),
    )

    stats = mat.stats(
        since_iso=None,
        enabled_kinds={"agent_task"},
        narrative_max_attempts=3,
    )

    assert stats["awaiting_summary"] == 1
    assert stats["awaiting_retry"] == 1
