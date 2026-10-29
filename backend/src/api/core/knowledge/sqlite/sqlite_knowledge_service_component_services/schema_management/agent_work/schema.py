"""Schema statements for the durable, source-safe agent work ledger."""

from __future__ import annotations

from typing import List


def get_agent_work_schema_statements() -> List[str]:
    """Return agent-work tables and indexes for new SQLite databases."""
    return [
        """
        CREATE TABLE IF NOT EXISTS agent_work_sessions (
            id TEXT PRIMARY KEY,
            agent_task_id TEXT,
            root_task_id TEXT,
            goal TEXT NOT NULL,
            collection_type TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}',
            strategy_json TEXT NOT NULL DEFAULT '{}',
            cursor_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            summary_so_far TEXT,
            item_budget INTEGER,
            token_budget INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_work_items (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            external_id TEXT,
            entity_type TEXT,
            source_system TEXT,
            source_scope_json TEXT,
            identity_quality TEXT NOT NULL DEFAULT 'legacy_unscoped',
            batch_index INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'discovered',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            decision_json TEXT NOT NULL DEFAULT '{}',
            detail_summary TEXT,
            action_result_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES agent_work_sessions(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_work_receipts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            item_id TEXT,
            agent_task_id TEXT,
            service TEXT NOT NULL,
            method TEXT NOT NULL,
            receipt_key TEXT,
            requested_effect_json TEXT NOT NULL DEFAULT '{}',
            observed_postcondition_json TEXT NOT NULL DEFAULT '{}',
            material_write INTEGER NOT NULL DEFAULT 0,
            execution_state TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            discrepancy_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES agent_work_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES agent_work_items(id) ON DELETE SET NULL,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_work_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            item_id TEXT,
            agent_task_id TEXT,
            event_kind TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES agent_work_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES agent_work_items(id) ON DELETE SET NULL,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_work_entity_relations (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            source_item_id TEXT NOT NULL,
            target_item_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            agent_task_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES agent_work_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (source_item_id) REFERENCES agent_work_items(id) ON DELETE CASCADE,
            FOREIGN KEY (target_item_id) REFERENCES agent_work_items(id) ON DELETE CASCADE,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE SET NULL,
            CHECK (relationship_type IN ('parent', 'derived_from', 'same_as'))
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_work_sessions_task
        ON agent_work_sessions(agent_task_id, updated_at DESC)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_work_sessions_unique_root
        ON agent_work_sessions(root_task_id)
        WHERE root_task_id IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_work_items_session_status
        ON agent_work_items(session_id, status, batch_index, created_at)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_work_items_identity
        ON agent_work_items(
            session_id, entity_type, source_system, source_scope_json, external_id
        )
        WHERE entity_type IS NOT NULL
          AND source_system IS NOT NULL
          AND source_scope_json IS NOT NULL
          AND external_id IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_work_receipts_session_item
        ON agent_work_receipts(session_id, item_id, created_at DESC, id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_work_receipts_task
        ON agent_work_receipts(agent_task_id, service, method, created_at DESC, id DESC)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_work_receipts_key
        ON agent_work_receipts(session_id, receipt_key)
        WHERE receipt_key IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_work_events_session_item
        ON agent_work_events(session_id, item_id, created_at, id)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_work_entity_relations_unique
        ON agent_work_entity_relations(
            session_id, source_item_id, target_item_id, relationship_type
        )
        """,
    ]
