"""Append-only bounded evidence for one parent-owned delegated-agent run."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from ..infrastructure.connection import get_sync_connection, run_write_transaction

MAX_SUMMARY_BYTES = 2_000
MAX_STRUCTURED_DATA_BYTES = 4_000
MAX_SOURCE_EVENT_KEY_BYTES = 256
MAX_KIND_BYTES = 96
MAX_ARTIFACT_LOCATOR_BYTES = 512
MAX_PAGE_SIZE = 50
EVIDENCE_SOURCES = frozenset({"provider_activity", "provider_terminal_response", "parent_verification", "transport_failure", "interaction_state"})
EVIDENCE_PROVENANCE = frozenset({"provider_reported", "basil_observed", "unavailable"})
VERIFICATION_STATES = frozenset({"pending", "verified", "verification_mismatch", "unavailable", "not_applicable"})


class DelegatedAgentEvidenceError(RuntimeError):
    """Raised when evidence is malformed, foreign, or contradictory."""


def _now() -> str:
    return datetime.utcnow().isoformat()


def _require_text(value: object, field_name: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelegatedAgentEvidenceError(f"{field_name} must be a nonblank string")
    text = value.strip()
    if len(text.encode("utf-8")) > maximum_bytes:
        raise DelegatedAgentEvidenceError(f"{field_name} exceeds {maximum_bytes} bytes")
    return text


def _optional_text(value: object, field_name: str, maximum_bytes: int) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name, maximum_bytes)


def _artifact_locator(value: object) -> str | None:
    locator = _optional_text(value, "artifact_locator", MAX_ARTIFACT_LOCATOR_BYTES)
    if locator is None:
        return None
    candidate_paths = (PurePosixPath(locator), PureWindowsPath(locator))
    if (
        locator.casefold().startswith("file://")
        or any(path.is_absolute() or ".." in path.parts for path in candidate_paths)
    ):
        raise DelegatedAgentEvidenceError(
            "artifact_locator must be workspace-relative or an opaque reference"
        )
    return locator


def _canonical_object(value: Mapping[str, Any] | None) -> str:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise DelegatedAgentEvidenceError("structured_data must be an object")
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise DelegatedAgentEvidenceError("structured_data must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_STRUCTURED_DATA_BYTES:
        raise DelegatedAgentEvidenceError(f"structured_data exceeds {MAX_STRUCTURED_DATA_BYTES} bytes")
    return encoded


def _decode_object(value: object) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DelegatedAgentEvidenceError("structured_data_json is malformed") from exc
    if not isinstance(decoded, dict):
        raise DelegatedAgentEvidenceError("structured_data_json must decode to an object")
    return decoded


def _row_to_evidence(row: sqlite3.Row, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "id": row["id"],
        "delegated_agent_run_id": row["delegated_agent_run_id"],
        "delegated_agent_turn_id": row["delegated_agent_turn_id"],
        "sequence": int(row["sequence"]),
        "source_event_key": row["source_event_key"],
        "source": row["source"],
        "kind": row["kind"],
        "provenance": row["provenance"],
        "verification_state": row["verification_state"],
        "summary": row["summary"],
        "structured_data": _decode_object(row["structured_data_json"]),
        "artifact_locator": row["artifact_locator"],
        "created_at": row["created_at"],
        "idempotent_replay": idempotent_replay,
    }


class DelegatedAgentEvidenceRepository:
    """Persist immutable source-keyed evidence and enforce parent/run/turn ownership."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def append_evidence(
        self,
        *,
        delegated_agent_run_id: str,
        delegated_agent_turn_id: str | None,
        source_event_key: str,
        source: str,
        kind: str,
        provenance: str,
        verification_state: str,
        summary: str,
        structured_data: Mapping[str, Any] | None = None,
        artifact_locator: str | None = None,
    ) -> dict[str, Any]:
        run_id = _require_text(delegated_agent_run_id, "delegated_agent_run_id", 128)
        turn_id = _optional_text(delegated_agent_turn_id, "delegated_agent_turn_id", 128)
        event_key = _require_text(source_event_key, "source_event_key", MAX_SOURCE_EVENT_KEY_BYTES)
        clean_source = _require_text(source, "source", 64)
        clean_kind = _require_text(kind, "kind", MAX_KIND_BYTES)
        clean_provenance = _require_text(provenance, "provenance", 64)
        clean_verification = _require_text(verification_state, "verification_state", 64)
        clean_summary = _require_text(summary, "summary", MAX_SUMMARY_BYTES)
        clean_locator = _artifact_locator(artifact_locator)
        structured_json = _canonical_object(structured_data)
        if clean_source not in EVIDENCE_SOURCES:
            raise DelegatedAgentEvidenceError("source is unsupported")
        if clean_provenance not in EVIDENCE_PROVENANCE:
            raise DelegatedAgentEvidenceError("provenance is unsupported")
        if clean_verification not in VERIFICATION_STATES:
            raise DelegatedAgentEvidenceError("verification_state is unsupported")
        timestamp = _now()

        def write(conn: sqlite3.Connection) -> tuple[sqlite3.Row, bool]:
            run = conn.execute("SELECT id FROM delegated_agent_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise DelegatedAgentEvidenceError("delegated-agent run does not exist")
            if turn_id is not None:
                turn = conn.execute(
                    "SELECT delegated_agent_run_id FROM delegated_agent_turns WHERE id = ?", (turn_id,)
                ).fetchone()
                if turn is None or turn["delegated_agent_run_id"] != run_id:
                    raise DelegatedAgentEvidenceError("delegated-agent turn is not owned by the run")
            existing = conn.execute(
                "SELECT * FROM delegated_agent_evidence WHERE delegated_agent_run_id = ? AND source_event_key = ?",
                (run_id, event_key),
            ).fetchone()
            if existing is not None:
                expected = (
                    turn_id, clean_source, clean_kind, clean_provenance, clean_verification,
                    clean_summary, structured_json, clean_locator,
                )
                actual = (
                    existing["delegated_agent_turn_id"], existing["source"], existing["kind"],
                    existing["provenance"], existing["verification_state"], existing["summary"],
                    existing["structured_data_json"], existing["artifact_locator"],
                )
                if actual != expected:
                    raise DelegatedAgentEvidenceError("source_event_key already has contradictory evidence")
                return existing, True
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM delegated_agent_evidence WHERE delegated_agent_run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            evidence_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO delegated_agent_evidence (
                    id, delegated_agent_run_id, delegated_agent_turn_id, sequence, source_event_key,
                    source, kind, provenance, verification_state, summary, structured_data_json,
                    artifact_locator, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id, run_id, turn_id, sequence, event_key, clean_source, clean_kind,
                    clean_provenance, clean_verification, clean_summary, structured_json,
                    clean_locator, timestamp,
                ),
            )
            row = conn.execute("SELECT * FROM delegated_agent_evidence WHERE id = ?", (evidence_id,)).fetchone()
            return row, False

        row, replayed = run_write_transaction(self.db_path, "append_delegated_agent_evidence", write, ensure_schema=False)
        return _row_to_evidence(row, idempotent_replay=replayed)

    async def list_evidence_for_run(
        self, *, delegated_agent_run_id: str, after_sequence: int | None = None, limit: int = 20
    ) -> dict[str, Any]:
        run_id = _require_text(delegated_agent_run_id, "delegated_agent_run_id", 128)
        if after_sequence is not None and (not isinstance(after_sequence, int) or after_sequence < 0):
            raise DelegatedAgentEvidenceError("after_sequence must be a non-negative integer")
        if not isinstance(limit, int) or limit < 1 or limit > MAX_PAGE_SIZE:
            raise DelegatedAgentEvidenceError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            rows = conn.execute(
                """
                SELECT * FROM delegated_agent_evidence
                WHERE delegated_agent_run_id = ? AND sequence > ?
                ORDER BY sequence ASC, id ASC
                LIMIT ?
                """,
                (run_id, after_sequence or 0, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        return {
            "items": [_row_to_evidence(row, idempotent_replay=False) for row in page],
            "next_after_sequence": int(page[-1]["sequence"]) if has_more and page else None,
        }

    async def get_report_card_aggregate(self, delegated_agent_run_id: str) -> dict[str, Any]:
        """Return selected aggregate facts for one run without exposing evidence bodies."""
        run_id = _require_text(delegated_agent_run_id, "delegated_agent_run_id", 128)
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            count_row = conn.execute(
                """
                SELECT COUNT(*) AS evidence_count
                FROM delegated_agent_evidence
                WHERE delegated_agent_run_id = ?
                """,
                (run_id,),
            ).fetchone()
            latest_row = conn.execute(
                """
                SELECT summary
                FROM delegated_agent_evidence
                WHERE delegated_agent_run_id = ?
                ORDER BY sequence DESC, id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            verification_rows = conn.execute(
                """
                SELECT verification_state
                FROM delegated_agent_evidence
                WHERE delegated_agent_run_id = ?
                  AND source = 'parent_verification'
                  AND kind = 'workspace_artifact_verification'
                  AND provenance = 'basil_observed'
                """,
                (run_id,),
            ).fetchall()
        evidence_count = int(count_row["evidence_count"])
        verification_states = {str(row["verification_state"]) for row in verification_rows}
        if evidence_count == 0:
            verification_state = "unavailable"
        elif "verification_mismatch" in verification_states:
            verification_state = "verification_mismatch"
        elif "verified" in verification_states:
            verification_state = "verified"
        elif verification_states:
            verification_state = "pending"
        else:
            verification_state = "not_applicable"
        return {
            "evidence_count": evidence_count,
            "latest_summary": str(latest_row["summary"]) if latest_row is not None else None,
            "verification_state": verification_state,
        }

    async def get_evidence_for_parent(
        self, *, parent_agent_task_id: str, delegated_agent_run_id: str, evidence_id: str
    ) -> dict[str, Any] | None:
        parent_id = _require_text(parent_agent_task_id, "parent_agent_task_id", 128)
        run_id = _require_text(delegated_agent_run_id, "delegated_agent_run_id", 128)
        clean_evidence_id = _require_text(evidence_id, "evidence_id", 128)
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            row = conn.execute(
                """
                SELECT evidence.*
                FROM delegated_agent_evidence AS evidence
                JOIN delegated_agent_runs AS run ON run.id = evidence.delegated_agent_run_id
                WHERE evidence.id = ? AND evidence.delegated_agent_run_id = ?
                  AND run.parent_agent_task_id = ?
                """,
                (clean_evidence_id, run_id, parent_id),
            ).fetchone()
        return _row_to_evidence(row, idempotent_replay=False) if row is not None else None

    async def get_evidence_for_parent_by_source_event_key(
        self,
        *,
        parent_agent_task_id: str,
        delegated_agent_run_id: str,
        source_event_key: str,
    ) -> dict[str, Any] | None:
        parent_id = _require_text(parent_agent_task_id, "parent_agent_task_id", 128)
        run_id = _require_text(delegated_agent_run_id, "delegated_agent_run_id", 128)
        event_key = _require_text(source_event_key, "source_event_key", MAX_SOURCE_EVENT_KEY_BYTES)
        with get_sync_connection(self.db_path, ensure_schema=False) as conn:
            row = conn.execute(
                """
                SELECT evidence.*
                FROM delegated_agent_evidence AS evidence
                JOIN delegated_agent_runs AS run ON run.id = evidence.delegated_agent_run_id
                WHERE evidence.delegated_agent_run_id = ?
                  AND evidence.source_event_key = ?
                  AND run.parent_agent_task_id = ?
                """,
                (run_id, event_key, parent_id),
            ).fetchone()
        return _row_to_evidence(row, idempotent_replay=False) if row is not None else None
