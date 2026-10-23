"""Durable, append-only receipts for agent work ledger operations."""

from __future__ import annotations

import json
import sqlite3

from ..infrastructure.connection import get_sync_connection
import uuid
from typing import Any, Dict, List, Optional

from api.services.agent_processing.lifecycle.runtime.ledger_json import (
    to_ledger_json_value,
)


class AgentWorkReceiptRepository:
    """Persist and query structured tool-operation receipts."""

    EXECUTION_STATES = {"not_started", "attempted", "succeeded", "failed"}
    VERIFICATION_STATUSES = {"not_applicable", "unverified", "verified", "failed"}

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(
            to_ledger_json_value(value if value is not None else {}),
            ensure_ascii=False,
        )

    @staticmethod
    def _json_load(value: Optional[str]) -> Dict[str, Any]:
        try:
            return json.loads(value) if value else {}
        except json.JSONDecodeError:
            return {}

    @classmethod
    def _row_to_receipt(cls, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "item_id": row["item_id"],
            "agent_task_id": row["agent_task_id"],
            "service": row["service"],
            "method": row["method"],
            "receipt_key": row["receipt_key"],
            "requested_effect": cls._json_load(row["requested_effect_json"]),
            "observed_postcondition": cls._json_load(
                row["observed_postcondition_json"]
            ),
            "material_write": bool(row["material_write"]),
            "execution_state": row["execution_state"],
            "verification_status": row["verification_status"],
            "evidence": cls._json_load(row["evidence_json"]),
            "discrepancy": cls._json_load(row["discrepancy_json"]),
            "created_at": row["created_at"],
        }

    async def add_receipt(
        self,
        *,
        session_id: str,
        service: str,
        method: str,
        execution_state: str,
        verification_status: str,
        item_id: Optional[str] = None,
        agent_task_id: Optional[str] = None,
        receipt_key: Optional[str] = None,
        requested_effect: Optional[Dict[str, Any]] = None,
        observed_postcondition: Optional[Dict[str, Any]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        discrepancy: Optional[Dict[str, Any]] = None,
        material_write: bool = False,
    ) -> Dict[str, Any]:
        if execution_state not in self.EXECUTION_STATES:
            raise ValueError(f"Unsupported execution state: {execution_state}")
        if verification_status not in self.VERIFICATION_STATUSES:
            raise ValueError(f"Unsupported verification status: {verification_status}")

        is_material_write = material_write or bool(
            (requested_effect or {}).get("material_write")
        )
        if is_material_write and verification_status == "verified":
            if not (evidence or {}):
                raise ValueError("Verified material-write receipts require evidence.")

        receipt_id = str(uuid.uuid4())
        with self._get_connection() as conn:
            if agent_task_id and not conn.execute(
                "SELECT 1 FROM agent_tasks WHERE id = ?",
                (agent_task_id,),
            ).fetchone():
                agent_task_id = None
            if receipt_key:
                existing = conn.execute(
                    """
                    SELECT * FROM agent_work_receipts
                    WHERE session_id = ? AND receipt_key = ?
                    """,
                    (session_id, receipt_key),
                ).fetchone()
                if existing:
                    return self._row_to_receipt(existing)
            conn.execute(
                """
                INSERT INTO agent_work_receipts (
                    id, session_id, item_id, agent_task_id, service, method,
                    receipt_key, requested_effect_json, execution_state,
                    verification_status, observed_postcondition_json, material_write,
                    evidence_json, discrepancy_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    session_id,
                    item_id,
                    agent_task_id,
                    service,
                    method,
                    receipt_key,
                    self._json_dump(requested_effect),
                    execution_state,
                    verification_status,
                    self._json_dump(observed_postcondition),
                    int(is_material_write),
                    self._json_dump(evidence),
                    self._json_dump(discrepancy),
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM agent_work_receipts WHERE id = ?",
                (receipt_id,),
            ).fetchone()
        return self._row_to_receipt(row)

    async def get_receipts(
        self,
        *,
        session_id: str,
        item_id: Optional[str] = None,
        verification_status: Optional[str] = None,
        service: Optional[str] = None,
        method: Optional[str] = None,
        agent_task_id: Optional[str] = None,
        limit: int = 20,
        newest_first: bool = False,
    ) -> List[Dict[str, Any]]:
        conditions = ["session_id = ?"]
        params: List[Any] = [session_id]
        for column, value in (
            ("item_id", item_id),
            ("verification_status", verification_status),
            ("service", service),
            ("method", method),
            ("agent_task_id", agent_task_id),
        ):
            if value:
                conditions.append(f"{column} = ?")
                params.append(value)
        params.append(min(max(int(limit or 1), 1), 50))
        order = "DESC" if newest_first else "ASC"
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM agent_work_receipts
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at {order}, rowid {order}
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_receipt(row) for row in rows]

    async def count_material_receipts_by_status(
        self,
        *,
        session_id: str,
    ) -> Dict[str, int]:
        """Return exact per-status counts for every material receipt in a session."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT verification_status, COUNT(*) AS count
                FROM agent_work_receipts
                WHERE session_id = ? AND material_write = 1
                GROUP BY verification_status
                """,
                (session_id,),
            ).fetchall()
        return {row["verification_status"]: row["count"] for row in rows}

    async def get_unresolved_material_receipts(
        self,
        *,
        session_id: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return a bounded, newest-first sample of unresolved material receipts."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_work_receipts
                WHERE session_id = ?
                  AND material_write = 1
                  AND verification_status IN ('unverified', 'failed')
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (session_id, min(max(int(limit or 1), 1), 50)),
            ).fetchall()
        return [self._row_to_receipt(row) for row in rows]
