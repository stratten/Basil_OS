"""Tests for finalized Zettel retrieval projection and FTS exact search."""

import sqlite3

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.core_migrations import (
    migrate_retrieval_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_zettel_backreference,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.fts.tables import (
    ensure_fts_tables,
    ensure_zettel_raw_search_fts,
    ensure_zettel_search_fts,
)
from api.services.retrieval.sources.zettel_source import ZettelBackedRetrievalSource
from api.services.retrieval.zettel_projection import (
    build_zettel_fts_content,
    finalized_zettel_document,
)
from api.services.zettel import store
from api.services.zettel.sources.base import ZettelDraft


def _draft(**overrides):
    base = dict(
        source_kind="transcription",
        source_id="t1",
        event_type="transcription",
        occurred_at="2026-07-24T10:00:00+00:00",
        title="Review contract",
        summary="Can you review the contract?",
    )
    base.update(overrides)
    return ZettelDraft(**base)


def _insert_final(conn, *, source_id="t1", title="Review contract", narrative="You asked to review the contract."):
    store.insert_card(conn, _draft(source_id=source_id, title=title))
    store.write_narrative(
        conn,
        f"transcription:{source_id}",
        narrative=narrative,
        model="m",
        is_open=False,
        open_note=None,
    )


def test_projection_excludes_payload_and_includes_bounded_fields(conn):
    store.insert_card(
        conn,
        _draft(
            payload={"secret_context": "raw transcript body"},
            summary="Card summary",
            outcome="requested",
        ),
    )
    store.write_narrative(
        conn,
        "transcription:t1",
        narrative="You asked to review the contract.",
        model="m",
        is_open=False,
        open_note=None,
    )
    row = conn.execute("SELECT * FROM zettel_entries").fetchone()
    document = finalized_zettel_document(row)

    assert "secret_context" not in document.search_text
    assert "Review contract" in document.search_text
    assert "Card summary" in document.search_text
    assert "You asked to review the contract." in document.search_text
    assert document.metadata["outcome"] == "requested"


def test_exact_search_returns_all_card_states(conn):
    _insert_final(conn, source_id="final-one", title="Contract review", narrative="Contract review request.")
    store.insert_card(conn, _draft(source_id="pending-one", title="Contract pending review"))
    store.insert_card(conn, _draft(source_id="open-one", title="Open item", summary="Open follow-up item"))
    store.write_narrative(
        conn,
        "transcription:open-one",
        narrative="Still open.",
        model="m",
        is_open=True,
        open_note="waiting",
    )
    conn.commit()

    source = ZettelBackedRetrievalSource("transcription")
    hits = list(source.search_exact(conn, "contract", None, None, 10))

    assert {hit.document_id for hit in hits} == {
        "transcription:final-one",
        "transcription:pending-one",
    }
    assert all(hit.score_kind == "exact_fts:zettel" for hit in hits)


def test_exact_search_respects_source_kind_and_date_filters(conn):
    _insert_final(
        conn,
        source_id="in-range",
        title="Budget planning",
        narrative="You planned the budget.",
    )
    store.insert_card(
        conn,
        _draft(
            source_kind="assistant_output",
            source_id="other-kind",
            title="Budget planning",
            summary="Assistant budget note",
        ),
    )
    store.write_narrative(
        conn,
        "assistant_output:other-kind",
        narrative="Assistant budget note.",
        model="m",
        is_open=False,
        open_note=None,
    )
    conn.commit()

    source = ZettelBackedRetrievalSource("transcription")
    hits = list(
        source.search_exact(
            conn,
            "budget",
            "2026-07-24T00:00:00+00:00",
            "2026-07-24T23:59:59+00:00",
            10,
        )
    )

    assert [hit.document_id for hit in hits] == ["transcription:in-range"]


def test_write_narrative_keeps_open_cards_in_fts(conn):
    store.insert_card(conn, _draft(source_id="t1"))
    store.write_narrative(
        conn,
        "transcription:t1",
        narrative="You asked about invoices.",
        model="m",
        is_open=False,
        open_note=None,
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM zettel_search_fts").fetchone()[0] == 1

    store.write_narrative(
        conn,
        "transcription:t1",
        narrative="Still waiting on invoices.",
        model="m",
        is_open=True,
        open_note="pending",
    )
    conn.commit()
    content = conn.execute(
        "SELECT content FROM zettel_search_fts WHERE entry_id = 'transcription:t1'"
    ).fetchone()["content"]
    assert "Still waiting on invoices." in content


def test_ensure_zettel_search_fts_rebuilds_stale_table(conn):
    _insert_final(conn, source_id="one", title="Alpha", narrative="Alpha narrative.")
    _insert_final(conn, source_id="two", title="Beta", narrative="Beta narrative.")
    store.insert_card(conn, _draft(source_id="pending", title="Pending card"))
    conn.execute("DELETE FROM zettel_search_fts")
    conn.commit()

    ensure_zettel_search_fts(conn)
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM zettel_search_fts").fetchone()[0] == 3
    row = conn.execute("SELECT * FROM zettel_entries WHERE source_id = 'one'").fetchone()
    fts_row = conn.execute(
        "SELECT content FROM zettel_search_fts WHERE entry_id = ?",
        (row["id"],),
    ).fetchone()
    assert fts_row is not None
    assert "Alpha" in fts_row["content"]
    assert "Alpha narrative." in fts_row["content"]


def test_uncarded_row_moves_atomically_from_raw_fts_to_card_fts(conn):
    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'raw-1', '2026-07-29T12:00:00+00:00', 'unique raw phrase', 'm', 'completed', NULL, '/tmp/raw-1.wav'
        )
        """
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_raw_search_fts WHERE document_id = 'transcription:raw-1'"
    ).fetchone()[0] == 1
    draft = _draft(source_id="raw-1", title="Unique raw phrase", summary="unique raw phrase")
    assert store.insert_card(conn, draft) is True
    store.stamp_source(
        conn, table="transcriptions", id_column="id", source_ids=["raw-1"], zettel_id="transcription:raw-1"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_raw_search_fts WHERE document_id = 'transcription:raw-1'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_search_fts WHERE entry_id = 'transcription:raw-1'"
    ).fetchone()[0] == 1


def test_committed_transition_is_visible_from_a_new_connection(tmp_path):
    db_path = tmp_path / "retrieval-transition.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for statement in get_schema_statements():
        conn.execute(statement)
    migrate_zettel_backreference(conn)
    migrate_retrieval_tables(conn)
    ensure_fts_tables(conn)
    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'committed-1', '2026-07-29T12:30:00+00:00', 'committed transition phrase',
            'm', 'completed', NULL, '/tmp/committed-1.wav'
        )
        """
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_raw_search_fts WHERE document_id = 'transcription:committed-1'"
    ).fetchone()[0] == 1
    assert store.insert_card(
        conn,
        _draft(
            source_id="committed-1",
            title="Committed transition phrase",
            summary="committed transition phrase",
        ),
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_search_fts WHERE entry_id = 'transcription:committed-1'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_raw_search_fts WHERE document_id = 'transcription:committed-1'"
    ).fetchone()[0] == 1
    store.stamp_source(
        conn,
        table="transcriptions",
        id_column="id",
        source_ids=["committed-1"],
        zettel_id="transcription:committed-1",
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_raw_search_fts WHERE document_id = 'transcription:committed-1'"
    ).fetchone()[0] == 0
    conn.commit()
    conn.close()

    with sqlite3.connect(db_path) as committed_conn:
        assert committed_conn.execute(
            "SELECT COUNT(*) FROM zettel_raw_search_fts WHERE document_id = 'transcription:committed-1'"
        ).fetchone()[0] == 0
        assert committed_conn.execute(
            "SELECT COUNT(*) FROM zettel_search_fts WHERE entry_id = 'transcription:committed-1'"
        ).fetchone()[0] == 1


def test_card_fts_stays_visible_while_open_and_after_finalization(conn):
    store.insert_card(conn, _draft(source_id="state-1", summary="initial phrase"))
    store.write_narrative(
        conn, "transcription:state-1", narrative="open narrative phrase", model="m", is_open=True, open_note="running"
    )
    open_content = conn.execute(
        "SELECT content FROM zettel_search_fts WHERE entry_id = 'transcription:state-1'"
    ).fetchone()["content"]
    assert "open narrative phrase" in open_content
    store.write_narrative(
        conn, "transcription:state-1", narrative="final narrative phrase", model="m", is_open=False, open_note=None
    )
    rows = conn.execute(
        "SELECT content FROM zettel_search_fts WHERE entry_id = 'transcription:state-1'"
    ).fetchall()
    assert len(rows) == 1
    assert "final narrative phrase" in rows[0]["content"]


def test_fts_never_indexes_payload_json(conn):
    store.insert_card(
        conn,
        _draft(source_id="secret-1", summary="safe summary", payload={"secret": "NEVER_SEARCHABLE_SECRET"}),
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_search_fts WHERE zettel_search_fts MATCH 'NEVER_SEARCHABLE_SECRET'"
    ).fetchone()[0] == 0


def test_raw_fts_startup_rebuild_matches_noop_update_trigger_for_all_source_policies(conn):
    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'parity-transcription', '2026-07-29T13:00:00+00:00', 'parity transcription phrase',
            'm', 'completed', NULL, '/tmp/parity-transcription.wav'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO assistant_outputs (
            id, output_text, user_request, generated_at, status, zettel_id
        ) VALUES (
            101, 'parity assistant output', 'parity assistant request',
            '2026-07-29T13:01:00+00:00', 'completed', NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO scheduled_agent_tasks (
            id, title, agent_task_text, schedule_type, schedule_config
        ) VALUES ('parity-schedule', 'Parity schedule', 'Parity task', 'one_time', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO scheduled_agent_task_runs (
            id, scheduled_agent_task_id, scheduled_for, status, error_message, zettel_id
        ) VALUES (
            'parity-scheduled-run', 'parity-schedule', '2026-07-29T13:02:00+00:00',
            'failed', 'parity scheduled error', NULL
        )
        """
    )
    conn.commit()
    ensure_zettel_raw_search_fts(conn)
    conn.commit()
    policies = (
        ("transcriptions", "id", "parity-transcription", "transcription:parity-transcription"),
        ("assistant_outputs", "id", "101", "assistant_output:101"),
        (
            "scheduled_agent_task_runs",
            "id",
            "parity-scheduled-run",
            "scheduled_run:parity-scheduled-run",
        ),
    )
    for table, id_column, source_id, document_id in policies:
        rebuild_row = conn.execute(
            "SELECT * FROM zettel_raw_search_fts WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        conn.execute(
            f"UPDATE {table} SET {id_column} = {id_column} WHERE {id_column} = ?",
            (source_id,),
        )
        trigger_row = conn.execute(
            "SELECT * FROM zettel_raw_search_fts WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        assert dict(rebuild_row) == dict(trigger_row)


def test_ensure_fts_tables_recovers_after_partial_sidecar_delete(conn):
    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'recover-1', '2026-07-29T14:00:00+00:00', 'recovery phrase', 'm', 'completed', NULL, '/tmp/recover-1.wav'
        )
        """
    )
    _insert_final(conn, source_id="recover-card", title="Recovery card", narrative="Recovery narrative.")
    conn.execute("DELETE FROM zettel_raw_search_fts")
    conn.execute("DELETE FROM zettel_search_fts")
    ensure_fts_tables(conn)
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_raw_search_fts WHERE document_id = 'transcription:recover-1'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM zettel_search_fts WHERE entry_id = 'transcription:recover-card'"
    ).fetchone()[0] == 1
