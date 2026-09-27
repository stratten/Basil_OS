"""Schema statements for durable provider-target discovery proposals."""

from __future__ import annotations


def get_provider_discovery_schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS provider_discovery_proposals (
            id TEXT PRIMARY KEY,
            agent_task_id TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('proposed', 'ambiguous', 'unavailable', 'conflicts_with_user_target')),
            grounding_tier TEXT NOT NULL
                CHECK (grounding_tier IN ('exact_user_target', 'explicit_reference_or_chain_context', 'inferred_native_context', 'insufficient')),
            confidence TEXT NOT NULL
                CHECK (confidence IN ('high', 'medium', 'low')),
            provider_candidates_json TEXT NOT NULL,
            service_candidates_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            exact_user_constraints_json TEXT NOT NULL,
            rationale TEXT NOT NULL,
            resolution_note TEXT,
            proposal_fingerprint TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_discovery_task_fingerprint
        ON provider_discovery_proposals(agent_task_id, proposal_fingerprint)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_discovery_task_created
        ON provider_discovery_proposals(agent_task_id, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS provider_target_authorizations (
            id TEXT PRIMARY KEY,
            parent_authorization_id TEXT,
            proposal_id TEXT NOT NULL,
            agent_task_id TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('authorized', 'needs_user', 'rejected', 'clarification_received', 'cancelled')),
            reason_code TEXT NOT NULL,
            selected_provider_profile_id TEXT,
            selected_workspace_grant_id TEXT,
            selected_connection_id TEXT,
            selected_tool_name TEXT,
            selected_service_policy TEXT,
            resolved_workspace_path TEXT,
            reference_paths_json TEXT NOT NULL,
            choice_snapshot_json TEXT NOT NULL,
            response_fingerprint TEXT,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (parent_authorization_id) REFERENCES provider_target_authorizations(id) ON DELETE CASCADE,
            FOREIGN KEY (proposal_id) REFERENCES provider_discovery_proposals(id) ON DELETE CASCADE,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_target_authorization_initial
        ON provider_target_authorizations(proposal_id)
        WHERE parent_authorization_id IS NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_target_authorization_response
        ON provider_target_authorizations(parent_authorization_id)
        WHERE parent_authorization_id IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_target_authorization_task_created
        ON provider_target_authorizations(agent_task_id, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS provider_target_delegations (
            id TEXT PRIMARY KEY,
            authorization_id TEXT NOT NULL UNIQUE,
            parent_agent_task_id TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            child_agent_task_id TEXT NOT NULL UNIQUE,
            delegated_agent_run_id TEXT UNIQUE,
            provider_profile_id TEXT NOT NULL,
            workspace_grant_id TEXT NOT NULL,
            selected_connection_id TEXT,
            selected_tool_name TEXT,
            selected_service_policy TEXT,
            legacy_lifecycle_snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (authorization_id) REFERENCES provider_target_authorizations(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_target_delegation_parent_created
        ON provider_target_delegations(parent_agent_task_id, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_target_delegation_child
        ON provider_target_delegations(child_agent_task_id)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_target_delegation_delegated_agent_run
        ON provider_target_delegations(delegated_agent_run_id)
        WHERE delegated_agent_run_id IS NOT NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS provider_runtime_evidence (
            id TEXT PRIMARY KEY,
            provider_profile_id TEXT NOT NULL,
            executable_fingerprint TEXT NOT NULL,
            runtime_version TEXT NOT NULL,
            acp_major INTEGER NOT NULL,
            evidence_kind TEXT NOT NULL CHECK (evidence_kind = 'same_session_follow_up'),
            status TEXT NOT NULL CHECK (status IN ('passed', 'failed')),
            evidence_fingerprint TEXT NOT NULL UNIQUE,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            observed_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP NOT NULL,
            FOREIGN KEY (provider_profile_id) REFERENCES provider_profiles(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_provider_runtime_evidence_lookup
        ON provider_runtime_evidence(
            provider_profile_id, executable_fingerprint, runtime_version, acp_major, evidence_kind, status
        )
        """,
    ]
