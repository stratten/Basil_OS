"""Schema statements for the per-chain agent checklist that hangs off an agent work session."""

from __future__ import annotations

from typing import List


def get_agent_checklist_schema_statements() -> List[str]:
    """Return checklist tables and indexes. Every statement is idempotent, so new and upgraded databases converge."""
    return [
        """
        CREATE TABLE IF NOT EXISTS agent_checklists (
            session_id TEXT PRIMARY KEY,
            closed_at TIMESTAMP,
            notes_content TEXT NOT NULL DEFAULT '',
            notes_revision INTEGER NOT NULL DEFAULT 0,
            notes_updated_by TEXT,
            notes_updated_at TIMESTAMP,
            notes_carried_from_task_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES agent_work_sessions(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_checklist_items (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'agent',
            title TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            done_basis TEXT NOT NULL DEFAULT '',
            required INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            waiting_on TEXT NOT NULL DEFAULT '',
            recheck_at TIMESTAMP,
            sort_order INTEGER NOT NULL DEFAULT 0,
            work_item_id TEXT,
            carried_from_item_id TEXT,
            archived_at TIMESTAMP,
            revision INTEGER NOT NULL DEFAULT 1,
            created_by_task_id TEXT,
            updated_by_task_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES agent_work_sessions(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_checklist_refs (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'related',
            ref_kind TEXT NOT NULL,
            source_system TEXT NOT NULL DEFAULT '',
            source_scope TEXT NOT NULL DEFAULT '',
            external_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            open_url TEXT NOT NULL DEFAULT '',
            added_by TEXT NOT NULL DEFAULT 'agent',
            last_known_status TEXT NOT NULL DEFAULT '',
            last_known_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES agent_checklist_items(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_checklist_events (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            agent_task_id TEXT,
            kind TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'agent',
            text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES agent_checklist_items(id) ON DELETE CASCADE,
            FOREIGN KEY (session_id) REFERENCES agent_work_sessions(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_checklist_items_session
        ON agent_checklist_items(session_id, archived_at, sort_order, created_at)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_checklist_refs_unique
        ON agent_checklist_refs(item_id, ref_kind, source_system, source_scope, external_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_checklist_refs_lookup
        ON agent_checklist_refs(ref_kind, external_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_checklist_events_item
        ON agent_checklist_events(item_id, created_at, id)
        """,
    ]
