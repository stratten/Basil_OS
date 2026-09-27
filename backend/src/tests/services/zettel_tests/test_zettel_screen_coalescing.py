"""Sixty captures of one document must become one block, not sixty rows."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from api.services.capture.shared.work_context import derive_work_context
from .conftest import NonClosingConnection
from api.services.zettel.materializer import ZettelMaterializer
from api.services.zettel.narrative.prompt import build_prompt
from api.services.zettel.sources.screen_source import (
    MAX_CONTEXT_CAPTURES,
    ScreenActivitySource,
)


def _store_work_context(conn, activity_id, app_name, window_title):
    context = derive_work_context(app_name, window_title, capture_id=activity_id)
    for key, value in context.as_metadata().items():
        conn.execute(
            """
            INSERT OR REPLACE INTO activity_metadata (activity_id, key, value, confidence)
            VALUES (?, ?, ?, 1.0)
            """,
            (activity_id, key, value),
        )


def _capture(conn, index, moment, app="Chrome", context="ctx-a", window_title="Spec document"):
    activity_id = f"a{index}"
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, window_title, extracted_text, "
        "created_at, context_hash) VALUES (?, ?, ?, ?, 'body', ?, ?)",
        (activity_id, moment.isoformat(), app, window_title, moment.isoformat(), context),
    )
    _store_work_context(conn, activity_id, app, window_title)


def _capture_with_dwell(conn, index, moment, dwell, app="Chrome", context="ctx-a", window_title="Spec document"):
    activity_id = f"a{index}"
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, window_title, extracted_text, "
        "created_at, context_hash, duration) VALUES (?, ?, ?, ?, 'body', ?, ?, ?)",
        (activity_id, moment.isoformat(), app, window_title, moment.isoformat(), context, dwell),
    )
    _store_work_context(conn, activity_id, app, window_title)


def _card_all(conn):
    materializer = ZettelMaterializer(sources=[ScreenActivitySource()])
    materializer._connection = lambda: NonClosingConnection(conn)
    return materializer


def test_sixty_similar_captures_collapse_to_one_block(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    for index in range(60):
        _capture(conn, index, base + timedelta(minutes=index))
    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)
    assert len(drafts) == 1
    assert drafts[0].payload["capture_count"] == 60
    assert drafts[0].source_id == "a0"
    assert drafts[0].payload["duration_seconds"] == pytest.approx(59 * 60)
    assert len(drafts[0].member_source_ids) == 60


def test_captures_coalesce_even_though_every_screen_differs(conn):
    """The real-world case: context_hash never repeats, yet this is one session.

    context_hash digests the full OCR'd screen text, so consecutive captures of
    the same work always hash differently. Every other test here hands each
    capture an identical context, which is why keying the run on that hash could
    ship while reducing every block to a single capture.
    """
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    for index in range(30):
        _capture(conn, index, base + timedelta(minutes=index), context=f"hash-{index}")

    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)

    assert len(drafts) == 1
    assert drafts[0].payload["capture_count"] == 30


def test_a_null_context_hash_does_not_split_a_run(conn):
    """Older captures predate context_hash; absence must not fragment them."""
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    for index in range(4):
        activity_id = f"a{index}"
        conn.execute(
            "INSERT INTO activities (id, timestamp, app_name, window_title, "
            "extracted_text, created_at) VALUES (?, ?, 'Chrome', 'Doc', 'body', ?)",
            (
                activity_id,
                (base + timedelta(minutes=index)).isoformat(),
                (base + timedelta(minutes=index)).isoformat(),
            ),
        )
        _store_work_context(conn, activity_id, "Chrome", "Doc")

    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)

    assert len(drafts) == 1
    assert drafts[0].payload["capture_count"] == 4


def test_single_capture_block_reports_its_recorded_dwell_not_zero(conn):
    _capture_with_dwell(conn, 0, datetime.now(timezone.utc) - timedelta(hours=3), 330.0)
    draft = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)[0]
    assert draft.payload["duration_seconds"] == pytest.approx(330.0)


def test_block_duration_sums_recorded_dwell(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    for index in range(3):
        _capture_with_dwell(conn, index, base + timedelta(minutes=5 * index), 300.0)
    draft = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)[0]
    assert draft.payload["capture_count"] == 3
    assert draft.payload["duration_seconds"] == pytest.approx(900.0)


def test_missing_dwell_falls_back_to_the_span(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    _capture(conn, 0, base)
    _capture(conn, 1, base + timedelta(minutes=4))
    draft = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)[0]
    assert draft.payload["duration_seconds"] == pytest.approx(240.0)


def test_app_change_starts_a_new_block(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    _capture(conn, 0, base)
    _capture(conn, 1, base + timedelta(minutes=1), app="Slack", context="ctx-b")
    assert len(ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)) == 2


def test_long_gap_starts_a_new_block(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    _capture(conn, 0, base)
    _capture(conn, 1, base + timedelta(minutes=45))
    assert len(ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)) == 2


def test_open_trailing_block_is_not_carded_until_it_closes(conn):
    """A still-growing block is held back so a session stays one block."""
    _capture(conn, 0, datetime.now(timezone.utc) - timedelta(seconds=30))
    assert ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500) == []


def test_closed_block_before_an_open_one_is_still_carded(conn):
    _capture(conn, 0, datetime.now(timezone.utc) - timedelta(days=1), app="Slack", context="ctx-b")
    _capture(conn, 1, datetime.now(timezone.utc) - timedelta(seconds=30))
    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)
    assert [d.source_id for d in drafts] == ["a0"]


def test_carding_stamps_every_member_and_does_not_fragment(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    for index in range(6):
        _capture(conn, index, base + timedelta(seconds=30 * index))

    materializer = _card_all(conn)
    for _ in range(4):
        materializer.run_pass()

    rows = conn.execute(
        "SELECT source_id, json_extract(payload_json, '$.capture_count') AS captures "
        "FROM zettel_entries WHERE source_kind = 'screen_block'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["source_id"] == "a0"
    assert rows[0]["captures"] == 6

    stamped = conn.execute(
        "SELECT COUNT(*) AS n FROM activities WHERE zettel_id = 'screen_block:a0'"
    ).fetchone()["n"]
    assert stamped == 6


def test_gather_context_reads_ai_analysis_from_members(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    for index in range(2):
        activity_id = f"a{index}"
        conn.execute(
            "INSERT INTO activities (id, timestamp, app_name, window_title, extracted_text, "
            "created_at, context_hash, ai_analysis) VALUES (?, ?, 'Chrome', 'Doc', 'body', ?, "
            "'ctx-a', ?)",
            (
                activity_id,
                (base + timedelta(seconds=30 * index)).isoformat(),
                (base + timedelta(seconds=30 * index)).isoformat(),
                '{"content_summary": "read the spec", "activity_type": "reading"}',
            ),
        )
        _store_work_context(conn, activity_id, "Chrome", "Doc")
    _card_all(conn).run_pass()
    context = ScreenActivitySource().gather_context(conn, ["a0"])
    assert context["a0"]["capture_count"] == 2
    assert context["a0"]["captures"][0]["content_summary"] == "read the spec"
    assert context["a0"]["work_context"] == {
        "key": "window_title:chrome:doc",
        "label": "Doc",
        "kind": "window_title",
        "confidence": "fallback",
        "evidence": "app_name=Chrome|window_title=Doc",
    }


def _verbose_capture(
    conn,
    index,
    moment,
    *,
    window_title="main.py — Speakeasy_AutoAdmin (Workspace)",
):
    """A capture whose analysis is long enough to fight for the context budget."""
    activity_id = f"a{index}"
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, window_title, "
        "extracted_text, created_at, ai_analysis) "
        "VALUES (?, ?, 'Cursor', ?, ?, ?, ?)",
        (
            activity_id,
            moment.isoformat(),
            window_title,
            "T" * 4000,
            moment.isoformat(),
            json.dumps(
                {
                    "content_summary": "S" * 600,
                    "context": "C" * 600,
                    "activity_type": "coding",
                }
            ),
        ),
    )
    _store_work_context(conn, activity_id, "Cursor", window_title)


def test_a_long_block_is_sampled_across_its_whole_span(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    for index in range(60):
        _verbose_capture(conn, index, base + timedelta(seconds=30 * index))
    _card_all(conn).run_pass()

    block = ScreenActivitySource().gather_context(conn, ["a0"])["a0"]

    # The true total is still reported; only the described sample is capped.
    assert block["capture_count"] == 60
    assert block["captures_shown"] == MAX_CONTEXT_CAPTURES
    assert len(block["captures"]) == MAX_CONTEXT_CAPTURES
    # Raw OCR is dropped once sampling kicks in, so breadth wins over depth.
    assert "extracted_text" not in block["captures"][0]


def test_large_block_context_stays_within_the_prompt_budget(conn):
    """Sampling is what keeps the rendered prompt from being truncated.

    MAX_CONTEXT_CAPTURES and the per-field limits live in screen_source while
    CONTEXT_MAX_CHARS lives in the prompt, so nothing but this test stops the
    two from drifting apart until narratives silently lose their tail again.
    """
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    for index in range(60):
        _verbose_capture(conn, index, base + timedelta(seconds=30 * index))
    _card_all(conn).run_pass()

    block = ScreenActivitySource().gather_context(conn, ["a0"])["a0"]
    prompt = build_prompt(
        {
            "source_kind": "screen_block",
            "title": "Cursor",
            "occurred_at": base.isoformat(),
            "summary": "S" * 400,
            "payload": {"capture_count": 60},
        },
        block,
    )

    assert "[truncated]" not in prompt


def test_a_short_block_keeps_every_capture_and_its_text(conn):
    """The cap must not disturb blocks that already fit."""
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    for index in range(3):
        _verbose_capture(conn, index, base + timedelta(seconds=30 * index))
    _card_all(conn).run_pass()

    block = ScreenActivitySource().gather_context(conn, ["a0"])["a0"]

    assert block["captures_shown"] == 3
    assert "extracted_text" in block["captures"][0]


def test_distinct_cursor_workspaces_produce_separate_blocks(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    _capture(
        conn,
        0,
        base,
        app="Cursor",
        window_title="main.py — Basil_Plus_Auth_Service (Workspace)",
    )
    _capture(
        conn,
        1,
        base + timedelta(minutes=1),
        app="Cursor",
        window_title="admin.py — Speakeasy_AutoAdmin (Workspace)",
    )
    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)
    assert len(drafts) == 2
    labels = {draft.payload["work_context_label"] for draft in drafts}
    assert labels == {"Basil_Plus_Auth_Service", "Speakeasy_AutoAdmin"}


def test_same_workspace_different_files_still_coalesce(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    _capture(
        conn,
        0,
        base,
        app="Cursor",
        window_title="foo.py — Basil_Plus_Auth_Service (Workspace)",
    )
    _capture(
        conn,
        1,
        base + timedelta(minutes=2),
        app="Cursor",
        window_title="bar.py — Basil_Plus_Auth_Service (Workspace)",
    )
    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)
    assert len(drafts) == 1
    assert drafts[0].payload["capture_count"] == 2
    assert drafts[0].payload["work_context_label"] == "Basil_Plus_Auth_Service"


def test_interleaved_apps_split_a_workspace_run(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    _capture(
        conn,
        0,
        base,
        app="Cursor",
        window_title="main.py — Basil_Plus_Auth_Service (Workspace)",
    )
    _capture(
        conn,
        1,
        base + timedelta(minutes=1),
        app="Microsoft Outlook",
        window_title="Re: Contract review",
    )
    _capture(
        conn,
        2,
        base + timedelta(minutes=2),
        app="Cursor",
        window_title="routes.py — Basil_Plus_Auth_Service (Workspace)",
    )
    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)
    assert len(drafts) == 3
    assert [draft.payload["work_context_label"] for draft in drafts] == [
        "Basil_Plus_Auth_Service",
        "Re: Contract review",
        "Basil_Plus_Auth_Service",
    ]


def test_no_window_captures_never_merge(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    for index in range(2):
        activity_id = f"nw{index}"
        conn.execute(
            "INSERT INTO activities (id, timestamp, app_name, window_title, extracted_text, created_at) "
            "VALUES (?, ?, 'Cursor', 'No Window', 'body', ?)",
            (activity_id, (base + timedelta(minutes=index)).isoformat(), base.isoformat()),
        )
        _store_work_context(conn, activity_id, "Cursor", "No Window")
    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)
    assert len(drafts) == 2


def test_different_context_hashes_still_merge_under_one_work_context(conn):
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    _capture(
        conn,
        0,
        base,
        app="Cursor",
        context="hash-one",
        window_title="main.py — Basil_Plus_Auth_Service (Workspace)",
    )
    _capture(
        conn,
        1,
        base + timedelta(minutes=1),
        app="Cursor",
        context="hash-two",
        window_title="routes.py — Basil_Plus_Auth_Service (Workspace)",
    )
    drafts = ScreenActivitySource().find_uncarded(conn, since_iso=None, limit=500)
    assert len(drafts) == 1
    assert drafts[0].payload["capture_count"] == 2
