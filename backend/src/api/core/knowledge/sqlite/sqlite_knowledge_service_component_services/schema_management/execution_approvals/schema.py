"""Schema statements for durable generic execution approvals."""

from __future__ import annotations


def get_execution_approval_schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS execution_approvals (
            id TEXT PRIMARY KEY,
            agent_task_id TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            execution_type TEXT NOT NULL DEFAULT 'shell'
                CHECK (execution_type IN ('shell', 'applescript', 'browser_foreground_control')),
            command TEXT NOT NULL,
            script_content TEXT,
            reason TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            generalized_pattern TEXT NOT NULL,
            render_context_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'denied', 'canceled')),
            remember_choice INTEGER NOT NULL DEFAULT 0,
            pattern_type TEXT,
            revision INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            resolved_at TIMESTAMP,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (root_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_execution_approvals_task_status
        ON execution_approvals(agent_task_id, status, updated_at DESC)
        """,
    ]
