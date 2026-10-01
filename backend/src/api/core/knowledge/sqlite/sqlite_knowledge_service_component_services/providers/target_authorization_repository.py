"""Immutable durable attempts to authorize one provider target proposal."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json
import sqlite3
import uuid

from ..infrastructure.connection import get_sync_connection, run_write_transaction


class ProviderTargetAuthorizationPersistenceError(RuntimeError):
    """Raised when a target-authorization record is malformed or cannot persist."""


class ProviderTargetAuthorizationConflictError(ProviderTargetAuthorizationPersistenceError):
    """Raised when task binding, parent resolution, or replay ownership conflicts."""


AUTHORIZATION_STATUSES = frozenset(
    {"authorized", "needs_user", "rejected", "clarification_received", "canceled"}
)


def _require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderTargetAuthorizationPersistenceError(
            f"{field_name} must be a nonblank string"
        )
    return value.strip()


def _optional_nonblank(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_nonblank(value, field_name)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json_array(raw: object, field_name: str) -> list[object]:
    if not isinstance(raw, str):
        raise ProviderTargetAuthorizationPersistenceError(f"{field_name} is missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderTargetAuthorizationPersistenceError(
            f"{field_name} contains invalid JSON"
        ) from exc
    if not isinstance(value, list):
        raise ProviderTargetAuthorizationPersistenceError(
            f"{field_name} must contain a JSON array"
        )
    return value


def _row_to_authorization(row: sqlite3.Row, *, idempotent_replay: bool) -> dict[str, object]:
    return {
        "id": row["id"],
        "parent_authorization_id": row["parent_authorization_id"],
        "proposal_id": row["proposal_id"],
        "agent_task_id": row["agent_task_id"],
        "root_task_id": row["root_task_id"],
        "status": row["status"],
        "reason_code": row["reason_code"],
        "selected_provider_profile_id": row["selected_provider_profile_id"],
        "selected_workspace_grant_id": row["selected_workspace_grant_id"],
        "selected_connection_id": row["selected_connection_id"],
        "selected_tool_name": row["selected_tool_name"],
        "selected_service_policy": row["selected_service_policy"],
        "resolved_workspace_path": row["resolved_workspace_path"],
        "reference_paths": _load_json_array(row["reference_paths_json"], "reference_paths_json"),
        "choice_snapshot": _load_json_array(row["choice_snapshot_json"], "choice_snapshot_json"),
        "response_fingerprint": row["response_fingerprint"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "idempotent_replay": idempotent_replay,
    }


class ProviderTargetAuthorizationRepository:
    """Persist initial and one-response immutable authorization attempts."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def get_authorization(self, authorization_id: str) -> dict[str, object] | None:
        clean_id = _require_nonblank(authorization_id, "authorization_id")
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM provider_target_authorizations WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return _row_to_authorization(row, idempotent_replay=False) if row is not None else None

    async def get_single_pending_initial_authorization_for_task(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
    ) -> dict[str, object] | None:
        task_id = _require_nonblank(agent_task_id, "agent_task_id")
        root_id = _require_nonblank(root_task_id, "root_task_id")
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM provider_target_authorizations
                WHERE agent_task_id = ?
                  AND root_task_id = ?
                  AND parent_authorization_id IS NULL
                  AND status = 'needs_user'
                ORDER BY created_at ASC, id ASC
                """,
                (task_id, root_id),
            ).fetchall()
        if len(rows) != 1:
            return None
        return _row_to_authorization(rows[0], idempotent_replay=False)

    async def create_initial_authorization(
        self,
        *,
        proposal_id: str,
        agent_task_id: str,
        root_task_id: str,
        status: str,
        reason_code: str,
        selected_provider_profile_id: str | None,
        selected_workspace_grant_id: str | None,
        selected_connection_id: str | None,
        selected_tool_name: str | None,
        selected_service_policy: str | None,
        resolved_workspace_path: str | None,
        reference_paths: Sequence[str],
        choice_snapshot: Sequence[Mapping[str, object]],
        expires_at: str,
    ) -> dict[str, object]:
        return await self._create_authorization(
            parent_authorization_id=None,
            proposal_id=proposal_id,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            status=status,
            reason_code=reason_code,
            selected_provider_profile_id=selected_provider_profile_id,
            selected_workspace_grant_id=selected_workspace_grant_id,
            selected_connection_id=selected_connection_id,
            selected_tool_name=selected_tool_name,
            selected_service_policy=selected_service_policy,
            resolved_workspace_path=resolved_workspace_path,
            reference_paths=reference_paths,
            choice_snapshot=choice_snapshot,
            response_fingerprint=None,
            expires_at=expires_at,
            operation_name="create_initial_provider_target_authorization",
        )

    async def create_response_authorization(
        self,
        *,
        parent_authorization_id: str,
        proposal_id: str,
        agent_task_id: str,
        root_task_id: str,
        status: str,
        reason_code: str,
        selected_provider_profile_id: str | None,
        selected_workspace_grant_id: str | None,
        selected_connection_id: str | None,
        selected_tool_name: str | None,
        selected_service_policy: str | None,
        resolved_workspace_path: str | None,
        reference_paths: Sequence[str],
        choice_snapshot: Sequence[Mapping[str, object]],
        response_value: str,
        expires_at: str,
    ) -> dict[str, object]:
        response = _require_nonblank(response_value, "response_value")
        fingerprint = hashlib.sha256(response.encode("utf-8")).hexdigest()
        return await self._create_authorization(
            parent_authorization_id=parent_authorization_id,
            proposal_id=proposal_id,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            status=status,
            reason_code=reason_code,
            selected_provider_profile_id=selected_provider_profile_id,
            selected_workspace_grant_id=selected_workspace_grant_id,
            selected_connection_id=selected_connection_id,
            selected_tool_name=selected_tool_name,
            selected_service_policy=selected_service_policy,
            resolved_workspace_path=resolved_workspace_path,
            reference_paths=reference_paths,
            choice_snapshot=choice_snapshot,
            response_fingerprint=fingerprint,
            expires_at=expires_at,
            operation_name="create_response_provider_target_authorization",
        )

    async def _create_authorization(
        self,
        *,
        parent_authorization_id: str | None,
        proposal_id: str,
        agent_task_id: str,
        root_task_id: str,
        status: str,
        reason_code: str,
        selected_provider_profile_id: str | None,
        selected_workspace_grant_id: str | None,
        selected_connection_id: str | None,
        selected_tool_name: str | None,
        selected_service_policy: str | None,
        resolved_workspace_path: str | None,
        reference_paths: Sequence[str],
        choice_snapshot: Sequence[Mapping[str, object]],
        response_fingerprint: str | None,
        expires_at: str,
        operation_name: str,
    ) -> dict[str, object]:
        clean_status = _require_nonblank(status, "status")
        if clean_status not in AUTHORIZATION_STATUSES:
            raise ProviderTargetAuthorizationPersistenceError("status is unsupported")
        values = {
            "proposal_id": _require_nonblank(proposal_id, "proposal_id"),
            "agent_task_id": _require_nonblank(agent_task_id, "agent_task_id"),
            "root_task_id": _require_nonblank(root_task_id, "root_task_id"),
            "reason_code": _require_nonblank(reason_code, "reason_code"),
            "expires_at": _require_nonblank(expires_at, "expires_at"),
        }
        parent_id = _optional_nonblank(parent_authorization_id, "parent_authorization_id")
        selected = [
            _optional_nonblank(value, name)
            for value, name in (
                (selected_provider_profile_id, "selected_provider_profile_id"),
                (selected_workspace_grant_id, "selected_workspace_grant_id"),
                (selected_connection_id, "selected_connection_id"),
                (selected_tool_name, "selected_tool_name"),
                (selected_service_policy, "selected_service_policy"),
                (resolved_workspace_path, "resolved_workspace_path"),
            )
        ]
        serialized_paths = _canonical_json(
            [_require_nonblank(path, "reference_paths entry") for path in reference_paths]
        )
        serialized_choices = _canonical_json([dict(item) for item in choice_snapshot])
        created_at = datetime.utcnow().isoformat()
        new_id = str(uuid.uuid4())

        def write(conn: sqlite3.Connection) -> tuple[sqlite3.Row, bool]:
            proposal = conn.execute(
                "SELECT agent_task_id, root_task_id FROM provider_discovery_proposals WHERE id = ?",
                (values["proposal_id"],),
            ).fetchone()
            if (
                proposal is None
                or proposal["agent_task_id"] != values["agent_task_id"]
                or proposal["root_task_id"] != values["root_task_id"]
            ):
                raise ProviderTargetAuthorizationConflictError(
                    "proposal is not bound to the current Agent Task"
                )
            if parent_id is None:
                existing = conn.execute(
                    """
                    SELECT * FROM provider_target_authorizations
                    WHERE proposal_id = ? AND parent_authorization_id IS NULL
                    """,
                    (values["proposal_id"],),
                ).fetchone()
                if existing is not None:
                    return existing, True
            else:
                parent = conn.execute(
                    "SELECT * FROM provider_target_authorizations WHERE id = ?",
                    (parent_id,),
                ).fetchone()
                if (
                    parent is None
                    or parent["proposal_id"] != values["proposal_id"]
                    or parent["agent_task_id"] != values["agent_task_id"]
                    or parent["status"] != "needs_user"
                ):
                    raise ProviderTargetAuthorizationConflictError(
                        "authorization response is not bound to a pending target checkpoint"
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM provider_target_authorizations
                    WHERE parent_authorization_id = ?
                    """,
                    (parent_id,),
                ).fetchone()
                if existing is not None:
                    if existing["response_fingerprint"] == response_fingerprint:
                        return existing, True
                    raise ProviderTargetAuthorizationConflictError(
                        "target checkpoint already received a different response"
                    )
            conn.execute(
                """
                INSERT INTO provider_target_authorizations (
                    id, parent_authorization_id, proposal_id, agent_task_id, root_task_id,
                    status, reason_code, selected_provider_profile_id,
                    selected_workspace_grant_id, selected_connection_id, selected_tool_name,
                    selected_service_policy, resolved_workspace_path, reference_paths_json,
                    choice_snapshot_json, response_fingerprint, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    parent_id,
                    values["proposal_id"],
                    values["agent_task_id"],
                    values["root_task_id"],
                    clean_status,
                    values["reason_code"],
                    *selected,
                    serialized_paths,
                    serialized_choices,
                    response_fingerprint,
                    created_at,
                    values["expires_at"],
                ),
            )
            row = conn.execute(
                "SELECT * FROM provider_target_authorizations WHERE id = ?",
                (new_id,),
            ).fetchone()
            if row is None:
                raise ProviderTargetAuthorizationPersistenceError(
                    "failed to load persisted target authorization"
                )
            return row, False

        try:
            row, replayed = run_write_transaction(self.db_path, operation_name, write)
        except sqlite3.IntegrityError as exc:
            raise ProviderTargetAuthorizationConflictError(
                "target authorization could not be persisted"
            ) from exc
        return _row_to_authorization(row, idempotent_replay=replayed)
