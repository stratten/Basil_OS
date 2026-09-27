"""Writing samples management operations."""

import uuid
import hashlib
import aiosqlite
import logging
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from ..personalization_models import (
    WritingSample,
    ContextType,
    SourceType,
    RelationshipType
)
from ..sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
)

logger = logging.getLogger(__name__)


def _source_type_from_database_value(source_type_value: str) -> SourceType:
    """Convert persisted source_type values into the current SourceType enum."""
    if source_type_value == "voice_suggestion_accepted":
        return SourceType.SUGGESTION_ACCEPTED
    return SourceType(source_type_value)


class WritingSamplesManager:
    """Manages writing samples storage and retrieval."""
    
    def __init__(self, db_path: str):
        """Initialize the writing samples manager.
        
        Args:
            db_path: Path to knowledge database
        """
        self.db_path = db_path
    
    @asynccontextmanager
    async def _get_connection(self):
        """Get async database connection."""
        conn = await get_async_connection(
            self.db_path, ensure_schema=False, foreign_keys=False
        )
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()
    
    async def add_writing_sample(
        self,
        content: str,
        source_type: SourceType,
        context_type: ContextType,
        app_name: Optional[str] = None,
        recipient: Optional[str] = None,
        subject: Optional[str] = None,
        relationship_type: Optional[RelationshipType] = None,
        was_edited: bool = False,
        edit_distance: Optional[int] = None,
        user_id: str = "default"
    ) -> WritingSample:
        """Add a writing sample.
        
        User explicitly saving a sample is the quality endorsement - no scoring needed.
        
        Args:
            content: The writing content
            source_type: Source of the sample
            context_type: Context type
            app_name: Application name
            recipient: Recipient email/name if applicable
            subject: Email subject if applicable
            relationship_type: Type of relationship
            was_edited: Whether it was edited
            edit_distance: Edit distance if edited
            user_id: User ID
            
        Returns:
            Created WritingSample
        """
        # Generate content hash for deduplication
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        # Check for duplicates
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM writing_samples WHERE content_hash = ?",
                (content_hash,)
            )
            existing = await cursor.fetchone()
            if existing:
                logger.info(f"Writing sample with hash {content_hash[:8]}... already exists, skipping")
                return await self._get_writing_sample_by_id(existing["id"])
            
            # Create new sample
            sample_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat() + "Z"
            
            await conn.execute(
                """
                INSERT INTO writing_samples (
                    id, user_id, source_type, context_type, app_name,
                    content, content_hash, recipient, subject, relationship_type,
                    was_edited, edit_distance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample_id,
                    user_id,
                    source_type.value,
                    context_type.value,
                    app_name,
                    content,
                    content_hash,
                    recipient,
                    subject,
                    relationship_type.value if relationship_type else None,
                    was_edited,
                    edit_distance,
                    now
                )
            )
            
            await conn.commit()
            logger.info(f"Created writing sample {sample_id} from {source_type.value}")
            
            return await self._get_writing_sample_by_id(sample_id)
    
    async def _get_writing_sample_by_id(self, sample_id: str) -> WritingSample:
        """Get writing sample by ID."""
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM writing_samples WHERE id = ?",
                (sample_id,)
            )
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Writing sample {sample_id} not found")
            
            return WritingSample(
                id=row["id"],
                user_id=row["user_id"],
                source_type=_source_type_from_database_value(row["source_type"]),
                context_type=ContextType(row["context_type"]),
                app_name=row["app_name"],
                content=row["content"],
                content_hash=row["content_hash"],
                recipient=row["recipient"],
                subject=row["subject"],
                relationship_type=RelationshipType(row["relationship_type"]) if row["relationship_type"] else None,
                was_edited=bool(row["was_edited"]),
                edit_distance=row["edit_distance"],
                created_at=datetime.fromisoformat(row["created_at"])
            )
    
    async def get_relevant_writing_samples(
        self,
        context_type: ContextType,
        recipient: Optional[str] = None,
        app_name: Optional[str] = None,
        limit: int = 3,
        user_id: str = "default"
    ) -> List[WritingSample]:
        """Get most relevant writing samples for context.
        
        Samples are user-curated (explicitly saved), so all are considered
        high quality. Selection strategy:
        
        1. Always match context_type (email_reply, social_media, document, etc.)
        2. Prioritize app_name match (Slack vs Mail vs Messages) - critical for platform-specific tone
        3. Prioritize recipient match (when available) - for relationship-specific communication
        4. Fall back to recency
        
        This approach works across:
        - Email (recipient-based: sarah@company.com)
        - Slack/Discord (app-based: channel/DM context matters more than individual)
        - Documents (app-based: Google Docs vs Notion have different styles)
        - Social Media (app-based: Twitter vs LinkedIn have very different tones)
        
        Args:
            context_type: Context type to match (required)
            recipient: Optional recipient to prioritize (email address, Slack user, etc.)
            app_name: Optional app name to prioritize (Slack, Mail, Discord, etc.)
            limit: Maximum number of samples
            user_id: User ID
            
        Returns:
            List of relevant writing samples, ordered by relevance
        """
        async with self._get_connection() as conn:
            # Build dynamic query based on available context
            if app_name and recipient:
                # Best case: match both app and recipient
                cursor = await conn.execute(
                    """
                    SELECT * FROM writing_samples 
                    WHERE user_id = ? AND context_type = ?
                    ORDER BY 
                      CASE WHEN app_name = ? AND recipient = ? THEN 0
                           WHEN app_name = ? THEN 1
                           WHEN recipient = ? THEN 2
                           ELSE 3 END,
                      created_at DESC
                    LIMIT ?
                    """,
                    (user_id, context_type.value, app_name, recipient, app_name, recipient, limit)
                )
            elif app_name:
                # App-specific samples (Slack, Discord, Google Docs, etc.)
                cursor = await conn.execute(
                    """
                    SELECT * FROM writing_samples 
                    WHERE user_id = ? AND context_type = ?
                    ORDER BY 
                      CASE WHEN app_name = ? THEN 0 ELSE 1 END,
                      created_at DESC
                    LIMIT ?
                    """,
                    (user_id, context_type.value, app_name, limit)
                )
            elif recipient:
                # Recipient-specific samples (email, DMs)
                cursor = await conn.execute(
                    """
                    SELECT * FROM writing_samples 
                    WHERE user_id = ? AND context_type = ?
                    ORDER BY 
                      CASE WHEN recipient = ? THEN 0 ELSE 1 END,
                      created_at DESC
                    LIMIT ?
                    """,
                    (user_id, context_type.value, recipient, limit)
                )
            else:
                # Generic samples for this context type
                cursor = await conn.execute(
                    """
                    SELECT * FROM writing_samples 
                    WHERE user_id = ? AND context_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, context_type.value, limit)
                )
            
            rows = await cursor.fetchall()
            samples = []
            for row in rows:
                samples.append(WritingSample(
                    id=row["id"],
                    user_id=row["user_id"],
                    source_type=_source_type_from_database_value(row["source_type"]),
                    context_type=ContextType(row["context_type"]),
                    app_name=row["app_name"],
                    content=row["content"],
                    content_hash=row["content_hash"],
                    recipient=row["recipient"],
                    subject=row["subject"],
                    relationship_type=RelationshipType(row["relationship_type"]) if row["relationship_type"] else None,
                    was_edited=bool(row["was_edited"]),
                    edit_distance=row["edit_distance"],
                    created_at=datetime.fromisoformat(row["created_at"])
                ))
            
            return samples
    
    async def get_writing_samples_count(
        self,
        context_type: Optional[ContextType] = None,
        user_id: str = "default"
    ) -> int:
        """Get count of writing samples.
        
        Args:
            context_type: Optional filter by context type
            user_id: User ID
            
        Returns:
            Count of writing samples
        """
        async with self._get_connection() as conn:
            if context_type:
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM writing_samples WHERE user_id = ? AND context_type = ?",
                    (user_id, context_type.value)
                )
            else:
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM writing_samples WHERE user_id = ?",
                    (user_id,)
                )
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def list_writing_samples(
        self,
        context_type: Optional[ContextType] = None,
        limit: int = 50,
        offset: int = 0,
        user_id: str = "default"
    ) -> List[WritingSample]:
        """List writing samples with pagination.
        
        Args:
            context_type: Optional filter by context type
            limit: Maximum number of samples to return
            offset: Number of samples to skip
            user_id: User ID
            
        Returns:
            List of writing samples
        """
        async with self._get_connection() as conn:
            if context_type:
                cursor = await conn.execute(
                    """
                    SELECT * FROM writing_samples 
                    WHERE user_id = ? AND context_type = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, context_type.value, limit, offset)
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT * FROM writing_samples 
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, limit, offset)
                )
            
            rows = await cursor.fetchall()
            samples = []
            for row in rows:
                samples.append(WritingSample(
                    id=row["id"],
                    user_id=row["user_id"],
                    source_type=_source_type_from_database_value(row["source_type"]),
                    context_type=ContextType(row["context_type"]),
                    app_name=row["app_name"],
                    content=row["content"],
                    content_hash=row["content_hash"],
                    recipient=row["recipient"],
                    subject=row["subject"],
                    relationship_type=RelationshipType(row["relationship_type"]) if row["relationship_type"] else None,
                    was_edited=bool(row["was_edited"]),
                    edit_distance=row["edit_distance"],
                    created_at=datetime.fromisoformat(row["created_at"])
                ))
            
            return samples
    
    async def delete_writing_sample(
        self,
        sample_id: str,
        user_id: str = "default"
    ) -> bool:
        """Delete a specific writing sample.
        
        Args:
            sample_id: Sample ID to delete
            user_id: User ID
            
        Returns:
            True if deleted, False if not found
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM writing_samples WHERE id = ? AND user_id = ?",
                (sample_id, user_id)
            )
            await conn.commit()
            return cursor.rowcount > 0
    
    async def delete_all_writing_samples(
        self,
        context_type: Optional[ContextType] = None,
        user_id: str = "default"
    ) -> int:
        """Delete all writing samples, optionally filtered by context type.
        
        Args:
            context_type: Optional filter by context type
            user_id: User ID
            
        Returns:
            Number of samples deleted
        """
        async with self._get_connection() as conn:
            if context_type:
                cursor = await conn.execute(
                    "DELETE FROM writing_samples WHERE user_id = ? AND context_type = ?",
                    (user_id, context_type.value)
                )
            else:
                cursor = await conn.execute(
                    "DELETE FROM writing_samples WHERE user_id = ?",
                    (user_id,)
                )
            await conn.commit()
            return cursor.rowcount

