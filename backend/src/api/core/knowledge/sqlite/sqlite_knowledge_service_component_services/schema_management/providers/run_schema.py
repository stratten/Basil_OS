"""Schema statements for attended generic ACP provider persistence."""

from __future__ import annotations


def get_provider_run_schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS provider_profiles (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            transport TEXT NOT NULL CHECK (transport = 'acp_stdio'),
            launch_argv_json TEXT NOT NULL,
            environment_allowlist_json TEXT NOT NULL DEFAULT '[]',
            authentication_method_id TEXT,
            status TEXT NOT NULL DEFAULT 'enabled'
                CHECK (status IN ('enabled', 'disabled', 'removed')),
            capability_state TEXT NOT NULL DEFAULT 'unverified'
                CHECK (capability_state = 'unverified'),
            description TEXT,
            routing_hints_json TEXT NOT NULL DEFAULT '[]',
            revision INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            removed_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS provider_workspace_grants (
            id TEXT PRIMARY KEY,
            provider_profile_id TEXT NOT NULL,
            canonical_workspace_root TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'revoked')),
            workspace_label TEXT NOT NULL DEFAULT '',
            description TEXT,
            routing_hints_json TEXT NOT NULL DEFAULT '[]',
            revision INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            revoked_at TIMESTAMP,
            UNIQUE (provider_profile_id, canonical_workspace_root),
            FOREIGN KEY (provider_profile_id) REFERENCES provider_profiles(id)
                ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS provider_runs (
            id TEXT PRIMARY KEY,
            agent_task_id TEXT NOT NULL UNIQUE,
            root_task_id TEXT NOT NULL,
            provider_profile_id TEXT NOT NULL,
            workspace_grant_id TEXT NOT NULL,
            provider_session_id TEXT,
            capability_snapshot_json TEXT,
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN (
                    'created', 'running', 'waiting_user_input', 'waiting_permission',
                    'canceling', 'interrupted', 'recoverable', 'completed', 'failed', 'canceled'
                )),
            runtime_version TEXT,
            launch_fingerprint TEXT,
            last_provider_event_id TEXT,
            generation INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 0,
            terminal_reason TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            started_at TIMESTAMP,
            terminal_at TIMESTAMP,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (provider_profile_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
            FOREIGN KEY (workspace_grant_id) REFERENCES provider_workspace_grants(id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_profiles_status
        ON provider_profiles(status, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_workspace_grants_profile_status
        ON provider_workspace_grants(provider_profile_id, status, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_runs_root_status
        ON provider_runs(root_task_id, status, updated_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_runs_profile_status
        ON provider_runs(provider_profile_id, status, updated_at DESC)
        """,
    ]
