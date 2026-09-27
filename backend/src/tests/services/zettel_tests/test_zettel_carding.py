"""End-to-end carding: un-carded rows become pending cards and get stamped."""

import json

import pytest

from .conftest import NonClosingConnection
from api.services.zettel.materializer import ZettelMaterializer

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


def test_uncarded_task_becomes_a_pending_card(conn):
    _insert_task(conn, "t1")
    result = _materializer(conn).run_pass(since_iso=None)
    assert result.carded == 1
    row = conn.execute(
        "SELECT source_kind, narrative_state FROM zettel_entries WHERE source_id='t1'"
    ).fetchone()
    assert row["source_kind"] == "agent_task"
    assert row["narrative_state"] == "pending"
    # The source row is stamped so it is not re-carded.
    assert conn.execute("SELECT zettel_id FROM agent_tasks WHERE id='t1'").fetchone()[0] == (
        "agent_task:t1"
    )


def test_second_pass_cards_nothing_new(conn):
    _insert_task(conn, "t1")
    materializer = _materializer(conn)
    materializer.run_pass(since_iso=None)
    second = materializer.run_pass(since_iso=None)
    assert second.carded == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM zettel_entries").fetchone()["n"] == 1


def test_rows_before_the_history_floor_are_ignored(conn):
    _insert_task(conn, "old", timestamp="2020-01-01 10:00:00")
    _insert_task(conn, "new", timestamp="2026-07-24 10:00:00")
    result = _materializer(conn).run_pass(since_iso="2026-07-01T00:00:00+00:00")
    assert result.carded == 1
    ids = [r["source_id"] for r in conn.execute("SELECT source_id FROM zettel_entries")]
    assert ids == ["new"]


def test_carding_drains_backlog_beyond_one_chunk(conn):
    for i in range(5):
        _insert_task(conn, f"t{i}")
    # A chunk of 2 still drains all five rows in a single pass.
    result = _materializer(conn).run_pass(limit_per_source=2, since_iso=None)
    assert result.carded == 5
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE source_kind='agent_task'"
    ).fetchone()["n"] == 5
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM agent_tasks WHERE zettel_id IS NULL"
    ).fetchone()["n"] == 0


def _insert_capture(conn, capture_id, timestamp, *, app="Safari", context="ctx"):
    conn.execute(
        "INSERT INTO activities (id, timestamp, created_at, app_name, window_title, "
        "extracted_text, ai_analysis, duration, context_hash) VALUES (?, ?, ?, ?, 'W', "
        "'text', '{}', 1.0, ?)",
        (capture_id, timestamp, timestamp, app, context),
    )


def test_block_straddling_a_batch_boundary_is_one_card(conn):
    # Three consecutive same-context captures form one block. Even with a chunk
    # size of 1 the screen source fetches a full-block window, so the block is
    # never split at a batch boundary. Old timestamps keep it closed.
    _insert_capture(conn, 1, "2020-01-01 10:00:00")
    _insert_capture(conn, 2, "2020-01-01 10:00:05")
    _insert_capture(conn, 3, "2020-01-01 10:00:10")

    result = _materializer(conn).run_pass(limit_per_source=1, since_iso=None)
    assert result.carded == 1
    row = conn.execute(
        "SELECT source_id, payload_json FROM zettel_entries WHERE source_kind='screen_block'"
    ).fetchone()
    assert row is not None
    zettel_id = f"screen_block:{row['source_id']}"
    stamped = conn.execute(
        "SELECT COUNT(*) AS n FROM activities WHERE zettel_id = ?", (zettel_id,)
    ).fetchone()["n"]
    assert stamped == 3
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM activities WHERE zettel_id IS NULL"
    ).fetchone()["n"] == 0


def test_multiple_sources_carded_in_one_pass(conn):
    _insert_task(conn, "t1")
    conn.execute(
        "INSERT INTO transcriptions (id, timestamp, status, transcription_text, model_name, "
        "audio_file_path, created_at) VALUES ('x1', '2026-07-24 09:00:00', 'completed', "
        "'hello world', 'whisper', '/tmp/x1.wav', '2026-07-24 09:00:00')"
    )
    result = _materializer(conn).run_pass(since_iso=None)
    assert result.carded == 2
    kinds = {
        r["source_kind"] for r in conn.execute("SELECT source_kind FROM zettel_entries")
    }
    assert kinds == {"agent_task", "transcription"}


def _insert_conversation_pair(
    conn,
    *,
    conversation_id,
    user_id,
    assistant_id,
    lifecycle,
    timestamp="2026-08-10 10:00:00",
):
    conn.execute("INSERT INTO conversations (id, title) VALUES (?, 'Conversation')", (conversation_id,))
    conn.execute(
        """
        INSERT INTO conversation_messages (id, conversation_id, role, content, timestamp)
        VALUES (?, ?, 'user', 'Please handle this.', ?)
        """,
        (user_id, conversation_id, timestamp),
    )
    metadata = {
        "conversation_turn": {
            "route": "direct",
            "lifecycle": lifecycle,
            "agent_task_id": None,
            "terminal_outcome": f"Turn {lifecycle}.",
            "user_message_id": user_id,
            "narration": {"lifecycle": "pending", "attempt_count": 0},
        }
    }
    conn.execute(
        """
        INSERT INTO conversation_messages
            (id, conversation_id, role, content, metadata, timestamp)
        VALUES (?, ?, 'assistant', 'The response.', ?, ?)
        """,
        (assistant_id, conversation_id, json.dumps(metadata), timestamp),
    )


def test_terminal_conversation_pairs_card_once_per_assistant_placeholder(conn):
    for lifecycle in ("completed", "failed", "cancelled"):
        _insert_conversation_pair(
            conn,
            conversation_id=f"conversation-{lifecycle}",
            user_id=f"user-{lifecycle}",
            assistant_id=f"assistant-{lifecycle}",
            lifecycle=lifecycle,
        )

    materializer = _materializer(conn)
    assert materializer.run_pass(since_iso=None).carded == 3
    rows = conn.execute(
        """
        SELECT source_id, source_status
        FROM zettel_entries
        WHERE source_kind = 'conversation_turn'
        ORDER BY source_id
        """
    ).fetchall()
    assert [(row["source_id"], row["source_status"]) for row in rows] == [
        ("assistant-cancelled", "cancelled"),
        ("assistant-completed", "completed"),
        ("assistant-failed", "failed"),
    ]
    assert materializer.run_pass(since_iso=None).carded == 0


def test_active_conversation_pair_is_not_carded(conn):
    _insert_conversation_pair(
        conn,
        conversation_id="conversation-active",
        user_id="user-active",
        assistant_id="assistant-active",
        lifecycle="running",
        timestamp="2100-01-01 10:00:00",
    )

    assert _materializer(conn).run_pass(since_iso=None).carded == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE source_kind = 'conversation_turn'"
    ).fetchone()["n"] == 0
