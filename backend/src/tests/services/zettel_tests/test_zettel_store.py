"""Card inserts, narrative writes, failure capping, and filtered reads."""

from api.services.zettel import store
from api.services.zettel.sources.base import ZettelDraft


def _draft(**overrides):
    base = dict(
        source_kind="agent_task",
        source_id="t1",
        event_type="agent_task_run",
        occurred_at="2026-07-24T10:00:00+00:00",
        title="A task",
    )
    base.update(overrides)
    return ZettelDraft(**base)


def test_first_card_inserts_and_repeat_is_ignored(conn):
    assert store.insert_card(conn, _draft()) is True
    assert store.insert_card(conn, _draft()) is False
    row = conn.execute(
        "SELECT narrative_state, narrative_attempts FROM zettel_entries"
    ).fetchone()
    assert row["narrative_state"] == "pending"
    assert row["narrative_attempts"] == 0


def test_same_source_never_duplicates(conn):
    for _ in range(5):
        store.insert_card(conn, _draft())
    assert conn.execute("SELECT COUNT(*) AS n FROM zettel_entries").fetchone()["n"] == 1


def test_store_enforces_the_bounds_it_is_given(conn):
    store.insert_card(conn, _draft(title="t" * 900, summary="s" * 2000))
    row = conn.execute("SELECT title, summary FROM zettel_entries").fetchone()
    assert len(row["title"]) <= 200
    assert len(row["summary"]) <= 500


def test_closed_narrative_becomes_final(conn):
    store.insert_card(conn, _draft())
    store.write_narrative(
        conn, "agent_task:t1", narrative="You did the thing.",
        model="m", is_open=False, open_note=None,
    )
    row = conn.execute(
        "SELECT narrative, narrative_state, is_open, narrative_attempts FROM zettel_entries"
    ).fetchone()
    assert row["narrative"] == "You did the thing."
    assert row["narrative_state"] == "final"
    assert row["is_open"] == 0
    # A successful swing is not a failed attempt; only record_failure increments.
    assert row["narrative_attempts"] == 0


def test_valid_narrative_is_final_even_with_retired_open_arguments(conn):
    store.insert_card(conn, _draft())
    store.write_narrative(
        conn, "agent_task:t1", narrative="Still working.",
        model="m", is_open=True, open_note="waiting on approval",
    )
    row = conn.execute(
        "SELECT narrative_state, is_open, open_note FROM zettel_entries"
    ).fetchone()
    assert row["narrative_state"] == "final"
    assert row["is_open"] == 0
    assert row["open_note"] is None


def test_failure_stays_pending_below_cap_then_fails(conn):
    store.insert_card(conn, _draft())
    store.record_failure(conn, "agent_task:t1", error="boom", max_attempts=3)
    assert conn.execute("SELECT narrative_state FROM zettel_entries").fetchone()[0] == "pending"
    store.record_failure(conn, "agent_task:t1", error="boom", max_attempts=3)
    store.record_failure(conn, "agent_task:t1", error="boom", max_attempts=3)
    row = conn.execute(
        "SELECT narrative_state, narrative_attempts FROM zettel_entries"
    ).fetchone()
    assert row["narrative_state"] == "failed"
    assert row["narrative_attempts"] == 3


def test_load_pending_returns_newest_first(conn):
    """Recent events are summarized first; a long backlog drains from the top.

    Oldest-first spent the entire model budget on the far end of the history -
    on the real database that meant grinding through February 2025 before ever
    reaching the current week.
    """
    for occurred_at in ("2025-02-25T10:00:00+00:00",
                        "2026-07-24T10:00:00+00:00",
                        "2026-01-15T10:00:00+00:00"):
        store.insert_card(conn, ZettelDraft(
            source_kind="agent_task", source_id=occurred_at,
            event_type="agent_task_run", occurred_at=occurred_at, title="t",
        ))

    pending = store.load_pending(conn, limit=10, max_attempts=3)
    assert [entry.occurred_at for entry in pending] == [
        "2026-07-24T10:00:00+00:00",
        "2026-01-15T10:00:00+00:00",
        "2025-02-25T10:00:00+00:00",
    ]


def test_load_pending_skips_capped_and_final(conn):
    store.insert_card(conn, _draft(source_id="a"))
    store.insert_card(conn, _draft(source_id="b"))
    store.write_narrative(
        conn, "agent_task:a", narrative="done", model="m", is_open=False, open_note=None
    )
    pending = store.load_pending(conn, limit=10, max_attempts=3)
    assert [entry.source_id for entry in pending] == ["b"]


def test_query_prefers_narrative_over_raw_summary(conn):
    store.insert_card(conn, _draft(summary="raw card text"))
    store.write_narrative(
        conn, "agent_task:t1", narrative="the real story",
        model="m", is_open=False, open_note=None,
    )
    entry = store.query_entries(conn, limit=10)[0]
    assert entry["summary"] == "the real story"
    assert entry["raw_summary"] == "raw card text"
    assert entry["narrative_state"] == "final"


def test_grouped_counts_cover_the_range_not_the_page(conn):
    for index in range(12):
        store.insert_card(conn, _draft(
            source_id=f"t{index}", occurred_at=f"2026-07-24T10:00:{index:02d}+00:00"
        ))
    for index in range(3):
        store.insert_card(conn, _draft(
            source_kind="transcription", source_id=f"x{index}",
            occurred_at=f"2026-07-24T11:00:{index:02d}+00:00",
        ))
    assert len(store.query_entries(conn, limit=2)) == 2
    counts = store.count_entries_by(conn, dimension="source_kind")
    assert counts == {"agent_task": 12, "transcription": 3}


def test_unknown_group_dimension_is_refused(conn):
    store.insert_card(conn, _draft())
    assert store.count_entries_by(conn, dimension="payload_json; DROP TABLE") == {}


def test_query_filters_by_range_and_kind(conn):
    store.insert_card(conn, _draft(source_id="t1", occurred_at="2026-07-20T10:00:00+00:00"))
    store.insert_card(conn, _draft(source_id="t2", occurred_at="2026-07-24T10:00:00+00:00"))
    results = store.query_entries(conn, start="2026-07-22T00:00:00+00:00", limit=10)
    assert [entry["source_id"] for entry in results] == ["t2"]
    assert store.query_entries(conn, source_kinds=["transcription"], limit=10) == []


def test_requeue_failed_resets_failed_rows(conn):
    store.insert_card(conn, _draft(source_id="dead"))
    store.insert_card(conn, _draft(source_id="alive"))
    for _ in range(3):
        store.record_failure(conn, "agent_task:dead", error="boom", max_attempts=3)
    assert store.requeue_failed(conn) == 1
    row = conn.execute(
        "SELECT narrative_state, narrative_attempts, narrative_error, narrative_at "
        "FROM zettel_entries WHERE source_id = 'dead'"
    ).fetchone()
    assert row["narrative_state"] == "pending"
    assert row["narrative_attempts"] == 0
    assert row["narrative_error"] is None
    assert row["narrative_at"] is None


def test_requeue_failed_leaves_final_and_pending_untouched(conn):
    store.insert_card(conn, _draft(source_id="final"))
    store.insert_card(conn, _draft(source_id="pending"))
    store.insert_card(conn, _draft(source_id="failed"))
    store.write_narrative(
        conn, "agent_task:final", narrative="done", model="m", is_open=False, open_note=None
    )
    for _ in range(3):
        store.record_failure(conn, "agent_task:failed", error="boom", max_attempts=3)
    assert store.requeue_failed(conn) == 1
    rows = {
        row["source_id"]: row["narrative_state"]
        for row in conn.execute("SELECT source_id, narrative_state FROM zettel_entries")
    }
    assert rows == {"final": "final", "pending": "pending", "failed": "pending"}


def test_requeue_failed_restores_attempts_burned_below_the_cap(conn):
    """A bad model run burns attempts on rows that never reach 'failed'.

    Those entries are the real damage: still pending, but one swing from being
    abandoned for a reason that no longer applies once the model changes.
    """
    store.insert_card(conn, _draft(source_id="scorched"))
    for _ in range(2):
        store.record_failure(conn, "agent_task:scorched", error="boom", max_attempts=3)
    before = conn.execute(
        "SELECT narrative_state, narrative_attempts FROM zettel_entries"
    ).fetchone()
    assert (before["narrative_state"], before["narrative_attempts"]) == ("pending", 2)

    assert store.requeue_failed(conn) == 1
    after = conn.execute(
        "SELECT narrative_attempts, narrative_error, narrative_at FROM zettel_entries"
    ).fetchone()
    assert after["narrative_attempts"] == 0
    assert after["narrative_error"] is None
    assert after["narrative_at"] is None


def test_requeue_failed_ignores_rows_with_nothing_to_repair(conn):
    """Untouched pending rows are not rewritten, so the count means repairs."""
    store.insert_card(conn, _draft(source_id="untouched"))
    assert store.requeue_failed(conn) == 0


def test_requeue_failed_reopens_pending_queue(conn):
    store.insert_card(conn, _draft(source_id="dead"))
    for _ in range(3):
        store.record_failure(conn, "agent_task:dead", error="boom", max_attempts=3)
    store.requeue_failed(conn)
    pending = store.load_pending(conn, limit=10, max_attempts=3)
    assert [entry.source_id for entry in pending] == ["dead"]


def test_repeated_successful_writes_remain_final(conn):
    store.insert_card(conn, _draft())
    for _ in range(5):
        store.write_narrative(
            conn, "agent_task:t1", narrative="Still going.",
            model="m", is_open=True, open_note="mid-run",
        )

    row = conn.execute(
        "SELECT narrative_state, narrative_attempts FROM zettel_entries"
    ).fetchone()
    assert row["narrative_state"] == "final"
    assert row["narrative_attempts"] == 0
    assert store.load_pending(conn, limit=10, max_attempts=3) == []


def test_failure_cannot_reopen_a_final_entry(conn):
    store.insert_card(conn, _draft())
    store.write_narrative(
        conn, "agent_task:t1", narrative="Still going.",
        model="m", is_open=True, open_note="mid-run",
    )
    for _ in range(3):
        store.record_failure(conn, "agent_task:t1", error="boom", max_attempts=3)

    row = conn.execute(
        "SELECT narrative_state, narrative_attempts FROM zettel_entries"
    ).fetchone()
    assert row["narrative_state"] == "final"
    assert row["narrative_attempts"] == 0


def test_write_narrative_still_stamps_narrative_at(conn):
    """touched_before relies on this; without it a run could not terminate."""
    store.insert_card(conn, _draft())
    store.write_narrative(
        conn, "agent_task:t1", narrative="Still going.",
        model="m", is_open=True, open_note="mid-run",
    )

    assert conn.execute(
        "SELECT narrative_at FROM zettel_entries"
    ).fetchone()["narrative_at"] is not None
