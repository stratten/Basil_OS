"""Shared persistence and query service for AssistantSession history.

Handles storing, listing, searching, retrieving, and deleting AssistantSession
outputs (and legacy 'regular'/'activity' rows persisted to the same
``assistant_outputs`` table) in SQLite.

The table ``assistant_outputs`` is the renamed-on-startup successor to
the legacy ``suggestions`` table; column ``output_text`` is the renamed
``suggestion_text`` and ``output_type`` is the renamed ``type``. The
new ``input_modality`` column carries 'voice', 'text', or NULL for
AssistantSession rows.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)

logger = logging.getLogger(__name__)


class AssistantOutputHistoryService:
    """Provides CRUD operations on the assistant_outputs table for history features."""

    def __init__(self, sqlite_knowledge_service):
        self.db = sqlite_knowledge_service
        self._db_path = sqlite_knowledge_service.db_path

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------

    async def persist_assistant_output(
        self,
        output_text: str,
        output_type: str = "regular",
        input_modality: Optional[str] = None,
        context_text: Optional[str] = None,
        explanation_text: Optional[str] = None,
        model_name: Optional[str] = None,
        screen_capture_path: Optional[str] = None,
        text_selection: Optional[str] = None,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        user_request: Optional[str] = None,
        processing_time_ms: Optional[int] = None,
        context_type: Optional[str] = None,
        recipient: Optional[str] = None,
    ) -> int:
        """Insert a completed AssistantSession output into the database.

        Args:
            output_text: The model-generated text to persist.
            output_type: 'assistant_session' for AssistantSession-pipeline rows, 'regular'
                or 'activity' for other producers.
            input_modality: 'voice' if the user spoke the request,
                'text' if the user typed it, or None for the
                screen-only / no-request case (and for legacy rows
                whose modality cannot be inferred).
            user_request: The user's original request -- spoken
                transcription for voice modality, typed string for text
                modality, custom prompt for non-AssistantSession rows.

        Returns:
            The new row id.
        """
        with get_sync_connection(self._db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO assistant_outputs (
                    output_text, context_text, explanation_text,
                    model_name, generated_at, user_request,
                    output_type, input_modality, screen_capture_path,
                    text_selection, app_name, window_title,
                    status, refinement_count, processing_time_ms,
                    context_type, recipient
                ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, 'completed', 0, ?, ?, ?)
                """,
                (
                    output_text,
                    context_text,
                    explanation_text,
                    model_name,
                    user_request,
                    output_type,
                    input_modality,
                    screen_capture_path,
                    text_selection,
                    app_name,
                    window_title,
                    processing_time_ms,
                    context_type,
                    recipient,
                ),
            )
            assistant_output_id = cursor.lastrowid
            conn.commit()

        logger.info(
            f"Persisted {output_type} assistant_output id={assistant_output_id} "
            f"(modality={input_modality or 'n/a'}, "
            f"request={user_request[:40] if user_request else 'N/A'}...)"
        )
        return assistant_output_id

    # ------------------------------------------------------------------
    # Update refinement
    # ------------------------------------------------------------------

    async def update_refinement(
        self,
        assistant_output_id: int,
        instruction: str,
        output: str,
    ) -> None:
        """Append a refinement entry to the row's refinements JSON array."""
        with get_sync_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT refinements, refinement_count FROM assistant_outputs WHERE id = ?",
                (assistant_output_id,),
            ).fetchone()
            if not row:
                logger.warning(f"AssistantSession output {assistant_output_id} not found for refinement update")
                return

            existing = json.loads(row["refinements"]) if row["refinements"] else []
            existing.append(
                {
                    "instruction": instruction,
                    "output": output,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            new_count = (row["refinement_count"] or 0) + 1

            conn.execute(
                "UPDATE assistant_outputs SET refinements = ?, refinement_count = ? WHERE id = ?",
                (json.dumps(existing), new_count, assistant_output_id),
            )
            conn.commit()

        logger.info(f"Updated refinement #{new_count} for assistant_output {assistant_output_id}")

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_assistant_outputs(
        self,
        input_modality_filter: Optional[str] = None,
        output_type_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Return recent AssistantSession outputs, newest first.

        Filters compose with AND. ``input_modality_filter`` matches
        the new modality column ('voice' | 'text'); ``output_type_filter``
        matches the row category ('assistant_session' | 'regular' | 'activity').

        Returns dict with keys: outputs (list), total_count (int), has_more (bool).
        """
        with get_sync_connection(self._db_path) as conn:
            where_parts = []
            params: list = []
            if input_modality_filter:
                where_parts.append("input_modality = ?")
                params.append(input_modality_filter)
            if output_type_filter:
                where_parts.append("output_type = ?")
                params.append(output_type_filter)
            where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM assistant_outputs {where_clause}", params
            ).fetchone()
            total_count = count_row["cnt"] if count_row else 0

            rows = conn.execute(
                f"""
                SELECT id, output_type, input_modality, output_text, context_text,
                       generated_at, status, refinement_count, app_name,
                       user_request, processing_time_ms
                FROM assistant_outputs
                {where_clause}
                ORDER BY generated_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()

        outputs = [self._row_to_list_item(r) for r in rows]
        return {
            "outputs": outputs,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_assistant_outputs(
        self,
        query: str,
        input_modality_filter: Optional[str] = None,
        output_type_filter: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Full-text search across user_request + output_text."""
        like = f"%{query}%"
        with get_sync_connection(self._db_path) as conn:
            extra_clauses = []
            params: list = [like, like]
            if input_modality_filter:
                extra_clauses.append("AND input_modality = ?")
                params.append(input_modality_filter)
            if output_type_filter:
                extra_clauses.append("AND output_type = ?")
                params.append(output_type_filter)
            extra_clause = " ".join(extra_clauses)
            params.append(limit)

            rows = conn.execute(
                f"""
                SELECT id, output_type, input_modality, output_text, context_text,
                       generated_at, status, refinement_count, app_name,
                       user_request, processing_time_ms
                FROM assistant_outputs
                WHERE (user_request LIKE ? OR output_text LIKE ?)
                {extra_clause}
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        outputs = [self._row_to_list_item(r) for r in rows]
        return {
            "outputs": outputs,
            "total_count": len(outputs),
            "has_more": False,
        }

    # ------------------------------------------------------------------
    # Detail
    # ------------------------------------------------------------------

    async def get_assistant_output_detail(self, assistant_output_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a full row for rehydration."""
        with get_sync_connection(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT id, output_type, input_modality, output_text, context_text,
                       explanation_text, model_name, generated_at, status,
                       refinement_count, refinements, app_name, window_title,
                       screen_capture_path, text_selection, user_request,
                       processing_time_ms, was_inserted, user_rating, user_feedback,
                       context_type, recipient
                FROM assistant_outputs
                WHERE id = ?
                """,
                (assistant_output_id,),
            ).fetchone()

        if not row:
            return None

        refinements = json.loads(row["refinements"]) if row["refinements"] else []
        return {
            "id": row["id"],
            "output_type": row["output_type"] or "regular",
            "input_modality": row["input_modality"],
            "output_text": row["output_text"],
            "context_text": row["context_text"],
            "explanation_text": row["explanation_text"],
            "model_name": row["model_name"],
            "timestamp": row["generated_at"],
            "status": row["status"] or "completed",
            "refinement_count": row["refinement_count"] or 0,
            "refinements": refinements,
            "app_name": row["app_name"],
            "window_title": row["window_title"],
            "screen_capture_path": row["screen_capture_path"],
            "text_selection": row["text_selection"],
            "user_request": row["user_request"],
            "processing_time_ms": row["processing_time_ms"],
            "was_inserted": bool(row["was_inserted"]),
            "user_rating": row["user_rating"],
            "user_feedback": row["user_feedback"],
            "context_type": row["context_type"],
            "recipient": row["recipient"],
        }

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_assistant_output(self, assistant_output_id: int) -> bool:
        """Delete a AssistantSession output by id. Returns True if deleted."""
        with get_sync_connection(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM assistant_outputs WHERE id = ?", (assistant_output_id,)
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"Deleted assistant_output {assistant_output_id}")
        else:
            logger.warning(f"AssistantSession output {assistant_output_id} not found for deletion")
        return deleted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_list_item(row) -> Dict[str, Any]:
        """Convert a database row to a list-item dict for the history sidebar."""
        request_text = row["user_request"] or ""
        title = (request_text[:60] + "...") if len(request_text) > 60 else request_text
        output_preview = row["output_text"] or ""
        output_preview = (
            (output_preview[:120] + "...") if len(output_preview) > 120 else output_preview
        )
        return {
            "id": row["id"],
            "output_type": row["output_type"] or "regular",
            "input_modality": row["input_modality"],
            "title": title,
            "output_preview": output_preview,
            "timestamp": row["generated_at"],
            "status": row["status"] or "completed",
            "refinement_count": row["refinement_count"] or 0,
            "app_name": row["app_name"],
        }
