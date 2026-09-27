"""Adversarial audit scenarios for the zettel carding pipeline."""

from datetime import datetime, timezone

import pytest

from .conftest import NonClosingConnection
from api.services.zettel import store
from api.services.zettel.materializer import ZettelMaterializer
from api.services.zettel.normalization import bounded_payload, to_utc_iso
from api.services.zettel.sources.configs import AGENT_TASK_CONFIG
from api.services.zettel.sources.table_source import TableZettelSource

pytestmark = pytest.mark.use_temp_home


def _all_sources(conn):
    materializer = ZettelMaterializer()
    materializer._connection = lambda: NonClosingConnection(conn)
    return materializer


def test_empty_database_cards_without_error(conn):
    result = _all_sources(conn).run_pass()
    assert result.carded == 0
    assert result.errors == []


def test_activities_only_database_cards_screen_blocks(conn):
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, created_at, context_hash) "
        "VALUES ('a1', '2026-01-01 10:00:00', 'Chrome', '2026-01-01 10:00:00', 'ctx')"
    )
    result = _all_sources(conn).run_pass(since_iso=None)
    assert result.carded >= 1
    row = conn.execute(
        "SELECT source_kind FROM zettel_entries WHERE source_kind = 'screen_block'"
    ).fetchone()
    assert row is not None


def test_mixed_timezone_timestamps_order_correctly(conn):
    conn.execute(
        "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, "
        "status, created_at, updated_at) VALUES "
        "('t1', '2026-07-24 10:00:00', 'p', 'p', 'completed', '2026-07-24 10:00:00', '2026-07-24 10:00:00'), "
        "('t2', '2026-07-24T14:00:00+00:00', 'p', 'p', 'completed', '2026-07-24T14:00:00+00:00', '2026-07-24T14:00:00+00:00')"
    )
    drafts = TableZettelSource(AGENT_TASK_CONFIG).find_uncarded(conn, since_iso=None, limit=10)
    assert [d.source_id for d in drafts] == ["t1", "t2"]


def test_disabled_source_is_not_carded(conn):
    conn.execute(
        "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, "
        "status, created_at, updated_at) VALUES ('t1', '2026-07-24 10:00:00', 'p', 'p', "
        "'completed', '2026-07-24 10:00:00', '2026-07-24 10:00:00')"
    )
    result = _all_sources(conn).run_pass(since_iso=None, enabled_kinds={"transcription"})
    assert result.carded == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM zettel_entries").fetchone()["n"] == 0


def test_non_json_serializable_payload_is_coerced(conn):
    encoded = bounded_payload({"when": datetime(2026, 7, 24, tzinfo=timezone.utc)})
    assert "2026" in encoded
    assert len(encoded) <= 4000


def test_naive_and_aware_timestamps_normalize_to_same_basis(conn):
    assert to_utc_iso("2026-07-24 14:30:00") == to_utc_iso("2026-07-24T14:30:00+00:00")


def test_concurrent_passes_do_not_duplicate_rows(conn):
    conn.execute(
        "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, "
        "status, created_at, updated_at) VALUES ('t1', '2026-07-24 10:00:00', 'p', 'p', "
        "'completed', '2026-07-24 10:00:00', '2026-07-24 10:00:00')"
    )
    materializer = _all_sources(conn)
    materializer.run_pass(since_iso=None)
    materializer.run_pass(since_iso=None)
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE source_kind='agent_task'"
    ).fetchone()["n"] == 1


def test_stamp_only_touches_null_backreferences(conn):
    """A row already pointing at a zettel is never re-stamped to another."""
    store.stamp_source(
        conn, table="agent_tasks", id_column="id", source_ids=["x"], zettel_id="agent_task:x"
    )
    conn.execute(
        "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, "
        "status, created_at, updated_at, zettel_id) VALUES ('x', '2026-07-24 10:00:00', 'p', "
        "'p', 'completed', '2026-07-24 10:00:00', '2026-07-24 10:00:00', 'preexisting')"
    )
    store.stamp_source(
        conn, table="agent_tasks", id_column="id", source_ids=["x"], zettel_id="agent_task:x"
    )
    assert conn.execute("SELECT zettel_id FROM agent_tasks WHERE id='x'").fetchone()[0] == (
        "preexisting"
    )
