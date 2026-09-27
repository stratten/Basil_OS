"""SQLite row mapping and authority helpers for provider persistence."""

from __future__ import annotations

import sqlite3

from .errors import ProviderRunConflictError
from .validation import (
    _json_load_object,
    _json_load_string_sequence,
    _require_nonblank,
    _validate_optional_authentication_method_id,
    _validate_optional_description,
    _validate_routing_hints,
)

def _row_to_profile(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "transport": row["transport"],
        "launch_argv": _json_load_string_sequence(
            row["launch_argv_json"],
            "launch_argv_json",
        ),
        "environment_allowlist": _json_load_string_sequence(
            row["environment_allowlist_json"],
            "environment_allowlist_json",
        ),
        "authentication_method_id": _validate_optional_authentication_method_id(
            row["authentication_method_id"]
        ),
        "status": row["status"],
        "capability_state": row["capability_state"],
        "description": _validate_optional_description(row["description"]),
        "routing_hints": _validate_routing_hints(
            _json_load_string_sequence(
                row["routing_hints_json"],
                "routing_hints_json",
            )
        ),
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "removed_at": row["removed_at"],
    }

def _row_to_grant(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "provider_profile_id": row["provider_profile_id"],
        "canonical_workspace_root": row["canonical_workspace_root"],
        "status": row["status"],
        "workspace_label": row["workspace_label"] or row["canonical_workspace_root"],
        "description": _validate_optional_description(row["description"]),
        "routing_hints": _validate_routing_hints(
            _json_load_string_sequence(
                row["routing_hints_json"],
                "routing_hints_json",
            )
        ),
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "revoked_at": row["revoked_at"],
    }

def _row_to_run(row: sqlite3.Row) -> dict[str, object]:
    capabilities = None
    if row["capability_snapshot_json"] is not None:
        capabilities = _json_load_object(
            row["capability_snapshot_json"],
            "capability_snapshot_json",
        )
    return {
        "id": row["id"],
        "agent_task_id": row["agent_task_id"],
        "root_task_id": row["root_task_id"],
        "provider_profile_id": row["provider_profile_id"],
        "workspace_grant_id": row["workspace_grant_id"],
        "provider_session_id": row["provider_session_id"],
        "capabilities": capabilities,
        "status": row["status"],
        "runtime_version": row["runtime_version"],
        "launch_fingerprint": row["launch_fingerprint"],
        "last_provider_event_id": row["last_provider_event_id"],
        "generation": row["generation"],
        "revision": row["revision"],
        "terminal_reason": row["terminal_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "terminal_at": row["terminal_at"],
    }

def _get_profile_row(
    conn: sqlite3.Connection,
    provider_profile_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM provider_profiles WHERE id = ?",
        (provider_profile_id,),
    ).fetchone()

def _get_grant_row(
    conn: sqlite3.Connection,
    workspace_grant_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM provider_workspace_grants WHERE id = ?",
        (workspace_grant_id,),
    ).fetchone()

def _require_enabled_profile(
    conn: sqlite3.Connection,
    provider_profile_id: str,
) -> sqlite3.Row:
    profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
    row = _get_profile_row(conn, profile_id)
    if row is None:
        raise ProviderRunConflictError(f"provider profile {profile_id!r} does not exist")
    if row["status"] != "enabled":
        raise ProviderRunConflictError(
            f"provider profile {profile_id!r} is not enabled"
        )
    return row

def _require_active_grant_for_profile(
    conn: sqlite3.Connection,
    *,
    provider_profile_id: str,
    workspace_grant_id: str,
) -> sqlite3.Row:
    grant_id = _require_nonblank(workspace_grant_id, "workspace_grant_id")
    row = _get_grant_row(conn, grant_id)
    if row is None:
        raise ProviderRunConflictError(f"workspace grant {grant_id!r} does not exist")
    if row["provider_profile_id"] != provider_profile_id:
        raise ProviderRunConflictError(
            f"workspace grant {grant_id!r} does not belong to profile {provider_profile_id!r}"
        )
    if row["status"] != "active":
        raise ProviderRunConflictError(f"workspace grant {grant_id!r} is not active")
    return row
