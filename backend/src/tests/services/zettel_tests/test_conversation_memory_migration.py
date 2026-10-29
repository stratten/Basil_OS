"""Legacy conversation-thread projection migration coverage."""

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.zettel_migrations import (
    migrate_conversation_memory_projection,
)
from api.services.zettel import store
from api.services.zettel.sources.base import ZettelDraft


def _legacy_entry(conn, source_id):
    store.insert_card(
        conn,
        ZettelDraft(
            source_kind="conversation",
            source_id=source_id,
            event_type="conversation",
            occurred_at="2026-08-10T10:00:00+00:00",
            title="Legacy conversation",
        ),
    )


def test_migration_finalizes_open_legacy_threads_and_preserves_narrative(conn):
    _legacy_entry(conn, "legacy-open")
    conn.execute(
        """
        UPDATE zettel_entries
        SET narrative = 'Existing legacy narrative.', narrative_state = 'pending',
            is_open = 1, open_note = 'old note', memory_swept_at = '2026-08-10T11:00:00+00:00'
        WHERE source_kind = 'conversation'
        """
    )

    migrate_conversation_memory_projection(conn)

    row = conn.execute(
        """
        SELECT narrative, narrative_state, is_open, open_note, memory_swept_at
        FROM zettel_entries WHERE source_id = 'legacy-open'
        """
    ).fetchone()
    assert tuple(row) == ("Existing legacy narrative.", "final", 0, None, None)


def test_migration_keeps_final_legacy_entries_unchanged_and_is_idempotent(conn):
    _legacy_entry(conn, "legacy-final")
    conn.execute(
        """
        UPDATE zettel_entries
        SET narrative = 'Final narrative.', narrative_state = 'final',
            is_open = 0, open_note = NULL, memory_swept_at = '2026-08-10T11:00:00+00:00'
        WHERE source_kind = 'conversation'
        """
    )

    migrate_conversation_memory_projection(conn)
    migrate_conversation_memory_projection(conn)

    row = conn.execute(
        """
        SELECT narrative, narrative_state, is_open, open_note, memory_swept_at
        FROM zettel_entries WHERE source_id = 'legacy-final'
        """
    ).fetchone()
    assert tuple(row) == (
        "Final narrative.",
        "final",
        0,
        None,
        "2026-08-10T11:00:00+00:00",
    )
