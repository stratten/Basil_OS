"""SQLite-backed ambient suggestion store."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.core.services.file_storage_service import StorageService

from .models import AmbientRecentSuggestionContext, AmbientSuggestionPayload, AmbientSuggestionRecord, SuggestionOutcome


class AmbientSuggestionStore:
    """Persist suggestion cards and outcome-based suppression state."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or StorageService(development_mode=True).get_db_path()
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = get_sync_connection(self.db_path, ensure_schema=False, operation_name="ambient_suggestion_write")
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ambient_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    content_fingerprint TEXT NOT NULL,
                    source_identifier TEXT,
                    app_name TEXT NOT NULL,
                    window_title TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    suggestion_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT,
                    proposed_request TEXT,
                    instruction TEXT NOT NULL,
                    context_text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    auto_execute_eligible INTEGER NOT NULL DEFAULT 0,
                    raw_payload TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "ambient_suggestions", "proposed_request", "TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ambient_suggestions_context
                ON ambient_suggestions(content_fingerprint, suggestion_type, capability, created_at)
                """
            )
            conn.commit()

    def should_suppress(
        self,
        *,
        content_fingerprint: str,
        suggestion_type: str,
        capability: str,
        cooldown_minutes: float,
    ) -> bool:
        cutoff = datetime.now() - timedelta(minutes=cooldown_minutes)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT outcome, created_at FROM ambient_suggestions
                WHERE content_fingerprint = ?
                  AND suggestion_type = ?
                  AND capability = ?
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (content_fingerprint, suggestion_type, capability, cutoff.isoformat()),
            ).fetchone()
        if not row:
            return False
        return row["outcome"] in {"suggested", "accepted", "rejected", "dismissed", "auto_executed"}

    def create_suggestion(
        self,
        *,
        app_name: str,
        window_title: str,
        content_fingerprint: str,
        source_identifier: Optional[str],
        payload: AmbientSuggestionPayload,
    ) -> AmbientSuggestionRecord:
        if not payload.capability or not payload.instruction or not payload.context_text:
            raise ValueError("Suggestion payload is missing capability, instruction, or context_text")

        record = AmbientSuggestionRecord(
            suggestion_id=str(uuid.uuid4()),
            created_at=datetime.now(),
            content_fingerprint=content_fingerprint,
            source_identifier=source_identifier,
            app_name=app_name,
            window_title=window_title,
            capability=payload.capability,
            suggestion_type=payload.suggestion_type,
            title=payload.title,
            summary=payload.summary,
            details=payload.details,
            proposed_request=payload.proposed_request or payload.instruction,
            instruction=payload.instruction,
            context_text=payload.context_text,
            confidence=payload.confidence,
            outcome="suggested",
            auto_execute_eligible=payload.auto_execute_eligible,
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ambient_suggestions (
                    suggestion_id, created_at, content_fingerprint, source_identifier,
                    app_name, window_title, capability, suggestion_type, title, summary,
                    details, proposed_request, instruction, context_text, confidence, outcome,
                    auto_execute_eligible, raw_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.suggestion_id,
                    record.created_at.isoformat(),
                    record.content_fingerprint,
                    record.source_identifier,
                    record.app_name,
                    record.window_title,
                    record.capability,
                    record.suggestion_type,
                    record.title,
                    record.summary,
                    record.details,
                    record.proposed_request,
                    record.instruction,
                    record.context_text,
                    record.confidence,
                    record.outcome,
                    1 if record.auto_execute_eligible else 0,
                    payload.model_dump_json(),
                ),
            )
            conn.commit()
        return record

    def update_outcome(self, suggestion_id: str, outcome: SuggestionOutcome) -> Optional[AmbientSuggestionRecord]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE ambient_suggestions SET outcome = ? WHERE suggestion_id = ?",
                (outcome, suggestion_id),
            )
            conn.commit()
        return self.get_suggestion(suggestion_id)

    def get_suggestion(self, suggestion_id: str) -> Optional[AmbientSuggestionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ambient_suggestions WHERE suggestion_id = ?",
                (suggestion_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_open_suggestions(self, limit: int = 20) -> List[AmbientSuggestionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ambient_suggestions
                WHERE outcome = 'suggested'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_recent_suggestion_context(
        self,
        *,
        content_fingerprint: str,
        app_name: str,
        window_title: str,
        cooldown_minutes: float,
        lookback_minutes: float,
        limit: int = 10,
    ) -> List[AmbientRecentSuggestionContext]:
        limit = max(1, limit)
        now = datetime.now()
        cooldown_cutoff = now - timedelta(minutes=cooldown_minutes)
        lookback_cutoff = now - timedelta(minutes=lookback_minutes)
        rows_by_id: dict[str, sqlite3.Row] = {}

        with self._connect() as conn:
            query_buckets = [
                (
                    """
                    SELECT * FROM ambient_suggestions
                    WHERE content_fingerprint = ?
                      AND created_at >= ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (content_fingerprint, cooldown_cutoff.isoformat(), limit),
                ),
                (
                    """
                    SELECT * FROM ambient_suggestions
                    WHERE app_name = ?
                      AND window_title = ?
                      AND created_at >= ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (app_name, window_title, lookback_cutoff.isoformat(), limit),
                ),
                (
                    """
                    SELECT * FROM ambient_suggestions
                    WHERE created_at >= ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (lookback_cutoff.isoformat(), limit),
                ),
            ]
            for query, params in query_buckets:
                for row in conn.execute(query, params).fetchall():
                    rows_by_id.setdefault(row["suggestion_id"], row)

        records = [self._row_to_record(row) for row in rows_by_id.values()]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return [self._record_to_recent_context(record) for record in records[:limit]]

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> AmbientSuggestionRecord:
        return AmbientSuggestionRecord(
            suggestion_id=row["suggestion_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            content_fingerprint=row["content_fingerprint"],
            source_identifier=row["source_identifier"],
            app_name=row["app_name"],
            window_title=row["window_title"],
            capability=row["capability"],
            suggestion_type=row["suggestion_type"],
            title=row["title"],
            summary=row["summary"],
            details=row["details"],
            proposed_request=row["proposed_request"] or row["instruction"],
            instruction=row["instruction"],
            context_text=row["context_text"],
            confidence=float(row["confidence"]),
            outcome=row["outcome"],
            auto_execute_eligible=bool(row["auto_execute_eligible"]),
        )

    @staticmethod
    def _record_to_recent_context(record: AmbientSuggestionRecord) -> AmbientRecentSuggestionContext:
        return AmbientRecentSuggestionContext(
            created_at=record.created_at,
            outcome=record.outcome,
            application=record.app_name,
            window_title=record.window_title,
            content_fingerprint=record.content_fingerprint,
            capability=record.capability,
            suggestion_type=record.suggestion_type,
            title=record.title,
            summary=record.summary,
            proposed_request=record.proposed_request,
        )
