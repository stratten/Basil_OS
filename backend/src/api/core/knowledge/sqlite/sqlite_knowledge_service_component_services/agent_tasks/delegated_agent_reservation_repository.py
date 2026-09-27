"""Reservation admission and projection queries for delegated child runs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..infrastructure.connection import get_sync_connection, run_write_transaction

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


class DelegatedAgentReservationConflictError(RuntimeError):
    """Raised when durable reservation or admission preconditions are not met."""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _require_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelegatedAgentReservationConflictError(f"{field_name} must be a nonblank string")
    return value.strip()


def _json_object(value: Mapping[str, Any], field_name: str) -> str:
    if not isinstance(value, Mapping):
        raise DelegatedAgentReservationConflictError(f"{field_name} must be an object")
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise DelegatedAgentReservationConflictError(f"{field_name} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise DelegatedAgentReservationConflictError(f"{field_name} exceeds {_MAX_TEXT_BYTES} bytes")
    return encoded


def _decode_object(value: object, field_name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DelegatedAgentReservationConflictError(f"{field_name} is malformed") from exc
    if not isinstance(decoded, dict):
        raise DelegatedAgentReservationConflictError(f"{field_name} must decode to an object")
    return decoded


def _scope_conflicts(existing_scope: Mapping[str, Any], candidate_scope: Mapping[str, Any]) -> bool:
    if bool(existing_scope.get("read_only")) or bool(candidate_scope.get("read_only")):
        return False
    return bool(
        {str(path) for path in existing_scope.get("mutable_paths", [])}
        & {str(path) for path in candidate_scope.get("mutable_paths", [])}
    )


def _strategic_assessment(value: Mapping[str, Any] | None) -> tuple[dict[str, Any], str]:
    if not isinstance(value, Mapping):
        raise DelegatedAgentReservationConflictError("strategic_assessment must be an object")
    assessment = {
        "parallelism_reason": _require_id(value.get("parallelism_reason"), "parallelism_reason"),
        "independence_rationale": _require_id(value.get("independence_rationale"), "independence_rationale"),
        "expected_benefit": _require_id(value.get("expected_benefit"), "expected_benefit"),
        "parent_work_can_continue": value.get("parent_work_can_continue"),
        "child_cannot_delegate": value.get("child_cannot_delegate"),
    }
    if assessment["parent_work_can_continue"] is not True and assessment["parent_work_can_continue"] is not False:
        raise DelegatedAgentReservationConflictError("parent_work_can_continue must be a boolean")
    if assessment["child_cannot_delegate"] is not True:
        raise DelegatedAgentReservationConflictError("child_cannot_delegate must be true")
    encoded = _json_object(assessment, "strategic_assessment")
    return assessment, encoded


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    dependency_ids = json.loads(row["dependency_run_ids_json"])
    if not isinstance(dependency_ids, list) or not all(isinstance(item, str) for item in dependency_ids):
        raise DelegatedAgentReservationConflictError("dependency_run_ids_json must decode to a string array")
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


class DelegatedAgentReservationRepository:
    """Own reservation-state transitions and the initial generic-run admission."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        *,
        delegated_agent_run_id: str,
        revision: int,
        event_kind: str,
        event_data: Mapping[str, Any],
    ) -> None:
        encoded = _json_object(event_data, "event_data")
        conn.execute(
            """
            INSERT INTO delegated_agent_events (
                id, delegated_agent_run_id, revision, event_kind, event_data_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), delegated_agent_run_id, revision, event_kind, encoded, _now()),
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
        parent_id = _require_id(parent_agent_task_id, "parent_agent_task_id")
        root_id = _require_id(root_task_id, "root_task_id")
        child_id = _require_id(child_agent_task_id, "child_agent_task_id")
        if executor_kind not in {"acp_provider", "internal_agent"}:
            raise DelegatedAgentReservationConflictError("executor_kind is unsupported")
        dependency_ids = [_require_id(item, "dependency_run_id") for item in dependency_run_ids or []]
        _, assessment_json = _strategic_assessment(strategic_assessment)
        if len(dependency_ids) != len(set(dependency_ids)):
            raise DelegatedAgentReservationConflictError("delegated dependencies contain duplicates")
        timestamp = _now()

        def write(conn: sqlite3.Connection) -> sqlite3.Row:
            parent = conn.execute("SELECT root_task_id FROM agent_tasks WHERE id = ?", (parent_id,)).fetchone()
            child = conn.execute("SELECT root_task_id, status FROM agent_tasks WHERE id = ?", (child_id,)).fetchone()
            if parent is None or child is None or parent["root_task_id"] != root_id or child["root_task_id"] != root_id:
                raise DelegatedAgentReservationConflictError("parent or child is not bound to the requested root task")
            if child["status"] != "routing":
                raise DelegatedAgentReservationConflictError("reserved delegated child must still be routing")
            existing = conn.execute(
                "SELECT * FROM delegated_agent_child_reservations WHERE child_agent_task_id = ?", (child_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["parent_agent_task_id"] != parent_id
                    or existing["root_task_id"] != root_id
                    or existing["executor_kind"] != executor_kind
                    or json.loads(existing["dependency_run_ids_json"]) != sorted(dependency_ids)
                    or existing["strategic_assessment_json"] != assessment_json
                ):
                    raise DelegatedAgentReservationConflictError("child task already has a different delegated reservation")
                return existing
            conn.execute(
                """
                INSERT INTO delegated_agent_child_reservations (
                    child_agent_task_id, parent_agent_task_id, root_task_id, executor_kind,
                    dependency_run_ids_json, strategic_assessment_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?)
                """,
                (
                    child_id,
                    parent_id,
                    root_id,
                    executor_kind,
                    json.dumps(sorted(dependency_ids), ensure_ascii=False, separators=(",", ":")),
                    assessment_json,
                    timestamp,
                    timestamp,
                ),
            )
            return conn.execute(
                "SELECT * FROM delegated_agent_child_reservations WHERE child_agent_task_id = ?", (child_id,)
            ).fetchone()

        return dict(run_write_transaction(self.db_path, "reserve_delegated_agent_child", write, ensure_schema=False))

    async def admit_reserved_run(
        self,
        *,
        child_agent_task_id: str,
        admitted_scope: Mapping[str, Any],
        evidence_policy: Mapping[str, Any],
        dependency_run_ids: list[str] | None = None,
        parent_continuation_required: bool = True,
    ) -> dict[str, Any]:
        child_id = _require_id(child_agent_task_id, "child_agent_task_id")
        scope_json = _json_object(admitted_scope, "admitted_scope")
        policy_json = _json_object(evidence_policy, "evidence_policy")
        scope = json.loads(scope_json)
        supplied_dependencies = [_require_id(item, "dependency_run_id") for item in dependency_run_ids or []]
        if len(supplied_dependencies) != len(set(supplied_dependencies)):
            raise DelegatedAgentReservationConflictError("delegated dependencies contain duplicates")
        dependency_ids = sorted(supplied_dependencies)
        timestamp = _now()
        run_id = str(uuid.uuid4())

        def write(conn: sqlite3.Connection) -> sqlite3.Row | dict[str, Any]:
            reservation = conn.execute(
                "SELECT * FROM delegated_agent_child_reservations WHERE child_agent_task_id = ?", (child_id,)
            ).fetchone()
            if reservation is None:
                raise DelegatedAgentReservationConflictError("delegated child was not reserved")
            existing = conn.execute(
                "SELECT * FROM delegated_agent_runs WHERE child_agent_task_id = ?", (child_id,)
            ).fetchone()
            if existing is not None:
                return existing
            parent_id = reservation["parent_agent_task_id"]
            if dependency_run_ids is None:
                supplied_reservation_dependencies = json.loads(reservation["dependency_run_ids_json"])
                if not isinstance(supplied_reservation_dependencies, list):
                    raise DelegatedAgentReservationConflictError("reservation dependencies are malformed")
                dependency_ids[:] = sorted(supplied_reservation_dependencies)
            if child_id in dependency_ids:
                raise DelegatedAgentReservationConflictError("delegated run cannot depend on itself")
            active_rows = conn.execute(
                f"SELECT * FROM delegated_agent_runs WHERE parent_agent_task_id = ? AND status IN ({','.join('?' for _ in _ACTIVE_STATUSES)})",
                (parent_id, *sorted(_ACTIVE_STATUSES)),
            ).fetchall()
            if len(active_rows) >= _MAX_ACTIVE_CHILDREN:
                raise DelegatedAgentReservationConflictError("parent already has three active delegated children")
            if any(_scope_conflicts(_decode_object(row["admitted_scope_json"], "admitted_scope_json"), scope) for row in active_rows):
                raise DelegatedAgentReservationConflictError("delegated mutable scope conflicts with an active child")
            if dependency_ids:
                placeholders = ",".join("?" for _ in dependency_ids)
                dependencies = conn.execute(
                    f"SELECT id, parent_agent_task_id, status FROM delegated_agent_runs WHERE id IN ({placeholders})",
                    tuple(dependency_ids),
                ).fetchall()
                if len(dependencies) != len(dependency_ids) or any(row["parent_agent_task_id"] != parent_id for row in dependencies):
                    raise DelegatedAgentReservationConflictError("delegated dependencies must be existing siblings")
                blocked_dependency_run_ids = sorted(
                    str(row["id"])
                    for row in dependencies
                    if row["status"] not in _TERMINAL_STATUSES
                )
                if blocked_dependency_run_ids:
                    return {
                        "ready": False,
                        "blocked_dependency_run_ids": blocked_dependency_run_ids,
                        "reservation": dict(reservation),
                    }
            conn.execute(
                """
                INSERT INTO delegated_agent_runs (
                    id, parent_agent_task_id, root_task_id, child_agent_task_id, executor_kind,
                    admitted_scope_json, evidence_policy_json, dependency_run_ids_json,
                    parent_continuation_required, status, revision, created_at, updated_at, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'admitted', 0, ?, ?, NULL)
                """,
                (
                    run_id, parent_id, reservation["root_task_id"], child_id, reservation["executor_kind"],
                    scope_json, policy_json, json.dumps(dependency_ids), int(parent_continuation_required),
                    timestamp, timestamp,
                ),
            )
            self._insert_event(
                conn,
                delegated_agent_run_id=run_id,
                revision=0,
                event_kind="admitted",
                event_data={"reservation_status": "reserved", "dependency_count": len(dependency_ids)},
            )
            return conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()

        result = run_write_transaction(
            self.db_path,
            "admit_reserved_delegated_agent_run",
            write,
            ensure_schema=False,
        )
        if isinstance(result, dict):
            return result
        return _run_row(result)

    async def create_provider_relation_and_admit_reserved_run(
        self,
        *,
        authorization_id: str,
        child_agent_task_id: str,
        provider_profile_id: str,
        workspace_grant_id: str,
        selected_connection_id: str | None,
        selected_tool_name: str | None,
        selected_service_policy: str | None,
        admitted_scope: Mapping[str, Any],
        evidence_policy: Mapping[str, Any],
        dependency_run_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Atomically bind current provider authority to one admitted reserved child."""

        authorization = _require_id(authorization_id, "authorization_id")
        child_id = _require_id(child_agent_task_id, "child_agent_task_id")
        profile_id = _require_id(provider_profile_id, "provider_profile_id")
        grant_id = _require_id(workspace_grant_id, "workspace_grant_id")
        scope_json = _json_object(admitted_scope, "admitted_scope")
        policy_json = _json_object(evidence_policy, "evidence_policy")
        scope = json.loads(scope_json)
        supplied_dependencies = [_require_id(item, "dependency_run_id") for item in dependency_run_ids or []]
        if len(supplied_dependencies) != len(set(supplied_dependencies)):
            raise DelegatedAgentReservationConflictError("delegated dependencies contain duplicates")
        dependency_ids = sorted(supplied_dependencies)
        timestamp = _now()
        run_id = str(uuid.uuid4())
        relation_id = str(uuid.uuid4())

        def write(conn: sqlite3.Connection) -> sqlite3.Row:
            authority = conn.execute(
                """
                SELECT agent_task_id, root_task_id, status, expires_at,
                       selected_provider_profile_id, selected_workspace_grant_id
                FROM provider_target_authorizations WHERE id = ?
                """,
                (authorization,),
            ).fetchone()
            if authority is None or authority["status"] != "authorized":
                raise DelegatedAgentReservationConflictError("provider authorization is not current")
            if (
                authority["selected_provider_profile_id"] != profile_id
                or authority["selected_workspace_grant_id"] != grant_id
                or datetime.fromisoformat(str(authority["expires_at"])) <= datetime.utcnow()
            ):
                raise DelegatedAgentReservationConflictError("provider authorization selection is not current")
            existing_relation = conn.execute(
                "SELECT * FROM provider_target_delegations WHERE authorization_id = ?", (authorization,)
            ).fetchone()
            if existing_relation is not None:
                existing_run_id = existing_relation["delegated_agent_run_id"]
                if existing_run_id is None:
                    raise DelegatedAgentReservationConflictError("provider relation exists without generic run")
                run = conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (existing_run_id,)).fetchone()
                if run is None:
                    raise DelegatedAgentReservationConflictError("provider relation references a missing generic run")
                return run
            reservation = conn.execute(
                "SELECT * FROM delegated_agent_child_reservations WHERE child_agent_task_id = ?", (child_id,)
            ).fetchone()
            if reservation is None or reservation["executor_kind"] != "acp_provider":
                raise DelegatedAgentReservationConflictError("provider child was not reserved")
            if reservation["parent_agent_task_id"] != authority["agent_task_id"] or reservation["root_task_id"] != authority["root_task_id"]:
                raise DelegatedAgentReservationConflictError("provider reservation does not match authorization authority")
            if child_id in dependency_ids:
                raise DelegatedAgentReservationConflictError("delegated run cannot depend on itself")
            active_rows = conn.execute(
                f"SELECT * FROM delegated_agent_runs WHERE parent_agent_task_id = ? AND status IN ({','.join('?' for _ in _ACTIVE_STATUSES)})",
                (reservation["parent_agent_task_id"], *sorted(_ACTIVE_STATUSES)),
            ).fetchall()
            if len(active_rows) >= _MAX_ACTIVE_CHILDREN:
                raise DelegatedAgentReservationConflictError("parent already has three active delegated children")
            if any(_scope_conflicts(_decode_object(row["admitted_scope_json"], "admitted_scope_json"), scope) for row in active_rows):
                raise DelegatedAgentReservationConflictError("delegated mutable scope conflicts with an active child")
            if dependency_ids:
                placeholders = ",".join("?" for _ in dependency_ids)
                dependencies = conn.execute(
                    f"SELECT id, parent_agent_task_id, status FROM delegated_agent_runs WHERE id IN ({placeholders})",
                    tuple(dependency_ids),
                ).fetchall()
                if len(dependencies) != len(dependency_ids) or any(row["parent_agent_task_id"] != reservation["parent_agent_task_id"] for row in dependencies):
                    raise DelegatedAgentReservationConflictError("delegated dependencies must be existing siblings")
                if any(row["status"] not in _TERMINAL_STATUSES for row in dependencies):
                    raise DelegatedAgentReservationConflictError("delegated dependencies are not settled")
            conn.execute(
                """
                INSERT INTO delegated_agent_runs (
                    id, parent_agent_task_id, root_task_id, child_agent_task_id, executor_kind,
                    admitted_scope_json, evidence_policy_json, dependency_run_ids_json,
                    parent_continuation_required, status, revision, created_at, updated_at, settled_at
                ) VALUES (?, ?, ?, ?, 'acp_provider', ?, ?, ?, 1, 'admitted', 0, ?, ?, NULL)
                """,
                (
                    run_id, reservation["parent_agent_task_id"], reservation["root_task_id"], child_id,
                    scope_json, policy_json, json.dumps(dependency_ids), timestamp, timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO provider_target_delegations (
                    id, authorization_id, parent_agent_task_id, root_task_id, child_agent_task_id,
                    delegated_agent_run_id, provider_profile_id, workspace_grant_id,
                    selected_connection_id, selected_tool_name, selected_service_policy,
                    legacy_lifecycle_snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    relation_id, authorization, reservation["parent_agent_task_id"], reservation["root_task_id"],
                    child_id, run_id, profile_id, grant_id, selected_connection_id, selected_tool_name,
                    selected_service_policy, timestamp, timestamp,
                ),
            )
            self._insert_event(
                conn,
                delegated_agent_run_id=run_id,
                revision=0,
                event_kind="admitted",
                event_data={"reservation_status": "reserved", "provider_relation_id": relation_id},
            )
            return conn.execute("SELECT * FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()

        return _run_row(
            run_write_transaction(
                self.db_path,
                "create_provider_relation_and_admit_reserved_run",
                write,
                ensure_schema=False,
            )
        )

    async def mark_reservation_dispatched(self, child_agent_task_id: str) -> dict[str, Any]:
        return await self._set_reservation_status(child_agent_task_id, "dispatched")

    async def mark_reservation_dispatch_failed(self, child_agent_task_id: str) -> dict[str, Any]:
        return await self._set_reservation_status(child_agent_task_id, "dispatch_failed")

    async def _set_reservation_status(self, child_agent_task_id: str, status: str) -> dict[str, Any]:
        child_id = _require_id(child_agent_task_id, "child_agent_task_id")
        timestamp = _now()

        def write(conn: sqlite3.Connection) -> sqlite3.Row:
            row = conn.execute(
                "SELECT * FROM delegated_agent_child_reservations WHERE child_agent_task_id = ?", (child_id,)
            ).fetchone()
            if row is None:
                raise DelegatedAgentReservationConflictError("delegated child was not reserved")
            if row["status"] == status:
                return row
            if row["status"] != "reserved":
                raise DelegatedAgentReservationConflictError("delegated reservation is no longer dispatchable")
            conn.execute(
                "UPDATE delegated_agent_child_reservations SET status = ?, updated_at = ? WHERE child_agent_task_id = ?",
                (status, timestamp, child_id),
            )
            return conn.execute(
                "SELECT * FROM delegated_agent_child_reservations WHERE child_agent_task_id = ?", (child_id,)
            ).fetchone()

        return dict(run_write_transaction(self.db_path, f"mark_delegated_reservation_{status}", write, ensure_schema=False))

    async def list_ready_reservations(self, parent_agent_task_id: str) -> list[dict[str, Any]]:
        parent_id = _require_id(parent_agent_task_id, "parent_agent_task_id")
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            rows = conn.execute(
                """
                SELECT r.* FROM delegated_agent_child_reservations r
                LEFT JOIN delegated_agent_runs d ON d.child_agent_task_id = r.child_agent_task_id
                WHERE r.parent_agent_task_id = ? AND r.status = 'reserved' AND d.id IS NULL
                ORDER BY r.created_at ASC, r.child_agent_task_id ASC
                """,
                (parent_id,),
            ).fetchall()
            ready: list[dict[str, Any]] = []
            for row in rows:
                dependency_ids = json.loads(row["dependency_run_ids_json"])
                if not isinstance(dependency_ids, list) or not all(isinstance(item, str) for item in dependency_ids):
                    raise DelegatedAgentReservationConflictError("reservation dependencies are malformed")
                if dependency_ids:
                    placeholders = ",".join("?" for _ in dependency_ids)
                    unresolved = conn.execute(
                        f"SELECT 1 FROM delegated_agent_runs WHERE id IN ({placeholders}) AND status NOT IN ({','.join('?' for _ in _TERMINAL_STATUSES)})",
                        (*dependency_ids, *sorted(_TERMINAL_STATUSES)),
                    ).fetchone()
                    if unresolved is not None:
                        continue
                ready.append(dict(row))
        return ready

    async def list_outcomes_for_parent(self, parent_agent_task_id: str) -> list[dict[str, Any]]:
        parent_id = _require_id(parent_agent_task_id, "parent_agent_task_id")
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            rows = conn.execute(
                """
                SELECT r.id AS delegated_agent_run_id, r.executor_kind, r.status AS terminal_status,
                       o.evidence_state, o.summary, o.receipt_references_json, o.created_at
                FROM delegated_agent_runs r
                JOIN delegated_agent_outcomes o ON o.delegated_agent_run_id = r.id
                WHERE r.parent_agent_task_id = ?
                ORDER BY o.created_at ASC, r.id ASC
                """,
                (parent_id,),
            ).fetchall()
        return [
            {
                "delegated_agent_run_id": row["delegated_agent_run_id"],
                "executor_kind": row["executor_kind"],
                "terminal_status": row["terminal_status"],
                "evidence_state": row["evidence_state"],
                "summary": row["summary"],
                "receipt_references": _decode_object(row["receipt_references_json"], "receipt_references_json"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def list_events(self, delegated_agent_run_id: str) -> list[dict[str, Any]]:
        run_id = _require_id(delegated_agent_run_id, "delegated_agent_run_id")
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            rows = conn.execute(
                """
                SELECT id, revision, event_kind, event_data_json, created_at
                FROM delegated_agent_events
                WHERE delegated_agent_run_id = ?
                ORDER BY revision ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "revision": int(row["revision"]),
                "event_kind": row["event_kind"],
                "event_data": _decode_object(row["event_data_json"], "event_data_json"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
