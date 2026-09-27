"""User profile management operations."""

import aiosqlite
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from ..personalization_models import (
    UserProfile,
    UserProfileCreate
)
from ..sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
)

logger = logging.getLogger(__name__)


class ProfileManager:
    """Manages user profile data."""
    
    def __init__(self, db_path: str):
        """Initialize the profile manager.
        
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
    
    async def get_user_profile(self, user_id: str = "default") -> Optional[UserProfile]:
        """Get user profile by ID."""
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM user_profile WHERE id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return UserProfile(
                    id=row["id"],
                    full_name=row["full_name"],
                    preferred_name=row["preferred_name"],
                    email=row["email"],
                    job_title=row["job_title"],
                    company_name=row["company_name"],
                    industry=row["industry"],
                    default_formality=row["default_formality"],
                    default_tone=row["default_tone"],
                    custom_instructions=row["custom_instructions"],
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.utcnow(),
                    updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.utcnow(),
                    profile_version=row["profile_version"]
                )
            return None

    async def create_or_update_user_profile(
        self,
        profile_data: UserProfileCreate,
        user_id: str = "default"
    ) -> UserProfile:
        """Create or update user profile."""
        async with self._get_connection() as conn:
            existing = await self.get_user_profile(user_id)
            now = datetime.utcnow().isoformat() + "Z"
            if existing:
                await conn.execute(
                    """
                    UPDATE user_profile 
                    SET full_name = ?, preferred_name = ?, email = ?, job_title = ?,
                        company_name = ?, industry = ?, default_formality = ?,
                        default_tone = ?, custom_instructions = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        profile_data.full_name, profile_data.preferred_name, profile_data.email,
                        profile_data.job_title, profile_data.company_name, profile_data.industry,
                        profile_data.default_formality, profile_data.default_tone,
                        profile_data.custom_instructions, now, user_id
                    )
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO user_profile (
                        id, full_name, preferred_name, email, job_title,
                        company_name, industry, default_formality, default_tone,
                        custom_instructions, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, profile_data.full_name, profile_data.preferred_name, profile_data.email,
                        profile_data.job_title, profile_data.company_name, profile_data.industry,
                        profile_data.default_formality, profile_data.default_tone,
                        profile_data.custom_instructions, now, now
                    )
                )
            await conn.commit()
            result = await self.get_user_profile(user_id)
            if result is None:
                raise RuntimeError("Failed to retrieve profile after create/update")
            return result

