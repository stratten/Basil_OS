"""Schema statements for the zettel unified event stream.

Split out of schema.py following the precedent of agent_work_schema.py.
The stream is a projection of existing tables: every entry back-references an owning record via (source_kind, source_id). Table-backed sources carry a zettel_id back-reference, while composite sources use the unique entry key to find un-carded records.
"""

from typing import List


def get_zettel_schema_statements() -> List[str]:
    """Return DDL for zettel_entries and its indexes."""
    return [
        """
        CREATE TABLE IF NOT EXISTS zettel_entries (
            id TEXT PRIMARY KEY,

            -- Back-reference to the owning record. Deterministic and unique so
            -- carding is an idempotent INSERT OR IGNORE, never a duplicate.
            source_kind TEXT NOT NULL,
            source_id TEXT NOT NULL,

            event_type TEXT NOT NULL,
            occurred_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP,
            title TEXT NOT NULL,
            summary TEXT,
            outcome TEXT,
            source_status TEXT,

            payload_json TEXT NOT NULL DEFAULT '{}',

            -- Narrative synthesis, filled by the model finalizing pass.
            -- pending: needs a swing. final: closed. failed: gave up.
            narrative TEXT,
            narrative_state TEXT NOT NULL DEFAULT 'pending',
            narrative_model TEXT,
            narrative_at TIMESTAMP,
            narrative_error TEXT,
            narrative_attempts INTEGER NOT NULL DEFAULT 0,

            -- Retained for legacy rows. A valid narrative is always finalized, so successful synthesis stores is_open=0 and no open_note.
            is_open INTEGER,
            open_note TEXT,

            content_digest TEXT NOT NULL DEFAULT '',
            materialized_at TIMESTAMP NOT NULL,

            -- Stamped once the memory evaluator has consumed this entry. Same
            -- contract as zettel_id on source rows and narrative_state above:
            -- downstream progress is a per-row stamp found by an indexed
            -- IS NULL scan, so consumption cannot depend on the order the
            -- narrative pass happens to settle entries in.
            memory_swept_at TIMESTAMP,

            UNIQUE (source_kind, source_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_zettel_entries_occurred
        ON zettel_entries(occurred_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_zettel_entries_kind
        ON zettel_entries(source_kind, occurred_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_zettel_entries_type
        ON zettel_entries(event_type, occurred_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_zettel_entries_state
        ON zettel_entries(narrative_state, occurred_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_zettel_entries_sweep
        ON zettel_entries(narrative_state, memory_swept_at, narrative_at)
        """,
    ]
