"""Memory consumption is a per-row stamp, not a moving cursor.

The pipeline's other stages find work by an indexed IS NULL scan (zettel_id on
source rows, narrative_state here), and this stage now matches. These tests pin
the property that motivated the change: the narrative pass may settle entries in
any event order, and nothing may be skipped because of it.
"""

from types import SimpleNamespace

import pytest

from .conftest import NonClosingConnection
from api.services.zettel import memory_bridge, store
from api.services.zettel.sources.base import ZettelDraft


@pytest.fixture()
def bridge(conn, monkeypatch):
    """Point the bridge's self-opened connections at the test database."""
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
    return memory_bridge


def _settled(
    conn,
    source_id,
    *,
    occurred_at,
    narrative_at,
    kind="transcription",
    narrative="You did a thing.",
):
    """Insert an entry and finalize it, with narrative_at pinned for the test."""
    store.insert_card(conn, ZettelDraft(
        source_kind=kind, source_id=source_id, event_type=f"{kind}_run",
        occurred_at=occurred_at, title=f"Entry {source_id}",
    ))
    entry_id = conn.execute(
        "SELECT id FROM zettel_entries WHERE source_kind = ? AND source_id = ?",
        (kind, source_id),
    ).fetchone()["id"]
    store.write_narrative(
        conn, entry_id, narrative=narrative, model="m", is_open=False, open_note=None
    )
    conn.execute(
        "UPDATE zettel_entries SET narrative_at = ? WHERE id = ?", (narrative_at, entry_id)
    )
    return entry_id


def test_all_settled_entries_are_returned_once(bridge, conn):
    _settled(conn, "a", occurred_at="2025-02-01T00:00:00+00:00",
             narrative_at="2026-07-25T10:00:00+00:00")
    _settled(conn, "b", occurred_at="2026-07-20T00:00:00+00:00",
             narrative_at="2026-07-25T10:00:01+00:00")

    signals, entry_ids = bridge.load_unswept_signals()
    assert len(signals) == 2
    assert len(entry_ids) == 2


def test_stamped_entries_are_not_returned_again(bridge, conn):
    _settled(conn, "a", occurred_at="2025-02-01T00:00:00+00:00",
             narrative_at="2026-07-25T10:00:00+00:00")
    signals, entry_ids = bridge.load_unswept_signals()
    assert len(signals) == 1

    assert bridge.mark_swept(entry_ids) == 1
    again, again_ids = bridge.load_unswept_signals()
    assert again == [] and again_ids == []


def test_an_old_event_settled_after_a_newer_one_is_still_swept(bridge, conn):
    """The regression this change exists for.

    A timestamp cursor on occurred_at would advance to the July 2026 entry and
    then permanently skip the February 2025 entry that settled afterwards. With
    a per-row stamp the settle order is irrelevant.
    """
    _settled(conn, "recent", occurred_at="2026-07-20T00:00:00+00:00",
             narrative_at="2026-07-25T10:00:00+00:00")
    _, first_ids = bridge.load_unswept_signals()
    bridge.mark_swept(first_ids)

    # Settled later, but its event is 16 months older than what we just swept.
    _settled(conn, "ancient", occurred_at="2025-02-25T00:00:00+00:00",
             narrative_at="2026-07-25T11:00:00+00:00")

    signals, entry_ids = bridge.load_unswept_signals()
    assert len(signals) == 1
    assert signals[0].occurred_at == "2025-02-25T00:00:00+00:00"
    assert len(entry_ids) == 1


def test_pending_and_failed_entries_are_ignored(bridge, conn):
    store.insert_card(conn, ZettelDraft(
        source_kind="transcription", source_id="p1", event_type="transcription_run",
        occurred_at="2026-07-20T00:00:00+00:00", title="still pending",
    ))
    entry_id = conn.execute("SELECT id FROM zettel_entries").fetchone()["id"]
    store.record_failure(conn, entry_id, error="nope", max_attempts=1)

    signals, entry_ids = bridge.load_unswept_signals()
    assert signals == [] and entry_ids == []


def test_screen_blocks_are_excluded(bridge, conn):
    _settled(conn, "s1", kind="screen_block",
             occurred_at="2026-07-20T00:00:00+00:00",
             narrative_at="2026-07-25T10:00:00+00:00")
    signals, entry_ids = bridge.load_unswept_signals()
    assert signals == [] and entry_ids == []


def test_textless_rows_are_still_stampable_so_the_scan_cannot_stall(bridge, conn):
    """A row we decline must still be reported for stamping.

    Otherwise a page of declined rows leaves the scan in the same place and is
    re-read on every sweep forever.
    """
    entry_id = _settled(conn, "empty", occurred_at="2026-07-20T00:00:00+00:00",
                        narrative_at="2026-07-25T10:00:00+00:00")
    conn.execute(
        "UPDATE zettel_entries SET narrative = NULL, summary = NULL, title = '' "
        "WHERE id = ?", (entry_id,)
    )

    signals, entry_ids = bridge.load_unswept_signals()
    assert signals == []
    assert entry_ids == [entry_id]


def test_summary_falls_back_when_no_narrative_exists(bridge, conn):
    entry_id = _settled(conn, "legacy", occurred_at="2026-07-20T00:00:00+00:00",
                        narrative_at="2026-07-25T10:00:00+00:00")
    conn.execute(
        "UPDATE zettel_entries SET narrative = NULL, summary = 'older summary' "
        "WHERE id = ?", (entry_id,)
    )
    signals, _ = bridge.load_unswept_signals()
    assert signals[0].summary == "older summary"


def test_mark_swept_is_idempotent(bridge, conn):
    _settled(conn, "a", occurred_at="2026-07-20T00:00:00+00:00",
             narrative_at="2026-07-25T10:00:00+00:00")
    _, entry_ids = bridge.load_unswept_signals()
    assert bridge.mark_swept(entry_ids) == 1
    assert bridge.mark_swept(entry_ids) == 0


def test_mark_swept_with_no_ids_is_a_noop(bridge):
    assert bridge.mark_swept([]) == 0


def test_limit_is_respected_and_the_rest_survives(bridge, conn):
    for index in range(3):
        _settled(conn, f"e{index}", occurred_at="2026-07-20T00:00:00+00:00",
                 narrative_at=f"2026-07-25T10:00:0{index}+00:00")

    signals, entry_ids = bridge.load_unswept_signals(limit=2)
    assert len(signals) == 2
    bridge.mark_swept(entry_ids)

    remaining, _ = bridge.load_unswept_signals()
    assert len(remaining) == 1
