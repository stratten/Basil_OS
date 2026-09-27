"""Durable provider interactions (Packages 4A-4B.2).

Mirrors `ProviderRunRepository`'s connection and optimistic-revision style. Every terminal mutation requires the caller's last-known `revision` and fails closed (`ProviderInteractionConflictError`) on any mismatch, missing row, or non-`pending` status, so two concurrent resolutions of the same interaction can never both succeed.
"""

from __future__ import annotations

import json
import sqlite3

from ..infrastructure.connection import get_sync_connection, run_write_transaction
import uuid
from datetime import datetime
from typing import Any, Mapping, Sequence


class ProviderInteractionPersistenceError(RuntimeError):
    """Base error for provider-interaction persistence failures."""


class ProviderInteractionConflictError(ProviderInteractionPersistenceError):
    """Stale revision, unknown interaction, or invalid run/task preconditions."""


TERMINAL_INTERACTION_STATUSES = {"answered", "declined", "cancelled", "superseded"}


class ProviderInteractionRepository:
    """Persist durable provider user-input interactions linked to one provider run."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    @staticmethod
    def _utcnow() -> str:
        return datetime.utcnow().isoformat()

    @staticmethod
    def _require_nonblank(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ProviderInteractionPersistenceError(f"{field_name} must be a nonblank string")
        return value.strip()

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @classmethod
    def _json_load(cls, raw: str | None, field_name: str) -> Any:
        if raw is None:
            raise ProviderInteractionPersistenceError(f"{field_name} is missing")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderInteractionPersistenceError(f"{field_name} contains invalid JSON") from exc

    @classmethod
    def _row_to_interaction(cls, row: sqlite3.Row) -> dict[str, object]:
        submitted_values = None
        if row["submitted_values_json"] is not None:
            submitted_values = cls._json_load(row["submitted_values_json"], "submitted_values_json")
        return {
            "id": row["id"],
            "provider_run_id": row["provider_run_id"],
            "agent_task_id": row["agent_task_id"],
            "root_task_id": row["root_task_id"],
            "interaction_kind": row["interaction_kind"],
            "mode": row["mode"],
            "message": row["message"],
            "requested_schema": cls._json_load(row["requested_schema_json"], "requested_schema_json"),
            "fields": cls._json_load(row["fields_json"], "fields_json"),
            "status": row["status"],
            "outcome": row["outcome"],
            "submitted_values": submitted_values,
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
        }

    async def create_interaction(
        self,
        *,
        provider_run_id: str,
        agent_task_id: str,
        root_task_id: str,
        message: str,
        requested_schema: Mapping[str, Any],
        fields: Sequence[Mapping[str, Any]],
        interaction_kind: str = "provider_user_input",
        mode: str = "form",
    ) -> dict[str, object]:
        run_id = self._require_nonblank(provider_run_id, "provider_run_id")
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        root_id = self._require_nonblank(root_task_id, "root_task_id")
        cleaned_message = self._require_nonblank(message, "message")
        interaction_id = str(uuid.uuid4())
        timestamp = self._utcnow()
        def _create(conn: sqlite3.Connection) -> sqlite3.Row:
            if not conn.execute(
                "SELECT 1 FROM provider_runs WHERE id = ?", (run_id,)
            ).fetchone():
                raise ProviderInteractionConflictError(f"provider run {run_id!r} does not exist")
            if not conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ?", (task_id,)
            ).fetchone():
                raise ProviderInteractionConflictError(f"agent task {task_id!r} does not exist")
            conn.execute(
                """
                INSERT INTO provider_interactions (
                    id, provider_run_id, agent_task_id, root_task_id, interaction_kind,
                    mode, message, requested_schema_json, fields_json, status, outcome,
                    submitted_values_json, revision, created_at, updated_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, 0, ?, ?, NULL)
                """,
                (
                    interaction_id,
                    run_id,
                    task_id,
                    root_id,
                    interaction_kind,
                    mode,
                    cleaned_message,
                    self._json_dump(dict(requested_schema)),
                    self._json_dump([dict(field) for field in fields]),
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM provider_interactions WHERE id = ?", (interaction_id,)
            ).fetchone()
            if row is None:
                raise ProviderInteractionPersistenceError("failed to load created provider interaction")
            return row

        try:
            row = run_write_transaction(self.db_path, "create_provider_interaction", _create)
        except sqlite3.IntegrityError as exc:
            raise ProviderInteractionConflictError(
                f"provider interaction could not be created for run {run_id!r}"
            ) from exc
        if row is None:
            raise ProviderInteractionPersistenceError("failed to load created provider interaction")
        return self._row_to_interaction(row)

    async def get_interaction(self, interaction_id: str) -> dict[str, object] | None:
        clean_id = self._require_nonblank(interaction_id, "interaction_id")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_interactions WHERE id = ?", (clean_id,)
            ).fetchone()
        return self._row_to_interaction(row) if row is not None else None

    async def get_pending_interaction_for_agent_task(
        self, agent_task_id: str
    ) -> dict[str, object] | None:
        """Return the newest pending provider user-input interaction for one task."""
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM provider_interactions
                WHERE agent_task_id = ?
                  AND interaction_kind = 'provider_user_input'
                  AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return self._row_to_interaction(row) if row is not None else None

    async def _resolve(
        self,
        *,
        interaction_id: str,
        expected_revision: int,
        next_status: str,
        outcome: str,
        submitted_values: Mapping[str, str] | None,
    ) -> dict[str, object]:
        clean_id = self._require_nonblank(interaction_id, "interaction_id")
        if type(expected_revision) is not int:
            raise ProviderInteractionPersistenceError("expected_revision must be an integer")
        timestamp = self._utcnow()
        values_json = self._json_dump(dict(submitted_values)) if submitted_values is not None else None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_interactions WHERE id = ?", (clean_id,)
            ).fetchone()
            if row is None:
                raise ProviderInteractionConflictError(f"provider interaction {clean_id!r} does not exist")
            if row["revision"] != expected_revision:
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} revision mismatch: "
                    f"expected {expected_revision}, got {row['revision']}"
                )
            if row["status"] != "pending":
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} is not pending (status={row['status']!r})"
                )
            updated = conn.execute(
                """
                UPDATE provider_interactions
                SET status = ?, outcome = ?, submitted_values_json = ?,
                    updated_at = ?, resolved_at = ?, revision = revision + 1
                WHERE id = ? AND status = 'pending' AND revision = ?
                """,
                (next_status, outcome, values_json, timestamp, timestamp, clean_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} could not transition to {next_status!r}"
                )
            conn.commit()
            refreshed = conn.execute(
                "SELECT * FROM provider_interactions WHERE id = ?", (clean_id,)
            ).fetchone()
        if refreshed is None:
            raise ProviderInteractionPersistenceError("failed to load resolved provider interaction")
        return self._row_to_interaction(refreshed)

    async def mark_answered(
        self, *, interaction_id: str, expected_revision: int, submitted_values: Mapping[str, str]
    ) -> dict[str, object]:
        return await self._resolve(
            interaction_id=interaction_id,
            expected_revision=expected_revision,
            next_status="answered",
            outcome="accept",
            submitted_values=submitted_values,
        )

    async def mark_declined(self, *, interaction_id: str, expected_revision: int) -> dict[str, object]:
        return await self._resolve(
            interaction_id=interaction_id,
            expected_revision=expected_revision,
            next_status="declined",
            outcome="decline",
            submitted_values=None,
        )

    async def mark_cancelled(self, *, interaction_id: str, expected_revision: int) -> dict[str, object]:
        return await self._resolve(
            interaction_id=interaction_id,
            expected_revision=expected_revision,
            next_status="cancelled",
            outcome="cancel",
            submitted_values=None,
        )

    async def supersede_pending_for_run(self, provider_run_id: str) -> int:
        """Mark all pending interactions, including `provider_permission` rows, superseded when a provider run ends."""
        run_id = self._require_nonblank(provider_run_id, "provider_run_id")
        timestamp = self._utcnow()
        with self._get_connection() as conn:
            updated = conn.execute(
                """
                UPDATE provider_interactions
                SET status = 'superseded', outcome = 'cancel',
                    updated_at = ?, resolved_at = ?, revision = revision + 1
                WHERE provider_run_id = ? AND status = 'pending'
                """,
                (timestamp, timestamp, run_id),
            )
            conn.commit()
            return updated.rowcount

    async def create_permission_interaction(
        self,
        *,
        provider_run_id: str,
        agent_task_id: str,
        root_task_id: str,
        action_summary: Mapping[str, Any],
    ) -> dict[str, object]:
        """Persist one normalized, pending `provider_permission` interaction (Package 4B.2)."""
        if not isinstance(action_summary, Mapping):
            raise ProviderInteractionPersistenceError("action_summary must be an object")
        from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_permission_action_summary import (
            InvalidPermissionActionSummaryError,
            normalize_permission_action_summary,
        )

        run_id = self._require_nonblank(provider_run_id, "provider_run_id")
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        root_id = self._require_nonblank(root_task_id, "root_task_id")
        try:
            normalized_summary = normalize_permission_action_summary(
                title=action_summary.get("title"),
                description=action_summary.get("description"),
                options=action_summary.get("options"),
                subject=action_summary.get("subject"),
            )
        except InvalidPermissionActionSummaryError as exc:
            raise ProviderInteractionPersistenceError(f"invalid permission action summary: {exc}") from exc
        title = str(normalized_summary["title"])
        options = list(normalized_summary["options"])
        requested_schema = {
            "description": normalized_summary["description"],
            "subject": normalized_summary["subject"],
        }
        interaction_id = str(uuid.uuid4())
        timestamp = self._utcnow()
        def _create_permission(conn: sqlite3.Connection) -> sqlite3.Row:
            run = conn.execute(
                "SELECT agent_task_id, root_task_id FROM provider_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise ProviderInteractionConflictError(f"provider run {run_id!r} does not exist")
            if run["agent_task_id"] != task_id or run["root_task_id"] != root_id:
                raise ProviderInteractionConflictError(
                    f"provider run {run_id!r} does not belong to agent task {task_id!r} "
                    f"and root task {root_id!r}"
                )
            agent_task = conn.execute(
                "SELECT root_task_id FROM agent_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if agent_task is None:
                raise ProviderInteractionConflictError(f"agent task {task_id!r} does not exist")
            if agent_task["root_task_id"] != root_id:
                raise ProviderInteractionConflictError(
                    f"agent task {task_id!r} does not belong to root task {root_id!r}"
                )
            conn.execute(
                """
                INSERT INTO provider_interactions (
                    id, provider_run_id, agent_task_id, root_task_id, interaction_kind,
                    mode, message, requested_schema_json, fields_json, status, outcome,
                    submitted_values_json, revision, created_at, updated_at, resolved_at
                ) VALUES (?, ?, ?, ?, 'provider_permission', 'form', ?, ?, ?, 'pending', NULL, NULL, 0, ?, ?, NULL)
                """,
                (
                    interaction_id,
                    run_id,
                    task_id,
                    root_id,
                    title,
                    self._json_dump(requested_schema),
                    self._json_dump(options),
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM provider_interactions WHERE id = ?", (interaction_id,)
            ).fetchone()
            if row is None:
                raise ProviderInteractionPersistenceError(
                    "failed to load created provider permission interaction"
                )
            return row

        try:
            row = run_write_transaction(
                self.db_path,
                "create_provider_permission_interaction",
                _create_permission,
            )
        except sqlite3.IntegrityError as exc:
            raise ProviderInteractionConflictError(
                f"provider permission interaction could not be created for run {run_id!r}"
            ) from exc
        if row is None:
            raise ProviderInteractionPersistenceError(
                "failed to load created provider permission interaction"
            )
        return self._row_to_interaction(row)

    async def _resolve_permission(
        self,
        *,
        interaction_id: str,
        provider_run_id: str,
        agent_task_id: str,
        expected_revision: int,
        next_status: str,
        outcome: str,
        submitted_values: Mapping[str, str] | None,
    ) -> dict[str, object]:
        clean_id = self._require_nonblank(interaction_id, "interaction_id")
        run_id = self._require_nonblank(provider_run_id, "provider_run_id")
        task_id = self._require_nonblank(agent_task_id, "agent_task_id")
        if type(expected_revision) is not int:
            raise ProviderInteractionPersistenceError("expected_revision must be an integer")
        timestamp = self._utcnow()
        values_json = self._json_dump(dict(submitted_values)) if submitted_values is not None else None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_interactions WHERE id = ?", (clean_id,)
            ).fetchone()
            if row is None:
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} does not exist"
                )
            if row["interaction_kind"] != "provider_permission":
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} is not a provider_permission interaction"
                )
            if row["provider_run_id"] != run_id:
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} does not belong to provider run {run_id!r}"
                )
            if row["agent_task_id"] != task_id:
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} does not belong to agent task {task_id!r}"
                )
            if row["revision"] != expected_revision:
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} revision mismatch: "
                    f"expected {expected_revision}, got {row['revision']}"
                )
            if row["status"] != "pending":
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} is not pending (status={row['status']!r})"
                )
            updated = conn.execute(
                """
                UPDATE provider_interactions
                SET status = ?, outcome = ?, submitted_values_json = ?,
                    updated_at = ?, resolved_at = ?, revision = revision + 1
                WHERE id = ? AND status = 'pending' AND revision = ?
                """,
                (next_status, outcome, values_json, timestamp, timestamp, clean_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise ProviderInteractionConflictError(
                    f"provider interaction {clean_id!r} could not transition to {next_status!r}"
                )
            conn.commit()
            refreshed = conn.execute(
                "SELECT * FROM provider_interactions WHERE id = ?", (clean_id,)
            ).fetchone()
        if refreshed is None:
            raise ProviderInteractionPersistenceError(
                "failed to load resolved provider permission interaction"
            )
        return self._row_to_interaction(refreshed)

    async def resolve_permission_interaction(
        self,
        *,
        interaction_id: str,
        provider_run_id: str,
        agent_task_id: str,
        expected_revision: int,
        selected_option_id: str,
    ) -> dict[str, object]:
        """CAS-transition one pending `provider_permission` interaction to an offered decision (Package 4B.2)."""
        if not isinstance(selected_option_id, str) or not selected_option_id.strip():
            raise ProviderInteractionPersistenceError("selected_option_id must be a nonblank string")
        option_id = selected_option_id
        interaction = await self.get_interaction(interaction_id)
        if interaction is None:
            raise ProviderInteractionConflictError(f"provider interaction {interaction_id!r} does not exist")
        if interaction["interaction_kind"] != "provider_permission":
            raise ProviderInteractionConflictError(
                f"provider interaction {interaction_id!r} is not a provider_permission interaction"
            )
        options = interaction["fields"]
        if (
            not isinstance(options, Sequence)
            or isinstance(options, (str, bytes, bytearray))
            or any(not isinstance(option, Mapping) for option in options)
        ):
            raise ProviderInteractionPersistenceError(
                f"provider interaction {interaction_id!r} has invalid permission options"
            )
        offered_option_ids = {option.get("optionId") for option in options}
        if option_id not in offered_option_ids:
            raise ProviderInteractionConflictError(
                f"provider interaction {interaction_id!r} does not offer option {option_id!r}"
            )
        return await self._resolve_permission(
            interaction_id=interaction_id,
            provider_run_id=provider_run_id,
            agent_task_id=agent_task_id,
            expected_revision=expected_revision,
            next_status="answered",
            outcome="accept",
            submitted_values={"selected_option_id": option_id},
        )

    async def cancel_permission_interaction(
        self,
        *,
        interaction_id: str,
        provider_run_id: str,
        agent_task_id: str,
        expected_revision: int,
    ) -> dict[str, object]:
        """CAS-transition one pending `provider_permission` interaction to `cancelled` (Package 4B.2)."""
        return await self._resolve_permission(
            interaction_id=interaction_id,
            provider_run_id=provider_run_id,
            agent_task_id=agent_task_id,
            expected_revision=expected_revision,
            next_status="cancelled",
            outcome="cancel",
            submitted_values=None,
        )


__all__ = [
    "ProviderInteractionRepository",
    "ProviderInteractionPersistenceError",
    "ProviderInteractionConflictError",
    "TERMINAL_INTERACTION_STATUSES",
]
