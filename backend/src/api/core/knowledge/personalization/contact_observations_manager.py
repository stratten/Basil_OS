"""Read/upsert operations for contact identity observations.

Observations are unverified, screen-derived candidate identity facts produced
by Activity Capture post-processing. They are intentionally stored separately
from ``contact_relationships`` and must never by themselves assert a
relationship. This manager only persists directly observed identity fields and
extraction provenance, and exposes read helpers used for transient generation
enrichment and explicit promotion.
"""

import uuid
import logging
import aiosqlite
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager

from ..personalization_models import (
    ContactIdentityObservation,
    ContactIdentityObservationCreate,
    ObservationSourceType,
)
from ..sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
)
from .contact_context import normalize_email_address

logger = logging.getLogger(__name__)


class ContactObservationsManager:
    """Manages persistence and retrieval of contact identity observations."""

    def __init__(self, db_path: str):
        """Initialize the observations manager.

        Args:
            db_path: Path to the knowledge database.
        """
        self.db_path = db_path

    @asynccontextmanager
    async def _get_connection(self):
        """Get an async database connection."""
        conn = await get_async_connection(
            self.db_path, ensure_schema=False, foreign_keys=False
        )
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    def _row_to_observation(self, row: aiosqlite.Row) -> ContactIdentityObservation:
        """Convert a contact_identity_observations row into a model."""
        return ContactIdentityObservation(
            id=row["id"],
            user_id=row["user_id"],
            source_type=ObservationSourceType(row["source_type"]),
            source_activity_id=row["source_activity_id"],
            source_app_name=row["source_app_name"],
            source_window_title=row["source_window_title"],
            normalized_email=row["normalized_email"],
            display_name=row["display_name"],
            organization_name=row["organization_name"],
            job_title=row["job_title"],
            relationship_hint=row["relationship_hint"],
            confidence=row["confidence"] if row["confidence"] is not None else 0.0,
            reason=row["reason"],
            raw_evidence=row["raw_evidence"],
            occurrence_count=row["occurrence_count"] if row["occurrence_count"] is not None else 1,
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )

    async def record_observation(
        self,
        observation: ContactIdentityObservationCreate,
        user_id: str = "default",
    ) -> Optional[ContactIdentityObservation]:
        """Upsert a candidate identity observation.

        Upserts by ``(user_id, normalized_email, source_app_name)`` so repeated
        captures of the same person in the same app aggregate rather than
        duplicating. On match, occurrence_count is incremented, last_seen_at is
        refreshed, confidence is raised to the max observed, and identity fields
        are filled in when the new observation supplies a value.

        Returns the stored observation, or ``None`` if the email is invalid.
        """
        normalized_email = normalize_email_address(observation.normalized_email)
        if not normalized_email:
            logger.debug("Skipping observation with invalid email: %r", observation.normalized_email)
            return None

        source_type_value = (
            observation.source_type.value
            if isinstance(observation.source_type, ObservationSourceType)
            else str(observation.source_type)
        )

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM contact_identity_observations
                WHERE user_id = ?
                  AND normalized_email = ?
                  AND IFNULL(source_app_name, '') = IFNULL(?, '')
                """,
                (user_id, normalized_email, observation.source_app_name),
            )
            existing = await cursor.fetchone()
            now = datetime.utcnow().isoformat()

            if existing:
                new_confidence = max(
                    existing["confidence"] if existing["confidence"] is not None else 0.0,
                    observation.confidence,
                )
                await conn.execute(
                    """
                    UPDATE contact_identity_observations
                    SET occurrence_count = occurrence_count + 1,
                        last_seen_at = ?,
                        confidence = ?,
                        display_name = COALESCE(?, display_name),
                        organization_name = COALESCE(?, organization_name),
                        job_title = COALESCE(?, job_title),
                        relationship_hint = COALESCE(?, relationship_hint),
                        source_activity_id = COALESCE(?, source_activity_id),
                        source_window_title = COALESCE(?, source_window_title),
                        reason = COALESCE(?, reason),
                        raw_evidence = COALESCE(?, raw_evidence)
                    WHERE id = ?
                    """,
                    (
                        now,
                        new_confidence,
                        observation.display_name,
                        observation.organization_name,
                        observation.job_title,
                        observation.relationship_hint,
                        observation.source_activity_id,
                        observation.source_window_title,
                        observation.reason,
                        observation.raw_evidence,
                        existing["id"],
                    ),
                )
                await conn.commit()
                cursor = await conn.execute(
                    "SELECT * FROM contact_identity_observations WHERE id = ?",
                    (existing["id"],),
                )
                row = await cursor.fetchone()
                return self._row_to_observation(row)

            observation_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO contact_identity_observations (
                    id, user_id, source_type, source_activity_id, source_app_name,
                    source_window_title, normalized_email, display_name,
                    organization_name, job_title, relationship_hint, confidence,
                    reason, raw_evidence, occurrence_count, created_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    user_id,
                    source_type_value,
                    observation.source_activity_id,
                    observation.source_app_name,
                    observation.source_window_title,
                    normalized_email,
                    observation.display_name,
                    observation.organization_name,
                    observation.job_title,
                    observation.relationship_hint,
                    observation.confidence,
                    observation.reason,
                    observation.raw_evidence,
                    1,
                    now,
                    now,
                ),
            )
            await conn.commit()
            cursor = await conn.execute(
                "SELECT * FROM contact_identity_observations WHERE id = ?",
                (observation_id,),
            )
            row = await cursor.fetchone()
            logger.info(
                "Recorded contact identity observation for %s (confidence=%.2f)",
                normalized_email,
                observation.confidence,
            )
            return self._row_to_observation(row)

    async def get_observations_for_email(
        self,
        contact_email: str,
        user_id: str = "default",
        min_confidence: float = 0.0,
    ) -> List[ContactIdentityObservation]:
        """Return observations for an email ordered by confidence then recency."""
        normalized_email = normalize_email_address(contact_email)
        if not normalized_email:
            return []

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM contact_identity_observations
                WHERE user_id = ?
                  AND normalized_email = ?
                  AND confidence >= ?
                ORDER BY confidence DESC, occurrence_count DESC, last_seen_at DESC
                """,
                (user_id, normalized_email, min_confidence),
            )
            rows = await cursor.fetchall()
            return [self._row_to_observation(row) for row in rows]

    async def get_best_observation_for_email(
        self,
        contact_email: str,
        user_id: str = "default",
        min_confidence: float = 0.0,
    ) -> Optional[ContactIdentityObservation]:
        """Return the single highest-confidence observation for an email."""
        observations = await self.get_observations_for_email(
            contact_email, user_id=user_id, min_confidence=min_confidence
        )
        return observations[0] if observations else None
