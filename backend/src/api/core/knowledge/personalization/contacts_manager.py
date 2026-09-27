"""Contact relationships management operations."""

import uuid
import json
import aiosqlite
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from ..personalization_models import (
    ContactRelationship,
    RelationshipType,
    FormalityLevel
)
from ..sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
)
from .contact_context import normalize_email_address

logger = logging.getLogger(__name__)


class ContactsManager:
    """Manages contact relationships and interaction tracking."""
    
    def __init__(self, db_path: str):
        """Initialize the contacts manager.
        
        Args:
            db_path: Path to knowledge database
        """
        self.db_path = db_path

    def _row_to_contact(self, row: aiosqlite.Row) -> ContactRelationship:
        """Convert a contact_relationships row into a ContactRelationship model."""
        common_topics = json.loads(row["common_topics"]) if row["common_topics"] else []
        return ContactRelationship(
            id=row["id"],
            user_id=row["user_id"],
            contact_name=row["contact_name"],
            contact_email=row["contact_email"],
            contact_company=row["contact_company"],
            relationship_type=RelationshipType(row["relationship_type"]),
            formality_level=FormalityLevel(row["formality_level"]),
            message_count=row["message_count"],
            last_contact_date=datetime.fromisoformat(row["last_contact_date"]) if row["last_contact_date"] else None,
            typical_response_time_hours=row["typical_response_time_hours"],
            common_topics=common_topics,
            notes=row["notes"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
    
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
    
    async def get_or_create_contact(
        self,
        contact_email: str,
        contact_name: Optional[str] = None,
        user_id: str = "default",
        contact_company: Optional[str] = None
    ) -> ContactRelationship:
        """Get existing contact or create new one.
        
        Args:
            contact_email: Contact's email address
            contact_name: Contact's name
            user_id: User ID
            contact_company: Optional company, only applied when creating a new
                contact (never overwrites an existing learned contact)
            
        Returns:
            ContactRelationship
        """
        normalized_email = normalize_email_address(contact_email)
        if not normalized_email:
            raise ValueError(f"Invalid contact email: {contact_email}")

        async with self._get_connection() as conn:
            # Try to find existing
            cursor = await conn.execute(
                """
                SELECT * FROM contact_relationships 
                WHERE user_id = ? AND contact_email = ?
                """,
                (user_id, normalized_email)
            )
            row = await cursor.fetchone()
            
            if row:
                return self._row_to_contact(row)
            
            # Create new contact
            contact_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat() + "Z"
            
            await conn.execute(
                """
                INSERT INTO contact_relationships (
                    id, user_id, contact_name, contact_email, contact_company,
                    relationship_type, formality_level, message_count,
                    common_topics, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact_id,
                    user_id,
                    contact_name,
                    normalized_email,
                    contact_company,
                    RelationshipType.UNKNOWN.value,
                    FormalityLevel.PROFESSIONAL.value,
                    0,
                    json.dumps([]),
                    now,
                    now
                )
            )
            
            await conn.commit()
            logger.info(f"Created new contact relationship for {normalized_email}")
            
            return await self.get_or_create_contact(normalized_email, contact_name, user_id)

    async def get_contact_by_email(
        self,
        contact_email: str,
        user_id: str = "default"
    ) -> Optional[ContactRelationship]:
        """Get an existing contact without creating a new relationship record."""
        normalized_email = normalize_email_address(contact_email)
        if not normalized_email:
            return None

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM contact_relationships
                WHERE user_id = ? AND contact_email = ?
                """,
                (user_id, normalized_email)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_contact(row)
    
    async def update_contact_interaction(
        self,
        contact_email: str,
        user_id: str = "default"
    ) -> None:
        """Update contact interaction count and last contact date.
        
        Args:
            contact_email: Contact's email
            user_id: User ID
        """
        normalized_email = normalize_email_address(contact_email)
        if not normalized_email:
            raise ValueError(f"Invalid contact email: {contact_email}")

        async with self._get_connection() as conn:
            now = datetime.utcnow().isoformat() + "Z"
            await conn.execute(
                """
                UPDATE contact_relationships 
                SET message_count = message_count + 1,
                    last_contact_date = ?,
                    updated_at = ?
                WHERE user_id = ? AND contact_email = ?
                """,
                (now, now, user_id, normalized_email)
            )
            await conn.commit()

