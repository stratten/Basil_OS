"""Schema statements for executor-neutral delegated AgentTask work."""

from __future__ import annotations


def get_delegated_agent_schema_statements() -> list[str]:
    """Return tables that durably supervise one parent-owned child worker."""

    return [
        """
        CREATE TABLE IF NOT EXISTS delegated_agent_runs (
            id TEXT PRIMARY KEY,
            parent_agent_task_id TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            child_agent_task_id TEXT NOT NULL UNIQUE,
            executor_kind TEXT NOT NULL
                CHECK (executor_kind IN ('acp_provider', 'internal_agent')),
            admitted_scope_json TEXT NOT NULL DEFAULT '{}',
            evidence_policy_json TEXT NOT NULL DEFAULT '{}',
            dependency_run_ids_json TEXT NOT NULL DEFAULT '[]',
            parent_continuation_required INTEGER NOT NULL DEFAULT 1
                CHECK (parent_continuation_required IN (0, 1)),
            status TEXT NOT NULL
                CHECK (status IN (
                    'admitted', 'running', 'idle', 'waiting_user_input',
                    'waiting_permission', 'supervision_due', 'cancelling',
                    'interrupted', 'settled', 'failed', 'cancelled'
                )),
            revision INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            settled_at TIMESTAMP,
            FOREIGN KEY (parent_agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delegated_agent_turns (
            id TEXT PRIMARY KEY,
            delegated_agent_run_id TEXT NOT NULL,
            turn_sequence INTEGER NOT NULL,
            controller_instruction TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('created', 'running', 'idle', 'failed', 'cancelled')),
            terminal_response_json TEXT,
            created_at TIMESTAMP NOT NULL,
            started_at TIMESTAMP,
            settled_at TIMESTAMP,
            UNIQUE (delegated_agent_run_id, turn_sequence),
            FOREIGN KEY (delegated_agent_run_id) REFERENCES delegated_agent_runs(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delegated_agent_outcomes (
            delegated_agent_run_id TEXT PRIMARY KEY,
            transport_state TEXT NOT NULL,
            executor_result_state TEXT NOT NULL,
            evidence_state TEXT NOT NULL
                CHECK (evidence_state IN (
                    'provider_reported', 'verified', 'verification_mismatch', 'unavailable'
                )),
            summary TEXT NOT NULL,
            receipt_references_json TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP NOT NULL,
            FOREIGN KEY (delegated_agent_run_id) REFERENCES delegated_agent_runs(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delegated_agent_events (
            id TEXT PRIMARY KEY,
            delegated_agent_run_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            event_kind TEXT NOT NULL,
            event_data_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP NOT NULL,
            UNIQUE (delegated_agent_run_id, revision),
            FOREIGN KEY (delegated_agent_run_id) REFERENCES delegated_agent_runs(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delegated_agent_child_reservations (
            child_agent_task_id TEXT PRIMARY KEY,
            parent_agent_task_id TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            executor_kind TEXT NOT NULL
                CHECK (executor_kind IN ('acp_provider', 'internal_agent')),
            dependency_run_ids_json TEXT NOT NULL DEFAULT '[]',
            strategic_assessment_json TEXT NOT NULL DEFAULT '{"child_cannot_delegate":true,"expected_benefit":"legacy reservation","independence_rationale":"legacy reservation","parallelism_reason":"legacy reservation","parent_work_can_continue":false}',
            status TEXT NOT NULL
                CHECK (status IN ('reserved', 'dispatched', 'dispatch_failed', 'cancelled')),
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (child_agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_delegated_agent_runs_parent_status
        ON delegated_agent_runs(parent_agent_task_id, status, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_delegated_agent_runs_root_status
        ON delegated_agent_runs(root_task_id, status, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_delegated_agent_events_run_created
        ON delegated_agent_events(delegated_agent_run_id, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_delegated_agent_reservations_parent_status
        ON delegated_agent_child_reservations(parent_agent_task_id, status, created_at, child_agent_task_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS delegated_agent_evidence (
            id TEXT PRIMARY KEY,
            delegated_agent_run_id TEXT NOT NULL,
            delegated_agent_turn_id TEXT,
            sequence INTEGER NOT NULL,
            source_event_key TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN (
                'provider_activity', 'provider_terminal_response', 'parent_verification',
                'transport_failure', 'interaction_state'
            )),
            kind TEXT NOT NULL,
            provenance TEXT NOT NULL CHECK (provenance IN (
                'provider_reported', 'basil_observed', 'unavailable'
            )),
            verification_state TEXT NOT NULL CHECK (verification_state IN (
                'pending', 'verified', 'verification_mismatch', 'unavailable', 'not_applicable'
            )),
            summary TEXT NOT NULL,
            structured_data_json TEXT NOT NULL DEFAULT '{}',
            artifact_locator TEXT,
            created_at TIMESTAMP NOT NULL,
            UNIQUE (delegated_agent_run_id, sequence),
            UNIQUE (delegated_agent_run_id, source_event_key),
            FOREIGN KEY (delegated_agent_run_id) REFERENCES delegated_agent_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (delegated_agent_turn_id) REFERENCES delegated_agent_turns(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_delegated_agent_evidence_run_sequence
        ON delegated_agent_evidence(delegated_agent_run_id, sequence)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_delegated_agent_evidence_turn_sequence
        ON delegated_agent_evidence(delegated_agent_turn_id, sequence)
        """,
    ]
