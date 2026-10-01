"""Provider run lifecycle persistence."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import Any

from ..infrastructure.connection import get_sync_connection, run_write_transaction
from .errors import (
    ProviderRunConflictError,
    ProviderRunPersistenceError,
    ProviderRunTransitionError,
)
from .records import (
    _require_active_grant_for_profile,
    _require_enabled_profile,
    _row_to_run,
)
from .validation import _json_dump_object, _require_nonblank

ALLOWED_RUN_TRANSITIONS = {
    "created": {"failed", "canceled"},
    "running": {
        "waiting_user_input",
        "waiting_permission",
        "canceling",
        "interrupted",
        "recoverable",
        "completed",
        "failed",
        "canceled",
    },
    "waiting_user_input": {
        "running",
        "canceling",
        "interrupted",
        "recoverable",
        "failed",
        "canceled",
    },
    "waiting_permission": {
        "running",
        "canceling",
        "interrupted",
        "recoverable",
        "failed",
        "canceled",
    },
    "canceling": {"interrupted", "failed", "canceled"},
    "interrupted": {"recoverable", "failed", "canceled"},
    "recoverable": {"running", "failed", "canceled"},
}

TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}

# Package 4C.1: provider-run statuses reachable during ordinary operation that a
# backend restart can leave stranded. "interrupted" and "recoverable" are
# deliberately excluded because only Package 4C.1's own reconciliation (or a
# future Package 4C.2 resume decision) produces them; a run already sitting in
# one of those two statuses has already been settled and must not be revisited.
ACTIVE_RECONCILIATION_STATUSES = {
    "created",
    "running",
    "waiting_user_input",
    "waiting_permission",
    "canceling",
}


def utcnow() -> str:
    return datetime.utcnow().isoformat()


class ProviderRunRepository:
    """Creation, reconciliation, and transition persistence for provider runs."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def get_latest_run_for_profile(
        self, provider_profile_id: str
    ) -> dict[str, object] | None:
        """Package 5C.1: the most recently updated provider run for a profile, if any.

        Used only to read whether the profile has an observed capability snapshot; it
        never creates, transitions, or finalizes a run.
        """
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM provider_runs
                WHERE provider_profile_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    async def create_run(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        provider_profile_id: str,
        workspace_grant_id: str,
    ) -> dict[str, object]:
        task_id = _require_nonblank(agent_task_id, "agent_task_id")
        root_id = _require_nonblank(root_task_id, "root_task_id")
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        grant_id = _require_nonblank(workspace_grant_id, "workspace_grant_id")
        run_id = str(uuid.uuid4())
        timestamp = utcnow()
        def _create(conn: sqlite3.Connection) -> sqlite3.Row:
            _require_enabled_profile(conn, profile_id)
            _require_active_grant_for_profile(
                conn,
                provider_profile_id=profile_id,
                workspace_grant_id=grant_id,
            )
            agent_task = conn.execute(
                "SELECT root_task_id FROM agent_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if agent_task is None:
                raise ProviderRunConflictError(f"agent task {task_id!r} does not exist")
            if agent_task["root_task_id"] != root_id:
                raise ProviderRunConflictError(
                    f"root task {root_id!r} does not match the Agent Task root "
                    f"{agent_task['root_task_id']!r}"
                )
            if not conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ?",
                (root_id,),
            ).fetchone():
                raise ProviderRunConflictError(f"root task {root_id!r} does not exist")
            if conn.execute(
                "SELECT 1 FROM provider_runs WHERE agent_task_id = ?",
                (task_id,),
            ).fetchone():
                raise ProviderRunConflictError(
                    f"provider run already exists for agent task {task_id!r}"
                )
            conn.execute(
                """
                INSERT INTO provider_runs (
                    id, agent_task_id, root_task_id, provider_profile_id,
                    workspace_grant_id, provider_session_id, capability_snapshot_json,
                    status, runtime_version, launch_fingerprint, last_provider_event_id,
                    generation, revision, terminal_reason, created_at, updated_at,
                    started_at, terminal_at
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 'created', NULL, NULL, NULL, 0, 0, NULL, ?, ?, NULL, NULL)
                """,
                (run_id, task_id, root_id, profile_id, grant_id, timestamp, timestamp),
            )
            row = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ProviderRunPersistenceError("failed to load created provider run")
            return row

        try:
            row = run_write_transaction(self.db_path, "create_provider_run", _create)
        except sqlite3.IntegrityError as exc:
            raise ProviderRunConflictError(
                f"provider run could not be created for agent task {task_id!r}"
            ) from exc
        if row is None:
            raise ProviderRunPersistenceError("failed to load created provider run")
        return _row_to_run(row)

    async def get_run(self, provider_run_id: str) -> dict[str, object] | None:
        run_id = _require_nonblank(provider_run_id, "provider_run_id")
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    async def list_runs_for_root(self, root_task_id: str) -> list[dict[str, object]]:
        root_id = _require_nonblank(root_task_id, "root_task_id")
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM provider_runs
                WHERE root_task_id = ?
                ORDER BY updated_at DESC
                """,
                (root_id,),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    async def list_active_runs(self) -> list[dict[str, object]]:
        """Return every provider run left in a pre-4C.2 active status.

        Used only by Package 4C.1's backend-startup reconciliation. A run already
        `completed`, `failed`, `canceled`, `interrupted`, or `recoverable` is
        excluded, so calling this after reconciliation has already run returns an
        empty list and callers naturally get idempotent behavior.
        """
        placeholders = ",".join("?" * len(ACTIVE_RECONCILIATION_STATUSES))
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM provider_runs
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC
                """,
                tuple(ACTIVE_RECONCILIATION_STATUSES),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    async def finalize_interrupted_run(
        self,
        *,
        provider_run_id: str,
        expected_revision: int,
        next_status: str,
        terminal_reason: str,
    ) -> dict[str, object]:
        """Atomically supersede pending interactions and finalize one interrupted run."""
        run_id = _require_nonblank(provider_run_id, "provider_run_id")
        if type(expected_revision) is not int:
            raise ProviderRunPersistenceError("expected_revision must be an integer")
        if next_status not in {"failed", "interrupted"}:
            raise ProviderRunPersistenceError(
                "interrupted-run finalization must transition to failed or interrupted"
            )
        cleaned_reason = _require_nonblank(terminal_reason, "terminal_reason")
        timestamp = utcnow()
        def _finalize(conn: sqlite3.Connection) -> sqlite3.Row:
            row = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ProviderRunConflictError(f"provider run {run_id!r} does not exist")
            current_status = row["status"]
            if row["revision"] != expected_revision:
                raise ProviderRunConflictError(
                    f"provider run {run_id!r} revision mismatch: expected "
                    f"{expected_revision}, got {row['revision']}"
                )
            if current_status in TERMINAL_RUN_STATUSES:
                raise ProviderRunTransitionError(
                    f"provider run {run_id!r} is terminal in status {current_status!r}"
                )
            if next_status not in ALLOWED_RUN_TRANSITIONS.get(current_status, set()):
                raise ProviderRunTransitionError(
                    f"illegal provider run transition from {current_status!r} "
                    f"to {next_status!r}"
                )
            conn.execute(
                """
                UPDATE provider_interactions
                SET status = 'superseded', outcome = 'cancel',
                    updated_at = ?, resolved_at = ?, revision = revision + 1
                WHERE provider_run_id = ? AND status = 'pending'
                """,
                (timestamp, timestamp, run_id),
            )
            terminal_at = timestamp if next_status in TERMINAL_RUN_STATUSES else None
            updated = conn.execute(
                """
                UPDATE provider_runs
                SET status = ?,
                    terminal_reason = ?,
                    updated_at = ?,
                    terminal_at = COALESCE(?, terminal_at),
                    revision = revision + 1
                WHERE id = ? AND status = ? AND revision = ?
                """,
                (
                    next_status,
                    cleaned_reason,
                    timestamp,
                    terminal_at,
                    run_id,
                    current_status,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                raise ProviderRunConflictError(
                    f"provider run {run_id!r} could not be finalized"
                )
            refreshed = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if refreshed is None:
                raise ProviderRunPersistenceError("failed to load finalized provider run")
            return refreshed

        refreshed = run_write_transaction(
            self.db_path,
            "finalize_interrupted_provider_run",
            _finalize,
        )
        if refreshed is None:
            raise ProviderRunPersistenceError("failed to load finalized provider run")
        return _row_to_run(refreshed)

    async def mark_run_initialized(
        self,
        *,
        provider_run_id: str,
        expected_revision: int,
        capabilities: dict[str, object],
        runtime_version: str,
        provider_session_id: str | None = None,
        launch_fingerprint: str | None = None,
    ) -> dict[str, object]:
        run_id = _require_nonblank(provider_run_id, "provider_run_id")
        if type(expected_revision) is not int:
            raise ProviderRunPersistenceError("expected_revision must be an integer")
        if not isinstance(capabilities, dict):
            raise ProviderRunPersistenceError("capabilities must be a JSON object")
        cleaned_runtime_version = _require_nonblank(runtime_version, "runtime_version")
        session_id = None
        if provider_session_id is not None:
            session_id = _require_nonblank(provider_session_id, "provider_session_id")
        fingerprint = None
        if launch_fingerprint is not None:
            fingerprint = _require_nonblank(launch_fingerprint, "launch_fingerprint")
        timestamp = utcnow()
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ProviderRunConflictError(f"provider run {run_id!r} does not exist")
            if row["status"] != "created":
                raise ProviderRunConflictError(
                    f"provider run {run_id!r} is not in created status"
                )
            if row["revision"] != expected_revision:
                raise ProviderRunConflictError(
                    f"provider run {run_id!r} revision mismatch: expected {expected_revision}, got {row['revision']}"
                )
            updated = conn.execute(
                """
                UPDATE provider_runs
                SET status = 'running',
                    capability_snapshot_json = ?,
                    runtime_version = ?,
                    provider_session_id = ?,
                    launch_fingerprint = ?,
                    started_at = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE id = ? AND status = 'created' AND revision = ?
                """,
                (
                    _json_dump_object(capabilities),
                    cleaned_runtime_version,
                    session_id,
                    fingerprint,
                    timestamp,
                    timestamp,
                    run_id,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                raise ProviderRunConflictError(
                    f"provider run {run_id!r} could not be initialized"
                )
            conn.commit()
            refreshed = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if refreshed is None:
            raise ProviderRunPersistenceError("failed to load initialized provider run")
        return _row_to_run(refreshed)

    async def transition_run(
        self,
        *,
        provider_run_id: str,
        expected_revision: int,
        next_status: str,
        terminal_reason: str | None = None,
        last_provider_event_id: str | None = None,
    ) -> dict[str, object]:
        run_id = _require_nonblank(provider_run_id, "provider_run_id")
        if type(expected_revision) is not int:
            raise ProviderRunPersistenceError("expected_revision must be an integer")
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ProviderRunConflictError(f"provider run {run_id!r} does not exist")
            current_status = row["status"]
            if row["revision"] != expected_revision:
                raise ProviderRunConflictError(
                    f"provider run {run_id!r} revision mismatch: expected {expected_revision}, got {row['revision']}"
                )
            if current_status in TERMINAL_RUN_STATUSES:
                raise ProviderRunTransitionError(
                    f"provider run {run_id!r} is terminal in status {current_status!r}"
                )
            allowed = ALLOWED_RUN_TRANSITIONS.get(current_status, set())
            if next_status not in allowed:
                raise ProviderRunTransitionError(
                    f"illegal provider run transition from {current_status!r} to {next_status!r}"
                )
            cleaned_reason = None
            if next_status in {"failed", "interrupted"}:
                cleaned_reason = _require_nonblank(
                    terminal_reason or "",
                    "terminal_reason",
                )
            elif terminal_reason is not None and terminal_reason.strip():
                cleaned_reason = terminal_reason.strip()
            event_id = last_provider_event_id
            if event_id is not None:
                event_id = _require_nonblank(event_id, "last_provider_event_id")
            timestamp = utcnow()
            terminal_at = timestamp if next_status in TERMINAL_RUN_STATUSES else None
            updated = conn.execute(
                """
                UPDATE provider_runs
                SET status = ?,
                    terminal_reason = ?,
                    last_provider_event_id = COALESCE(?, last_provider_event_id),
                    updated_at = ?,
                    terminal_at = COALESCE(?, terminal_at),
                    revision = revision + 1
                WHERE id = ? AND status = ? AND revision = ?
                """,
                (
                    next_status,
                    cleaned_reason,
                    event_id,
                    timestamp,
                    terminal_at,
                    run_id,
                    current_status,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                current = conn.execute(
                    "SELECT revision FROM provider_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if current is None or current["revision"] != expected_revision:
                    raise ProviderRunConflictError(
                        f"provider run {run_id!r} revision mismatch: expected {expected_revision}"
                    )
                raise ProviderRunTransitionError(
                    f"provider run {run_id!r} could not transition from {current_status!r} to {next_status!r}"
                )
            conn.commit()
            refreshed = conn.execute(
                "SELECT * FROM provider_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if refreshed is None:
            raise ProviderRunPersistenceError("failed to load transitioned provider run")
        return _row_to_run(refreshed)
