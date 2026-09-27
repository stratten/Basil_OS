"""Durable executor-neutral parent/child delegated-agent lifecycle records."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..infrastructure.connection import get_sync_connection, run_write_transaction
from .delegated_agent_reservation_repository import (
    DelegatedAgentReservationConflictError,
    DelegatedAgentReservationRepository,
)


_ACTIVE_STATUSES = {
    "admitted",
    "running",
    "idle",
    "waiting_user_input",
    "waiting_permission",
    "supervision_due",
    "cancelling",
    "interrupted",
}
_TERMINAL_STATUSES = {"settled", "failed", "cancelled"}
_MAX_ACTIVE_CHILDREN = 3
_MAX_TEXT_BYTES = 8_000


class DelegatedAgentConflictError(RuntimeError):
    """Raised when one parent cannot admit or transition a delegated child."""


class DelegatedAgentPersistenceError(RuntimeError):
    """Raised when delegated-agent durable data is malformed."""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _require_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelegatedAgentPersistenceError(f"{field_name} must be a nonblank string")
    return value.strip()


def _bounded_text(value: object, field_name: str) -> str:
    text = _require_id(value, field_name)
    if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise DelegatedAgentPersistenceError(f"{field_name} exceeds {_MAX_TEXT_BYTES} bytes")
    return text


def _json_object(value: Mapping[str, Any] | None, field_name: str) -> str:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise DelegatedAgentPersistenceError(f"{field_name} must be an object")
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise DelegatedAgentPersistenceError(f"{field_name} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise DelegatedAgentPersistenceError(f"{field_name} exceeds {_MAX_TEXT_BYTES} bytes")
    return encoded


def _scope_conflicts(existing_scope: Mapping[str, Any], candidate_scope: Mapping[str, Any]) -> bool:
    if bool(existing_scope.get("read_only")) or bool(candidate_scope.get("read_only")):
        return False
    existing_paths = {str(path) for path in existing_scope.get("mutable_paths", [])}
    candidate_paths = {str(path) for path in candidate_scope.get("mutable_paths", [])}
    return bool(existing_paths.intersection(candidate_paths))


def _decode_object(value: object, field_name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DelegatedAgentPersistenceError(f"{field_name} is malformed") from exc
    if not isinstance(decoded, dict):
        raise DelegatedAgentPersistenceError(f"{field_name} must decode to an object")
    return decoded


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    dependency_ids = json.loads(row["dependency_run_ids_json"])
    if not isinstance(dependency_ids, list) or not all(isinstance(item, str) for item in dependency_ids):
        raise DelegatedAgentPersistenceError("dependency_run_ids_json must decode to a string array")
    return {
        "id": row["id"],
        "parent_agent_task_id": row["parent_agent_task_id"],
        "root_task_id": row["root_task_id"],
        "child_agent_task_id": row["child_agent_task_id"],
        "executor_kind": row["executor_kind"],
        "admitted_scope": _decode_object(row["admitted_scope_json"], "admitted_scope_json"),
        "evidence_policy": _decode_object(row["evidence_policy_json"], "evidence_policy_json"),
        "dependency_run_ids": dependency_ids,
        "parent_continuation_required": bool(row["parent_continuation_required"]),
        "status": row["status"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "settled_at": row["settled_at"],
    }


class DelegatedAgentRepository:
    """Atomic admissions, turns, and terminal evidence for all child executors."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._reservations = DelegatedAgentReservationRepository(db_path)

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        *,
        delegated_agent_run_id: str,
        revision: int,
        event_kind: str,
        event_data: Mapping[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO delegated_agent_events (
                id, delegated_agent_run_id, revision, event_kind, event_data_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                delegated_agent_run_id,
                revision,
                _bounded_text(event_kind, "event_kind"),
                _json_object(event_data, "event_data"),
                _now(),
            ),
        )

    async def reserve_child_agent_task(
        self,
        *,
        parent_agent_task_id: str,
        root_task_id: str,
        child_agent_task_id: str,
        executor_kind: str,
        dependency_run_ids: list[str] | None = None,
        strategic_assessment: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._reservations.reserve_child_agent_task(
                parent_agent_task_id=parent_agent_task_id,
                root_task_id=root_task_id,
                child_agent_task_id=child_agent_task_id,
                executor_kind=executor_kind,
                dependency_run_ids=dependency_run_ids,
                strategic_assessment=strategic_assessment,
            )
        except DelegatedAgentReservationConflictError as exc:
            raise DelegatedAgentConflictError(str(exc)) from exc

    async def admit_reserved_run(
        self,
        *,
        child_agent_task_id: str,
        admitted_scope: Mapping[str, Any],
        evidence_policy: Mapping[str, Any],
        dependency_run_ids: list[str] | None = None,
        parent_continuation_required: bool = True,
    ) -> dict[str, Any]:
        try:
            return await self._reservations.admit_reserved_run(
                child_agent_task_id=child_agent_task_id,
                admitted_scope=admitted_scope,
                evidence_policy=evidence_policy,
                dependency_run_ids=dependency_run_ids,
                parent_continuation_required=parent_continuation_required,
            )
        except DelegatedAgentReservationConflictError as exc:
            raise DelegatedAgentConflictError(str(exc)) from exc

    async def create_provider_relation_and_admit_reserved_run(self, **kwargs: Any) -> dict[str, Any]:
        """Use the sole atomic provider-authority and generic-run admission boundary."""

        return await self._reservations.create_provider_relation_and_admit_reserved_run(**kwargs)

    async def mark_reservation_dispatched(self, child_agent_task_id: str) -> dict[str, Any]:
        return await self._reservations.mark_reservation_dispatched(child_agent_task_id)

    async def mark_reservation_dispatch_failed(self, child_agent_task_id: str) -> dict[str, Any]:
        return await self._reservations.mark_reservation_dispatch_failed(child_agent_task_id)

    async def get_run_for_child(self, child_agent_task_id: str) -> dict[str, Any] | None:
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            row = conn.execute(
                "SELECT * FROM delegated_agent_runs WHERE child_agent_task_id = ?",
                (_require_id(child_agent_task_id, "child_agent_task_id"),),
            ).fetchone()
        return _run_row(row) if row is not None else None

    async def get_run(self, delegated_agent_run_id: str) -> dict[str, Any] | None:
        """Load one durable delegated child for executor-side CAS transitions."""

        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            row = conn.execute(
                "SELECT * FROM delegated_agent_runs WHERE id = ?",
                (_require_id(delegated_agent_run_id, "delegated_agent_run_id"),),
            ).fetchone()
        return _run_row(row) if row is not None else None

    async def list_active_for_parent(self, parent_agent_task_id: str) -> list[dict[str, Any]]:
        """Return every unresolved child that a parent cancellation must fence."""

        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM delegated_agent_runs
                WHERE parent_agent_task_id = ? AND status IN ({",".join("?" for _ in _ACTIVE_STATUSES)})
                ORDER BY created_at ASC, id ASC
                """,
                (_require_id(parent_agent_task_id, "parent_agent_task_id"), *sorted(_ACTIVE_STATUSES)),
            ).fetchall()
        return [_run_row(row) for row in rows]

    async def list_runs_for_parent(self, parent_agent_task_id: str) -> list[dict[str, Any]]:
        """Return every durable delegated child owned by one parent in creation order."""
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            rows = conn.execute(
                """
                SELECT * FROM delegated_agent_runs
                WHERE parent_agent_task_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (_require_id(parent_agent_task_id, "parent_agent_task_id"),),
            ).fetchall()
        return [_run_row(row) for row in rows]

    async def list_restart_reconciliation_candidates(self) -> list[dict[str, Any]]:
        """Return unresolved delegated runs whose in-memory executor may be gone."""

        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM delegated_agent_runs
                WHERE status IN ({",".join("?" for _ in _ACTIVE_STATUSES)})
                ORDER BY created_at ASC, id ASC
                """,
                tuple(sorted(_ACTIVE_STATUSES)),
            ).fetchall()
        return [_run_row(row) for row in rows]

    async def transition_run(
        self,
        *,
        delegated_agent_run_id: str,
        expected_revision: int,
        next_status: str,
        event_data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if next_status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
            raise DelegatedAgentPersistenceError("next_status is unsupported")
        run_id = _require_id(delegated_agent_run_id, "delegated_agent_run_id")
        timestamp = _now()

        def write(conn: sqlite3.Connection) -> sqlite3.Row:
            row = conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise DelegatedAgentConflictError("delegated-agent run does not exist")
            if int(row["revision"]) != expected_revision:
                raise DelegatedAgentConflictError("delegated-agent run revision mismatch")
            if row["status"] in _TERMINAL_STATUSES:
                raise DelegatedAgentConflictError("delegated-agent run is already terminal")
            terminal_at = timestamp if next_status in _TERMINAL_STATUSES else None
            updated = conn.execute(
                """
                UPDATE delegated_agent_runs
                SET status = ?, revision = revision + 1, updated_at = ?, settled_at = COALESCE(?, settled_at)
                WHERE id = ? AND revision = ?
                """,
                (next_status, timestamp, terminal_at, run_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise DelegatedAgentConflictError("delegated-agent run transition lost its compare-and-swap race")
            self._insert_event(
                conn,
                delegated_agent_run_id=run_id,
                revision=expected_revision + 1,
                event_kind=f"status:{next_status}",
                event_data=event_data,
            )
            return conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()

        row = run_write_transaction(
            self.db_path,
            "transition_delegated_agent_run",
            write,
            ensure_schema=False,
        )
        return _run_row(row)

    async def start_turn(
        self,
        *,
        delegated_agent_run_id: str,
        expected_revision: int,
        controller_instruction: str,
    ) -> dict[str, Any]:
        """Persist one exclusive controller instruction before executor delivery."""

        run_id = _require_id(delegated_agent_run_id, "delegated_agent_run_id")
        instruction = _bounded_text(controller_instruction, "controller_instruction")
        timestamp = _now()

        def write(conn: sqlite3.Connection) -> sqlite3.Row:
            run = conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise DelegatedAgentConflictError("delegated-agent run does not exist")
            if int(run["revision"]) != expected_revision:
                raise DelegatedAgentConflictError("delegated-agent run revision mismatch")
            if run["status"] not in {"admitted", "idle", "supervision_due"}:
                raise DelegatedAgentConflictError("delegated-agent run is not eligible for another turn")
            active = conn.execute(
                """
                SELECT 1 FROM delegated_agent_turns
                WHERE delegated_agent_run_id = ? AND status IN ('created', 'running')
                """,
                (run_id,),
            ).fetchone()
            if active is not None:
                raise DelegatedAgentConflictError("delegated-agent run already has an active turn")
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(turn_sequence), 0) + 1 FROM delegated_agent_turns WHERE delegated_agent_run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            turn_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO delegated_agent_turns (
                    id, delegated_agent_run_id, turn_sequence, controller_instruction,
                    status, terminal_response_json, created_at, started_at, settled_at
                ) VALUES (?, ?, ?, ?, 'running', NULL, ?, ?, NULL)
                """,
                (turn_id, run_id, sequence, instruction, timestamp, timestamp),
            )
            conn.execute(
                """
                UPDATE delegated_agent_runs
                SET status = 'running', revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (timestamp, run_id, expected_revision),
            )
            self._insert_event(
                conn,
                delegated_agent_run_id=run_id,
                revision=expected_revision + 1,
                event_kind="turn_started",
                event_data={"turn_id": turn_id, "turn_sequence": sequence},
            )
            return conn.execute("SELECT * FROM delegated_agent_turns WHERE id = ?", (turn_id,)).fetchone()

        row = run_write_transaction(
            self.db_path,
            "start_delegated_agent_turn",
            write,
            ensure_schema=False,
        )
        return {
            "id": row["id"],
            "delegated_agent_run_id": row["delegated_agent_run_id"],
            "turn_sequence": int(row["turn_sequence"]),
            "controller_instruction": row["controller_instruction"],
            "status": row["status"],
        }

    async def settle_turn_idle(
        self,
        *,
        delegated_agent_run_id: str,
        turn_id: str,
        expected_revision: int,
        terminal_response: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist bounded executor evidence and make the child eligible for supervision."""

        run_id = _require_id(delegated_agent_run_id, "delegated_agent_run_id")
        clean_turn_id = _require_id(turn_id, "turn_id")
        response_json = _json_object(terminal_response, "terminal_response")
        timestamp = _now()

        def write(conn: sqlite3.Connection) -> sqlite3.Row:
            run = conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None or int(run["revision"]) != expected_revision or run["status"] != "running":
                raise DelegatedAgentConflictError("delegated-agent run cannot settle this turn")
            turn = conn.execute(
                "SELECT * FROM delegated_agent_turns WHERE id = ? AND delegated_agent_run_id = ?",
                (clean_turn_id, run_id),
            ).fetchone()
            if turn is None or turn["status"] != "running":
                raise DelegatedAgentConflictError("delegated-agent turn is not active")
            conn.execute(
                """
                UPDATE delegated_agent_turns
                SET status = 'idle', terminal_response_json = ?, settled_at = ?
                WHERE id = ?
                """,
                (response_json, timestamp, clean_turn_id),
            )
            conn.execute(
                """
                UPDATE delegated_agent_runs
                SET status = 'idle', revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (timestamp, run_id, expected_revision),
            )
            self._insert_event(
                conn,
                delegated_agent_run_id=run_id,
                revision=expected_revision + 1,
                event_kind="turn_idle",
                event_data={"turn_id": clean_turn_id},
            )
            return conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()

        row = run_write_transaction(
            self.db_path,
            "settle_delegated_agent_turn_idle",
            write,
            ensure_schema=False,
        )
        return _run_row(row)

    async def record_outcome(
        self,
        *,
        delegated_agent_run_id: str,
        expected_revision: int,
        transport_state: str,
        executor_result_state: str,
        evidence_state: str,
        summary: str,
        receipt_references: list[Mapping[str, Any]],
        terminal_status: str,
    ) -> dict[str, Any]:
        """Record terminal evidence before the parent is allowed to continue."""

        if evidence_state not in {"provider_reported", "verified", "verification_mismatch", "unavailable"}:
            raise DelegatedAgentPersistenceError("evidence_state is unsupported")
        if terminal_status not in _TERMINAL_STATUSES:
            raise DelegatedAgentPersistenceError("terminal_status is unsupported")
        run_id = _require_id(delegated_agent_run_id, "delegated_agent_run_id")
        summary_text = _bounded_text(summary, "summary")
        receipt_json = _json_object({"items": receipt_references}, "receipt_references")
        timestamp = _now()

        def write(conn: sqlite3.Connection) -> sqlite3.Row:
            run = conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None or int(run["revision"]) != expected_revision:
                raise DelegatedAgentConflictError("delegated-agent outcome revision mismatch")
            if run["status"] in _TERMINAL_STATUSES:
                raise DelegatedAgentConflictError("delegated-agent run is already terminal")
            conn.execute(
                """
                INSERT INTO delegated_agent_outcomes (
                    delegated_agent_run_id, transport_state, executor_result_state,
                    evidence_state, summary, receipt_references_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, transport_state, executor_result_state, evidence_state, summary_text, receipt_json, timestamp),
            )
            conn.execute(
                """
                UPDATE delegated_agent_runs
                SET status = ?, revision = revision + 1, updated_at = ?, settled_at = ?
                WHERE id = ? AND revision = ?
                """,
                (terminal_status, timestamp, timestamp, run_id, expected_revision),
            )
            self._insert_event(
                conn,
                delegated_agent_run_id=run_id,
                revision=expected_revision + 1,
                event_kind=f"outcome:{terminal_status}",
                event_data={"evidence_state": evidence_state, "executor_result_state": executor_result_state},
            )
            return conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()

        row = run_write_transaction(
            self.db_path,
            "record_delegated_agent_outcome",
            write,
            ensure_schema=False,
        )
        return _run_row(row)

    async def list_unsettled_dependencies(self, delegated_agent_run_id: str) -> list[dict[str, Any]]:
        run = await self.get_run(delegated_agent_run_id)
        if run is None:
            raise DelegatedAgentConflictError("delegated-agent run does not exist")
        dependency_ids = run["dependency_run_ids"]
        if not dependency_ids:
            return []
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            placeholders = ",".join("?" for _ in dependency_ids)
            rows = conn.execute(
                f"""
                SELECT * FROM delegated_agent_runs
                WHERE id IN ({placeholders})
                ORDER BY created_at ASC, id ASC
                """,
                tuple(dependency_ids),
            ).fetchall()
        found_ids = {str(row["id"]) for row in rows}
        missing_ids = sorted(set(dependency_ids) - found_ids)
        if missing_ids:
            raise DelegatedAgentConflictError(
                f"delegated dependencies do not exist: {', '.join(missing_ids)}"
            )
        rows = [row for row in rows if row["status"] not in _TERMINAL_STATUSES]
        return [_run_row(row) for row in rows]

    async def list_ready_reservations(self, parent_agent_task_id: str) -> list[dict[str, Any]]:
        return await self._reservations.list_ready_reservations(parent_agent_task_id)

    async def list_outcomes_for_parent(self, parent_agent_task_id: str) -> list[dict[str, Any]]:
        return await self._reservations.list_outcomes_for_parent(parent_agent_task_id)

    async def list_events(self, delegated_agent_run_id: str) -> list[dict[str, Any]]:
        return await self._reservations.list_events(delegated_agent_run_id)
