"""Schema statements for durable provider interactions (Packages 4A-4B.2).

`provider_interactions` rows are the single source of truth for either a live `elicitation/create` exchange (`interaction_kind = 'provider_user_input'`) or a durable `session/request_permission` decision record (`interaction_kind = 'provider_permission'`, Package 4B.2). For a `provider_permission` row: `message` holds the permission `title`; `requested_schema_json` holds `{"description": ..., "subject": ...}`; `fields_json` holds the normalized `PermissionOption` list; and `submitted_values_json` holds `{"selected_option_id": ...}` once resolved. `mode` is fixed at `'form'` for `provider_permission` rows as a non-semantic placeholder, since the `CHECK` constraint below only allows `'form'`/`'url'` and neither is meaningful for a permission decision.
"""

from __future__ import annotations


def get_provider_interaction_schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS provider_interactions (
            id TEXT PRIMARY KEY,
            provider_run_id TEXT NOT NULL,
            agent_task_id TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            interaction_kind TEXT NOT NULL DEFAULT 'provider_user_input'
                CHECK (interaction_kind IN ('provider_user_input', 'provider_permission')),
            mode TEXT NOT NULL DEFAULT 'form'
                CHECK (mode IN ('form', 'url')),
            message TEXT NOT NULL,
            requested_schema_json TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'answered', 'declined', 'canceled', 'superseded')),
            outcome TEXT
                CHECK (outcome IN ('accept', 'decline', 'cancel')),
            submitted_values_json TEXT,
            revision INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            resolved_at TIMESTAMP,
            FOREIGN KEY (provider_run_id) REFERENCES provider_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_interactions_run_status
        ON provider_interactions(provider_run_id, status, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_interactions_agent_task_status
        ON provider_interactions(agent_task_id, status, updated_at DESC)
        """,
    ]
