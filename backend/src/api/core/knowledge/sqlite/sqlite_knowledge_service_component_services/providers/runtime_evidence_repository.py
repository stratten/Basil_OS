"""Exact-runtime evidence used to gate ACP follow-up prompts."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..infrastructure.connection import get_sync_connection, run_write_transaction

_MAX_METADATA_BYTES = 8_000


class ProviderRuntimeEvidenceRepository:
    """Persist controlled protocol evidence without trusting another runtime tuple."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @staticmethod
    def _identity(
        *,
        provider_profile_id: str,
        executable_fingerprint: str,
        runtime_version: str,
        acp_major: int,
    ) -> tuple[str, str, str, str, int]:
        values = (provider_profile_id, executable_fingerprint, runtime_version)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("provider runtime evidence identity values must be nonblank strings")
        if not isinstance(acp_major, int) or acp_major < 1:
            raise ValueError("acp_major must be a positive integer")
        return (
            provider_profile_id.strip(),
            executable_fingerprint.strip(),
            runtime_version.strip(),
            "same_session_follow_up",
            acp_major,
        )

    async def record_same_session_follow_up_evidence(
        self,
        *,
        provider_profile_id: str,
        executable_fingerprint: str,
        runtime_version: str,
        acp_major: int,
        status: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in {"passed", "failed"}:
            raise ValueError("runtime evidence status must be passed or failed")
        profile_id, executable, version, kind, major = self._identity(
            provider_profile_id=provider_profile_id,
            executable_fingerprint=executable_fingerprint,
            runtime_version=runtime_version,
            acp_major=acp_major,
        )
        try:
            metadata_json = json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime evidence metadata must be JSON serializable") from exc
        if len(metadata_json.encode("utf-8")) > _MAX_METADATA_BYTES:
            raise ValueError("runtime evidence metadata exceeds the bounded storage limit")
        fingerprint = hashlib.sha256(
            f"{profile_id}\0{executable}\0{version}\0{major}\0{kind}".encode("utf-8")
        ).hexdigest()
        timestamp = datetime.utcnow().isoformat()

        def write(conn: Any) -> Any:
            existing = conn.execute(
                "SELECT * FROM provider_runtime_evidence WHERE evidence_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing is not None:
                if existing["status"] != status:
                    raise ValueError("runtime evidence identity already has a contradictory result")
                return existing
            conn.execute(
                """
                INSERT INTO provider_runtime_evidence (
                    id, provider_profile_id, executable_fingerprint, runtime_version, acp_major,
                    evidence_kind, status, evidence_fingerprint, metadata_json, observed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()), profile_id, executable, version, major, kind, status,
                    fingerprint, metadata_json, timestamp, timestamp,
                ),
            )
            return conn.execute(
                "SELECT * FROM provider_runtime_evidence WHERE evidence_fingerprint = ?",
                (fingerprint,),
            ).fetchone()

        row = run_write_transaction(self.db_path, "record_provider_runtime_evidence", write)
        return dict(row)

    async def is_exact_follow_up_certified(
        self,
        *,
        provider_profile_id: str,
        executable_fingerprint: str,
        runtime_version: str,
        acp_major: int,
    ) -> bool:
        profile_id, executable, version, kind, major = self._identity(
            provider_profile_id=provider_profile_id,
            executable_fingerprint=executable_fingerprint,
            runtime_version=runtime_version,
            acp_major=acp_major,
        )
        with get_sync_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM provider_runtime_evidence
                WHERE provider_profile_id = ? AND executable_fingerprint = ?
                  AND runtime_version = ? AND acp_major = ? AND evidence_kind = ?
                  AND status = 'passed'
                """,
                (profile_id, executable, version, major, kind),
            ).fetchone()
        return row is not None
