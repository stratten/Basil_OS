"""Durable, idempotent provider-target discovery proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json
import sqlite3
import uuid

from ..infrastructure.connection import get_sync_connection, run_write_transaction


class ProviderDiscoveryProposalPersistenceError(RuntimeError):
    """Raised when proposal input or durable proposal state is malformed."""


class ProviderDiscoveryProposalConflictError(ProviderDiscoveryProposalPersistenceError):
    """Raised when a proposal cannot be bound to its requested Agent Task."""


def _require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderDiscoveryProposalPersistenceError(
            f"{field_name} must be a nonblank string"
        )
    return value.strip()


def _require_mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ProviderDiscoveryProposalPersistenceError(f"{field_name} must be an object")
    return dict(value)


def _require_mapping_sequence(value: object, field_name: str) -> list[dict[str, object]]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ProviderDiscoveryProposalPersistenceError(f"{field_name} must be an array")
    return [
        _require_mapping(item, f"{field_name}[{index}]")
        for index, item in enumerate(value)
    ]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _load_json_array(raw: object, field_name: str) -> list[object]:
    if not isinstance(raw, str):
        raise ProviderDiscoveryProposalPersistenceError(f"{field_name} is missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderDiscoveryProposalPersistenceError(
            f"{field_name} contains invalid JSON"
        ) from exc
    if not isinstance(value, list):
        raise ProviderDiscoveryProposalPersistenceError(
            f"{field_name} must contain a JSON array"
        )
    return value


def _load_json_object(raw: object, field_name: str) -> dict[str, object]:
    if not isinstance(raw, str):
        raise ProviderDiscoveryProposalPersistenceError(f"{field_name} is missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderDiscoveryProposalPersistenceError(
            f"{field_name} contains invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ProviderDiscoveryProposalPersistenceError(
            f"{field_name} must contain a JSON object"
        )
    return dict(value)


def _row_to_proposal(
    row: sqlite3.Row,
    *,
    idempotent_replay: bool,
) -> dict[str, object]:
    return {
        "id": row["id"],
        "agent_task_id": row["agent_task_id"],
        "root_task_id": row["root_task_id"],
        "status": row["status"],
        "grounding_tier": row["grounding_tier"],
        "confidence": row["confidence"],
        "provider_candidates": _load_json_array(
            row["provider_candidates_json"],
            "provider_candidates_json",
        ),
        "service_candidates": _load_json_array(
            row["service_candidates_json"],
            "service_candidates_json",
        ),
        "evidence": _load_json_array(row["evidence_json"], "evidence_json"),
        "exact_user_constraints": _load_json_object(
            row["exact_user_constraints_json"],
            "exact_user_constraints_json",
        ),
        "rationale": row["rationale"],
        "resolution_note": row["resolution_note"],
        "proposal_fingerprint": row["proposal_fingerprint"],
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
        "idempotent_replay": idempotent_replay,
    }


class ProviderDiscoveryProposalRepository:
    """Persist proposals after the semantic layer validates their content."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def create_or_get_proposal(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        status: str,
        grounding_tier: str,
        confidence: str,
        provider_candidates: Sequence[Mapping[str, object]],
        service_candidates: Sequence[Mapping[str, object]],
        evidence: Sequence[Mapping[str, object]],
        exact_user_constraints: Mapping[str, object],
        rationale: str,
        resolution_note: str | None,
        expires_at: str,
    ) -> dict[str, object]:
        task_id = _require_nonblank(agent_task_id, "agent_task_id")
        root_id = _require_nonblank(root_task_id, "root_task_id")
        cleaned_status = _require_nonblank(status, "status")
        cleaned_grounding_tier = _require_nonblank(grounding_tier, "grounding_tier")
        cleaned_confidence = _require_nonblank(confidence, "confidence")
        cleaned_candidates = _require_mapping_sequence(
            provider_candidates,
            "provider_candidates",
        )
        cleaned_services = _require_mapping_sequence(
            service_candidates,
            "service_candidates",
        )
        cleaned_evidence = _require_mapping_sequence(evidence, "evidence")
        cleaned_constraints = _require_mapping(
            exact_user_constraints,
            "exact_user_constraints",
        )
        cleaned_rationale = _require_nonblank(rationale, "rationale")
        cleaned_resolution_note = (
            _require_nonblank(resolution_note, "resolution_note")
            if resolution_note is not None
            else None
        )
        cleaned_expires_at = _require_nonblank(expires_at, "expires_at")
        fingerprint_payload = {
            "agent_task_id": task_id,
            "root_task_id": root_id,
            "status": cleaned_status,
            "grounding_tier": cleaned_grounding_tier,
            "confidence": cleaned_confidence,
            "provider_candidates": cleaned_candidates,
            "service_candidates": cleaned_services,
            "evidence": cleaned_evidence,
            "exact_user_constraints": cleaned_constraints,
            "rationale": cleaned_rationale,
            "resolution_note": cleaned_resolution_note,
        }
        fingerprint = hashlib.sha256(
            _canonical_json(fingerprint_payload).encode("utf-8")
        ).hexdigest()
        proposal_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        def _create_or_get(conn: sqlite3.Connection) -> tuple[sqlite3.Row, bool]:
            task_row = conn.execute(
                "SELECT COALESCE(root_task_id, id) AS root_id FROM agent_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise ProviderDiscoveryProposalConflictError(
                    f"agent task {task_id!r} does not exist"
                )
            if task_row["root_id"] != root_id:
                raise ProviderDiscoveryProposalConflictError(
                    f"root task {root_id!r} does not match the Agent Task root "
                    f"{task_row['root_id']!r}"
                )
            if conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ?",
                (root_id,),
            ).fetchone() is None:
                raise ProviderDiscoveryProposalConflictError(
                    f"root task {root_id!r} does not exist"
                )
            existing = conn.execute(
                """
                SELECT * FROM provider_discovery_proposals
                WHERE agent_task_id = ? AND proposal_fingerprint = ?
                """,
                (task_id, fingerprint),
            ).fetchone()
            if existing is not None:
                return existing, True
            conn.execute(
                """
                INSERT INTO provider_discovery_proposals (
                    id, agent_task_id, root_task_id, status, grounding_tier,
                    confidence, provider_candidates_json, service_candidates_json,
                    evidence_json, exact_user_constraints_json, rationale,
                    resolution_note, proposal_fingerprint, revision, created_at,
                    updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    proposal_id,
                    task_id,
                    root_id,
                    cleaned_status,
                    cleaned_grounding_tier,
                    cleaned_confidence,
                    _canonical_json(cleaned_candidates),
                    _canonical_json(cleaned_services),
                    _canonical_json(cleaned_evidence),
                    _canonical_json(cleaned_constraints),
                    cleaned_rationale,
                    cleaned_resolution_note,
                    fingerprint,
                    timestamp,
                    timestamp,
                    cleaned_expires_at,
                ),
            )
            created = conn.execute(
                "SELECT * FROM provider_discovery_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if created is None:
                raise ProviderDiscoveryProposalPersistenceError(
                    "failed to load created provider discovery proposal"
                )
            return created, False

        try:
            row, replayed = run_write_transaction(
                self.db_path,
                "create_or_get_provider_discovery_proposal",
                _create_or_get,
            )
        except sqlite3.IntegrityError as exc:
            raise ProviderDiscoveryProposalConflictError(
                "provider discovery proposal could not be created"
            ) from exc
        return _row_to_proposal(row, idempotent_replay=replayed)

    async def get_proposal(
        self,
        proposal_id: str,
    ) -> dict[str, object] | None:
        clean_id = _require_nonblank(proposal_id, "proposal_id")
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM provider_discovery_proposals WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return (
            _row_to_proposal(row, idempotent_replay=False)
            if row is not None
            else None
        )

    async def get_latest_proposal_for_agent_task(
        self,
        agent_task_id: str,
    ) -> dict[str, object] | None:
        task_id = _require_nonblank(agent_task_id, "agent_task_id")
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM provider_discovery_proposals
                WHERE agent_task_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return (
            _row_to_proposal(row, idempotent_replay=False)
            if row is not None
            else None
        )
