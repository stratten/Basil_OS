"""Read-only provider-target authority relations for generic delegated runs."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..infrastructure.connection import get_sync_connection


class ProviderTargetDelegationPersistenceError(RuntimeError):
    """Raised when a provider authority relation cannot be decoded."""


class ProviderTargetDelegationConflictError(ProviderTargetDelegationPersistenceError):
    """Retained compatibility error type for callers handling stale authority."""


def _require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderTargetDelegationPersistenceError(f"{field_name} must be a nonblank string")
    return value.strip()


def _decode_legacy_snapshot(value: object) -> dict[str, object]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProviderTargetDelegationPersistenceError("legacy_lifecycle_snapshot_json is malformed") from exc
    if not isinstance(decoded, dict):
        raise ProviderTargetDelegationPersistenceError("legacy_lifecycle_snapshot_json must decode to an object")
    return decoded


def _decode_legacy_outcome(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProviderTargetDelegationPersistenceError("legacy child result is malformed") from exc
    if not isinstance(decoded, dict):
        raise ProviderTargetDelegationPersistenceError("legacy child result must decode to an object")
    return decoded


def _relation_row(row: sqlite3.Row) -> dict[str, object]:
    snapshot = _decode_legacy_snapshot(row["legacy_lifecycle_snapshot_json"])
    return {
        "id": row["id"],
        "authorization_id": row["authorization_id"],
        "parent_agent_task_id": row["parent_agent_task_id"],
        "root_task_id": row["root_task_id"],
        "child_agent_task_id": row["child_agent_task_id"],
        "delegated_agent_run_id": row["delegated_agent_run_id"],
        "provider_profile_id": row["provider_profile_id"],
        "workspace_grant_id": row["workspace_grant_id"],
        "selected_connection_id": row["selected_connection_id"],
        "selected_tool_name": row["selected_tool_name"],
        "selected_service_policy": row["selected_service_policy"],
        "legacy_lifecycle_snapshot": snapshot,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class ProviderTargetDelegationRepository:
    """Read immutable provider selection authority; generic runs own lifecycle."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def get_delegation_by_authorization(self, authorization_id: str) -> dict[str, object] | None:
        return self._get_one("authorization_id", authorization_id)

    async def get_delegation_by_child_agent_task(self, child_agent_task_id: str) -> dict[str, object] | None:
        return self._get_one("child_agent_task_id", child_agent_task_id)

    async def get_delegation_by_parent_agent_task(self, parent_agent_task_id: str) -> dict[str, object] | None:
        return self._get_one("parent_agent_task_id", parent_agent_task_id)

    async def get_relation_by_delegated_agent_run(self, delegated_agent_run_id: str) -> dict[str, object] | None:
        return self._get_one("delegated_agent_run_id", delegated_agent_run_id)

    def _get_one(self, field_name: str, value: str) -> dict[str, object] | None:
        clean_value = _require_nonblank(value, field_name)
        query = f"SELECT * FROM provider_target_delegations WHERE {field_name} = ?"
        if field_name == "parent_agent_task_id":
            query += " ORDER BY created_at ASC, id ASC LIMIT 1"
        else:
            query += " LIMIT 1"
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(query, (clean_value,)).fetchone()
        return _relation_row(row) if row is not None else None
