"""User signatures management operations."""

import uuid
import aiosqlite
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from ..personalization_models import UserSignature
from ..sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
)

logger = logging.getLogger(__name__)


class SignaturesManager:
    """Manages user email signatures storage and retrieval."""
    
    def __init__(self, db_path: str):
        """Initialize the signatures manager.
        
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
    
    async def add_or_update_signature(
        self,
        signature_text: str,
        context: str = "default",
        signature_html: Optional[str] = None,
        user_id: str = "default"
    ) -> UserSignature:
        """Add or update a user signature.
        
        Args:
            signature_text: Signature text
            context: Context (work, personal, etc.)
            signature_html: HTML version if available
            user_id: User ID
            
        Returns:
            UserSignature
        """
        async with self._get_connection() as conn:
            # Check for existing signature with same text
            cursor = await conn.execute(
                """
                SELECT * FROM user_signatures 
                WHERE user_id = ? AND signature_text = ?
                """,
                (user_id, signature_text)
            )
            row = await cursor.fetchone()
            
            now = datetime.utcnow().isoformat() + "Z"
            
            if row:
                # Update occurrence count and last seen
                await conn.execute(
                    """
                    UPDATE user_signatures 
                    SET occurrence_count = occurrence_count + 1,
                        last_seen = ?
                    WHERE id = ?
                    """,
                    (now, row["id"])
                )
                await conn.commit()
                return UserSignature(
                    id=row["id"],
                    user_id=row["user_id"],
                    signature_text=row["signature_text"],
                    signature_html=row["signature_html"],
                    context=row["context"],
                    is_primary=bool(row["is_primary"]),
                    first_seen=datetime.fromisoformat(row["first_seen"]),
                    last_seen=datetime.fromisoformat(now),
                    occurrence_count=row["occurrence_count"] + 1,
                    confidence=row["confidence"]
                )
            
            # Create new signature
            sig_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO user_signatures (
                    id, user_id, signature_text, signature_html,
                    context, is_primary, first_seen, last_seen,
                    occurrence_count, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sig_id,
                    user_id,
                    signature_text,
                    signature_html,
                    context,
                    False,  # Not primary by default
                    now,
                    now,
                    1,
                    1.0
                )
            )
            await conn.commit()
            
            return UserSignature(
                id=sig_id,
                user_id=user_id,
                signature_text=signature_text,
                signature_html=signature_html,
                context=context,
                is_primary=False,
                first_seen=datetime.fromisoformat(now),
                last_seen=datetime.fromisoformat(now),
                occurrence_count=1,
                confidence=1.0
            )
    
    async def get_primary_signature(
        self,
        context: str = "default",
        user_id: str = "default"
    ) -> Optional[UserSignature]:
        """Get primary signature for context.
        
        Args:
            context: Context (work, personal, etc.)
            user_id: User ID
            
        Returns:
            UserSignature if found, None otherwise
        """
        async with self._get_connection() as conn:
            # Try to get marked primary signature
            cursor = await conn.execute(
                """
                SELECT * FROM user_signatures 
                WHERE user_id = ? AND context = ? AND is_primary = 1
                ORDER BY last_seen DESC LIMIT 1
                """,
                (user_id, context)
            )
            row = await cursor.fetchone()
            
            if not row:
                # Fall back to most frequently used
                cursor = await conn.execute(
                    """
                    SELECT * FROM user_signatures 
                    WHERE user_id = ? AND context = ?
                    ORDER BY occurrence_count DESC, last_seen DESC LIMIT 1
                    """,
                    (user_id, context)
                )
                row = await cursor.fetchone()
            
            if row:
                return UserSignature(
                    id=row["id"],
                    user_id=row["user_id"],
                    signature_text=row["signature_text"],
                    signature_html=row["signature_html"],
                    context=row["context"],
                    is_primary=bool(row["is_primary"]),
                    first_seen=datetime.fromisoformat(row["first_seen"]),
                    last_seen=datetime.fromisoformat(row["last_seen"]),
                    occurrence_count=row["occurrence_count"],
                    confidence=row["confidence"]
                )
            return None

