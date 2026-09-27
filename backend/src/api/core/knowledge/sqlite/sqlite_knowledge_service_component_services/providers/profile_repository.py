"""Provider profile and workspace-grant persistence."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from ..infrastructure.connection import get_sync_connection, run_write_transaction
from .errors import ProviderRunConflictError, ProviderRunPersistenceError
from .records import _get_grant_row, _get_profile_row, _row_to_grant, _row_to_profile
from .validation import (
    _json_dump_sequence,
    _require_absolute_executable_path,
    _require_absolute_workspace_root,
    _require_nonblank,
    _require_nonnegative_revision,
    _validate_environment_allowlist,
    _validate_launch_argv,
    _validate_optional_authentication_method_id,
    _validate_optional_description,
    _validate_routing_hints,
    _validate_workspace_label,
)


def utcnow() -> str:
    return datetime.utcnow().isoformat()


class ProviderProfileRepository:
    """CRUD and authorization persistence for provider profiles and grants."""

    PROFILE_STATUSES = {"enabled", "disabled", "removed"}
    GRANT_STATUSES = {"active", "revoked"}
    TRANSPORT = "acp_stdio"
    CAPABILITY_STATE = "unverified"

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def create_profile(
        self,
        *,
        display_name: str,
        launch_argv: tuple[str, ...],
        environment_allowlist: tuple[str, ...] = (),
        authentication_method_id: str | None = None,
        description: str | None = None,
        routing_hints: tuple[str, ...] = (),
        initial_status: str = "enabled",
        require_executable: bool = False,
    ) -> dict[str, object]:
        cleaned_name = _require_nonblank(display_name, "display_name")
        cleaned_argv = _validate_launch_argv(launch_argv)
        cleaned_allowlist = _validate_environment_allowlist(environment_allowlist)
        cleaned_authentication_method_id = _validate_optional_authentication_method_id(
            authentication_method_id
        )
        cleaned_description = _validate_optional_description(description)
        cleaned_routing_hints = _validate_routing_hints(routing_hints)
        if require_executable:
            _require_absolute_executable_path(cleaned_argv[0])
        if initial_status not in self.PROFILE_STATUSES - {"removed"}:
            raise ProviderRunPersistenceError(
                f"unsupported initial profile status {initial_status!r}"
            )
        profile_id = str(uuid.uuid4())
        timestamp = utcnow()
        with get_sync_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO provider_profiles (
                    id, display_name, transport, launch_argv_json,
                    environment_allowlist_json, authentication_method_id, status, capability_state,
                    description, routing_hints_json, revision,
                    created_at, updated_at, removed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unverified', ?, ?, 0, ?, ?, NULL)
                """,
                (
                    profile_id,
                    cleaned_name,
                    self.TRANSPORT,
                    _json_dump_sequence(cleaned_argv),
                    _json_dump_sequence(cleaned_allowlist),
                    cleaned_authentication_method_id,
                    initial_status,
                    cleaned_description,
                    _json_dump_sequence(cleaned_routing_hints),
                    timestamp,
                    timestamp,
                ),
            )
            conn.commit()
            row = _get_profile_row(conn, profile_id)
        if row is None:
            raise ProviderRunPersistenceError("failed to load created provider profile")
        return _row_to_profile(row)

    async def get_profile(self, provider_profile_id: str) -> dict[str, object] | None:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        with get_sync_connection(self.db_path) as conn:
            row = _get_profile_row(conn, profile_id)
        return _row_to_profile(row) if row is not None else None

    async def list_profiles(self, *, include_removed: bool = False) -> list[dict[str, object]]:
        query = "SELECT * FROM provider_profiles"
        if not include_removed:
            query += " WHERE status != 'removed'"
        query += " ORDER BY updated_at DESC"
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(query).fetchall()
        return [_row_to_profile(row) for row in rows]

    async def list_profile_ids(self, *, include_removed: bool = False) -> list[str]:
        """Return ordered profile IDs without decoding provider-controlled metadata."""
        query = "SELECT id FROM provider_profiles"
        if not include_removed:
            query += " WHERE status != 'removed'"
        query += " ORDER BY updated_at DESC"
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(query).fetchall()
        return [str(row["id"]) for row in rows]

    async def set_profile_status(
        self,
        provider_profile_id: str,
        status: str,
    ) -> dict[str, object]:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        if status not in self.PROFILE_STATUSES:
            raise ProviderRunPersistenceError(f"unsupported profile status {status!r}")
        timestamp = utcnow()
        with get_sync_connection(self.db_path) as conn:
            row = _get_profile_row(conn, profile_id)
            if row is None:
                raise ProviderRunConflictError(f"provider profile {profile_id!r} does not exist")
            removed_at = timestamp if status == "removed" else None
            conn.execute(
                """
                UPDATE provider_profiles
                SET status = ?, updated_at = ?, removed_at = ?
                WHERE id = ?
                """,
                (status, timestamp, removed_at, profile_id),
            )
            conn.commit()
            updated = _get_profile_row(conn, profile_id)
        if updated is None:
            raise ProviderRunPersistenceError("failed to load updated provider profile")
        return _row_to_profile(updated)

    async def update_profile_configuration(
        self,
        *,
        provider_profile_id: str,
        expected_revision: int,
        display_name: str,
        launch_argv: tuple[str, ...],
        environment_allowlist: tuple[str, ...],
        authentication_method_id: str | None,
        description: str | None,
        routing_hints: tuple[str, ...],
    ) -> dict[str, object]:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        revision = _require_nonnegative_revision(expected_revision)
        cleaned_name = _require_nonblank(display_name, "display_name")
        cleaned_argv = _validate_launch_argv(launch_argv)
        _require_absolute_executable_path(cleaned_argv[0])
        cleaned_allowlist = _validate_environment_allowlist(environment_allowlist)
        cleaned_authentication_method_id = _validate_optional_authentication_method_id(
            authentication_method_id
        )
        cleaned_description = _validate_optional_description(description)
        cleaned_routing_hints = _validate_routing_hints(routing_hints)
        timestamp = utcnow()

        def _update(conn: sqlite3.Connection) -> sqlite3.Row:
            row = _get_profile_row(conn, profile_id)
            if row is None or row["status"] == "removed":
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} does not exist"
                )
            if row["revision"] != revision:
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} revision mismatch"
                )
            updated = conn.execute(
                """
                UPDATE provider_profiles
                SET display_name = ?, launch_argv_json = ?, environment_allowlist_json = ?,
                    authentication_method_id = ?, description = ?, routing_hints_json = ?, updated_at = ?,
                    revision = revision + 1
                WHERE id = ? AND revision = ? AND status != 'removed'
                """,
                (
                    cleaned_name,
                    _json_dump_sequence(cleaned_argv),
                    _json_dump_sequence(cleaned_allowlist),
                    cleaned_authentication_method_id,
                    cleaned_description,
                    _json_dump_sequence(cleaned_routing_hints),
                    timestamp,
                    profile_id,
                    revision,
                ),
            )
            if updated.rowcount != 1:
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} revision mismatch"
                )
            refreshed = _get_profile_row(conn, profile_id)
            if refreshed is None:
                raise ProviderRunPersistenceError(
                    "failed to load updated provider profile"
                )
            return refreshed

        return _row_to_profile(
            run_write_transaction(self.db_path, "update_provider_profile", _update)
        )

    async def set_profile_registry_status(
        self,
        *,
        provider_profile_id: str,
        expected_revision: int,
        next_status: str,
    ) -> dict[str, object]:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        revision = _require_nonnegative_revision(expected_revision)
        if next_status not in self.PROFILE_STATUSES:
            raise ProviderRunPersistenceError(f"unsupported profile status {next_status!r}")
        timestamp = utcnow()

        def _update(conn: sqlite3.Connection) -> sqlite3.Row:
            row = _get_profile_row(conn, profile_id)
            if row is None or row["status"] == "removed":
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} does not exist"
                )
            if row["revision"] != revision:
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} revision mismatch"
                )
            if next_status == "enabled":
                profile = _row_to_profile(row)
                launch_argv = _validate_launch_argv(profile["launch_argv"])
                _require_absolute_executable_path(launch_argv[0])
                _validate_environment_allowlist(profile["environment_allowlist"])
            removed_at = timestamp if next_status == "removed" else None
            updated = conn.execute(
                """
                UPDATE provider_profiles
                SET status = ?, updated_at = ?, removed_at = ?, revision = revision + 1
                WHERE id = ? AND revision = ? AND status != 'removed'
                """,
                (next_status, timestamp, removed_at, profile_id, revision),
            )
            if updated.rowcount != 1:
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} revision mismatch"
                )
            refreshed = _get_profile_row(conn, profile_id)
            if refreshed is None:
                raise ProviderRunPersistenceError(
                    "failed to load updated provider profile"
                )
            return refreshed

        return _row_to_profile(
            run_write_transaction(
                self.db_path,
                "set_provider_profile_registry_status",
                _update,
            )
        )

    async def grant_workspace(
        self,
        *,
        provider_profile_id: str,
        canonical_workspace_root: str,
        workspace_label: str | None = None,
        description: str | None = None,
        routing_hints: tuple[str, ...] = (),
        reject_active_duplicate: bool = False,
    ) -> dict[str, object]:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        workspace_root = _require_absolute_workspace_root(
            _require_nonblank(
                canonical_workspace_root,
                "canonical_workspace_root",
            )
        )
        cleaned_label = _validate_workspace_label(
            workspace_label
            if workspace_label is not None
            else Path(workspace_root).name or workspace_root
        )
        cleaned_description = _validate_optional_description(description)
        cleaned_routing_hints = _validate_routing_hints(routing_hints)
        timestamp = utcnow()

        def _grant(conn: sqlite3.Connection) -> sqlite3.Row:
            profile = _get_profile_row(conn, profile_id)
            if profile is None or profile["status"] == "removed":
                raise ProviderRunConflictError(f"provider profile {profile_id!r} does not exist")
            grant_id = str(uuid.uuid4())
            existing = conn.execute(
                """
                SELECT * FROM provider_workspace_grants
                WHERE provider_profile_id = ? AND canonical_workspace_root = ?
                """,
                (profile_id, workspace_root),
            ).fetchone()
            if (
                reject_active_duplicate
                and existing is not None
                and existing["status"] == "active"
            ):
                raise ProviderRunConflictError(
                    f"workspace root {workspace_root!r} is already granted to profile {profile_id!r}"
                )
            conn.execute(
                """
                INSERT INTO provider_workspace_grants (
                    id, provider_profile_id, canonical_workspace_root,
                    status, workspace_label, description, routing_hints_json, revision,
                    created_at, updated_at, revoked_at
                ) VALUES (?, ?, ?, 'active', ?, ?, ?, 0, ?, ?, NULL)
                ON CONFLICT(provider_profile_id, canonical_workspace_root) DO UPDATE SET
                    status = 'active',
                    workspace_label = excluded.workspace_label,
                    description = excluded.description,
                    routing_hints_json = excluded.routing_hints_json,
                    updated_at = excluded.updated_at,
                    revoked_at = NULL,
                    revision = provider_workspace_grants.revision + 1
                """,
                (
                    grant_id,
                    profile_id,
                    workspace_root,
                    cleaned_label,
                    cleaned_description,
                    _json_dump_sequence(cleaned_routing_hints),
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM provider_workspace_grants
                WHERE provider_profile_id = ? AND canonical_workspace_root = ?
                """,
                (profile_id, workspace_root),
            ).fetchone()
            if row is None:
                raise ProviderRunPersistenceError("failed to load workspace grant")
            return row

        row = run_write_transaction(self.db_path, "grant_provider_workspace", _grant)
        if row is None:
            raise ProviderRunPersistenceError("failed to load workspace grant")
        return _row_to_grant(row)

    async def update_workspace_grant_configuration(
        self,
        *,
        provider_profile_id: str,
        workspace_grant_id: str,
        expected_revision: int,
        workspace_label: str,
        description: str | None,
        routing_hints: tuple[str, ...],
    ) -> dict[str, object]:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        grant_id = _require_nonblank(workspace_grant_id, "workspace_grant_id")
        revision = _require_nonnegative_revision(expected_revision)
        cleaned_label = _validate_workspace_label(workspace_label)
        cleaned_description = _validate_optional_description(description)
        cleaned_routing_hints = _validate_routing_hints(routing_hints)
        timestamp = utcnow()

        def _update(conn: sqlite3.Connection) -> sqlite3.Row:
            profile = _get_profile_row(conn, profile_id)
            if profile is None or profile["status"] == "removed":
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} does not exist"
                )
            row = _get_grant_row(conn, grant_id)
            if (
                row is None
                or row["provider_profile_id"] != profile_id
                or row["status"] != "active"
            ):
                raise ProviderRunConflictError(
                    f"workspace grant {grant_id!r} does not exist for profile {profile_id!r}"
                )
            if row["revision"] != revision:
                raise ProviderRunConflictError(
                    f"workspace grant {grant_id!r} revision mismatch"
                )
            updated = conn.execute(
                """
                UPDATE provider_workspace_grants
                SET workspace_label = ?, description = ?, routing_hints_json = ?,
                    updated_at = ?, revision = revision + 1
                WHERE id = ? AND provider_profile_id = ? AND status = 'active'
                  AND revision = ?
                """,
                (
                    cleaned_label,
                    cleaned_description,
                    _json_dump_sequence(cleaned_routing_hints),
                    timestamp,
                    grant_id,
                    profile_id,
                    revision,
                ),
            )
            if updated.rowcount != 1:
                raise ProviderRunConflictError(
                    f"workspace grant {grant_id!r} revision mismatch"
                )
            refreshed = _get_grant_row(conn, grant_id)
            if refreshed is None:
                raise ProviderRunPersistenceError(
                    "failed to load updated workspace grant"
                )
            return refreshed

        return _row_to_grant(
            run_write_transaction(
                self.db_path,
                "update_provider_workspace_grant",
                _update,
            )
        )

    async def revoke_workspace_grant_if_revision(
        self,
        *,
        provider_profile_id: str,
        workspace_grant_id: str,
        expected_revision: int,
    ) -> dict[str, object]:
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        grant_id = _require_nonblank(workspace_grant_id, "workspace_grant_id")
        revision = _require_nonnegative_revision(expected_revision)
        timestamp = utcnow()

        def _revoke(conn: sqlite3.Connection) -> sqlite3.Row:
            profile = _get_profile_row(conn, profile_id)
            if profile is None or profile["status"] == "removed":
                raise ProviderRunConflictError(
                    f"provider profile {profile_id!r} does not exist"
                )
            row = _get_grant_row(conn, grant_id)
            if (
                row is None
                or row["provider_profile_id"] != profile_id
                or row["status"] != "active"
            ):
                raise ProviderRunConflictError(
                    f"workspace grant {grant_id!r} does not exist for profile {profile_id!r}"
                )
            if row["revision"] != revision:
                raise ProviderRunConflictError(
                    f"workspace grant {grant_id!r} revision mismatch"
                )
            updated = conn.execute(
                """
                UPDATE provider_workspace_grants
                SET status = 'revoked', updated_at = ?, revoked_at = ?,
                    revision = revision + 1
                WHERE id = ? AND provider_profile_id = ? AND status = 'active'
                  AND revision = ?
                """,
                (timestamp, timestamp, grant_id, profile_id, revision),
            )
            if updated.rowcount != 1:
                raise ProviderRunConflictError(
                    f"workspace grant {grant_id!r} revision mismatch"
                )
            refreshed = _get_grant_row(conn, grant_id)
            if refreshed is None:
                raise ProviderRunPersistenceError(
                    "failed to load revoked workspace grant"
                )
            return refreshed

        return _row_to_grant(
            run_write_transaction(
                self.db_path,
                "revoke_provider_workspace_grant",
                _revoke,
            )
        )

    async def revoke_workspace_grant(self, workspace_grant_id: str) -> dict[str, object]:
        grant_id = _require_nonblank(workspace_grant_id, "workspace_grant_id")
        timestamp = utcnow()
        with get_sync_connection(self.db_path) as conn:
            row = _get_grant_row(conn, grant_id)
            if row is None:
                raise ProviderRunConflictError(f"workspace grant {grant_id!r} does not exist")
            conn.execute(
                """
                UPDATE provider_workspace_grants
                SET status = 'revoked', updated_at = ?, revoked_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, grant_id),
            )
            conn.commit()
            updated = _get_grant_row(conn, grant_id)
        if updated is None:
            raise ProviderRunPersistenceError("failed to load revoked workspace grant")
        return _row_to_grant(updated)

    async def get_workspace_grant(self, workspace_grant_id: str) -> dict[str, object] | None:
        grant_id = _require_nonblank(workspace_grant_id, "workspace_grant_id")
        with get_sync_connection(self.db_path) as conn:
            row = _get_grant_row(conn, grant_id)
        return _row_to_grant(row) if row is not None else None

    async def list_workspace_grants_for_profile(
        self, provider_profile_id: str, *, include_revoked: bool = False
    ) -> list[dict[str, object]]:
        """Package 5C.1: read-only workspace-grant lookup for a single profile.

        Used only for read-only presentation; it never creates or revokes a grant.
        """
        profile_id = _require_nonblank(provider_profile_id, "provider_profile_id")
        query = "SELECT * FROM provider_workspace_grants WHERE provider_profile_id = ?"
        if not include_revoked:
            query += " AND status = 'active'"
        query += " ORDER BY updated_at DESC"
        with get_sync_connection(self.db_path) as conn:
            rows = conn.execute(query, (profile_id,)).fetchall()
        return [_row_to_grant(row) for row in rows]

