"""Source-safe entity and relationship persistence for agent work sessions."""

from __future__ import annotations

import json
import sqlite3

from ..infrastructure.connection import get_sync_connection
import uuid
from typing import Any, Dict, List, Optional

from api.services.agent_processing.lifecycle.runtime.ledger_json import (
    to_ledger_json_value,
)


class AgentWorkEntityRepository:
    """Persist ledger entities by fully qualified source identity."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(
            to_ledger_json_value(value if value is not None else {}),
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _json_load(raw: Optional[str]) -> Dict[str, Any]:
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @classmethod
    def _row_to_entity(cls, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "external_id": row["external_id"],
            "entity_type": row["entity_type"],
            "source_system": row["source_system"],
            "source_scope": cls._json_load(row["source_scope_json"]),
            "identity_quality": row["identity_quality"],
            "batch_index": row["batch_index"],
            "status": row["status"],
            "metadata": cls._json_load(row["metadata_json"]),
            "decision": cls._json_load(row["decision_json"]),
            "detail_summary": row["detail_summary"],
            "action_result": cls._json_load(row["action_result_json"]),
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    async def get_entity(
        self,
        *,
        session_id: str,
        item_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_work_items
                WHERE session_id = ? AND id = ?
                """,
                (session_id, item_id),
            ).fetchone()
        return self._row_to_entity(row) if row else None

    async def find_by_external_id(
        self,
        *,
        session_id: str,
        external_id: str,
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_work_items
                WHERE session_id = ? AND external_id = ?
                ORDER BY created_at, id
                """,
                (session_id, external_id),
            ).fetchall()
        return [self._row_to_entity(row) for row in rows]

    async def get_entities(
        self,
        *,
        session_id: str,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_work_items
                WHERE session_id = ?
                ORDER BY created_at, id
                LIMIT ?
                """,
                (session_id, min(max(int(limit or 1), 1), 500)),
            ).fetchall()
        return [self._row_to_entity(row) for row in rows]

    async def upsert_entity(
        self,
        *,
        session_id: str,
        entity_type: str,
        source_system: str,
        source_scope: Dict[str, Any],
        external_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "discovered",
        batch_index: int = 0,
        identity_quality: str = "source_safe",
    ) -> Dict[str, Any]:
        scope_json = self._json_dump(source_scope)
        with self._get_connection() as conn:
            existing = conn.execute(
                """
                SELECT * FROM agent_work_items
                WHERE session_id = ?
                  AND entity_type = ?
                  AND source_system = ?
                  AND source_scope_json = ?
                  AND external_id = ?
                """,
                (
                    session_id,
                    entity_type,
                    source_system,
                    scope_json,
                    external_id,
                ),
            ).fetchone()
            if existing:
                if metadata:
                    merged_metadata = self._json_load(existing["metadata_json"])
                    for key, value in to_ledger_json_value(metadata).items():
                        merged_metadata.setdefault(key, value)
                    conn.execute(
                        """
                        UPDATE agent_work_items
                        SET metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (self._json_dump(merged_metadata), existing["id"]),
                    )
                    existing = conn.execute(
                        "SELECT * FROM agent_work_items WHERE id = ?",
                        (existing["id"],),
                    ).fetchone()
                conn.commit()
                return self._row_to_entity(existing)

            item_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO agent_work_items (
                    id, session_id, external_id, entity_type, source_system,
                    source_scope_json, identity_quality, batch_index, status,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    session_id,
                    external_id,
                    entity_type,
                    source_system,
                    scope_json,
                    identity_quality,
                    batch_index,
                    status,
                    self._json_dump(metadata),
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_work_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            conn.commit()
        return self._row_to_entity(row)

    async def add_relation(
        self,
        *,
        session_id: str,
        source_item_id: str,
        target_item_id: str,
        relationship_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        agent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if relationship_type not in {"parent", "derived_from", "same_as"}:
            raise ValueError(f"Unsupported entity relationship: {relationship_type}")
        relation_id = str(uuid.uuid4())
        with self._get_connection() as conn:
            existing = conn.execute(
                """
                SELECT * FROM agent_work_entity_relations
                WHERE session_id = ? AND source_item_id = ? AND target_item_id = ?
                  AND relationship_type = ?
                """,
                (session_id, source_item_id, target_item_id, relationship_type),
            ).fetchone()
            if not existing:
                conn.execute(
                    """
                    INSERT INTO agent_work_entity_relations (
                        id, session_id, source_item_id, target_item_id,
                        relationship_type, metadata_json, agent_task_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relation_id,
                        session_id,
                        source_item_id,
                        target_item_id,
                        relationship_type,
                        self._json_dump(metadata),
                        agent_task_id,
                    ),
                )
                existing = conn.execute(
                    "SELECT * FROM agent_work_entity_relations WHERE id = ?",
                    (relation_id,),
                ).fetchone()
            conn.commit()
        return {
            "id": existing["id"],
            "session_id": existing["session_id"],
            "source_item_id": existing["source_item_id"],
            "target_item_id": existing["target_item_id"],
            "relationship_type": existing["relationship_type"],
            "metadata": self._json_load(existing["metadata_json"]),
            "agent_task_id": existing["agent_task_id"],
            "created_at": existing["created_at"],
        }

    async def get_relations(
        self,
        *,
        session_id: str,
        item_id: str,
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_work_entity_relations
                WHERE session_id = ?
                  AND (source_item_id = ? OR target_item_id = ?)
                ORDER BY created_at, id
                """,
                (session_id, item_id, item_id),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "source_item_id": row["source_item_id"],
                "target_item_id": row["target_item_id"],
                "relationship_type": row["relationship_type"],
                "metadata": self._json_load(row["metadata_json"]),
                "agent_task_id": row["agent_task_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
