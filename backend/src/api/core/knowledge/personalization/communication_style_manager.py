"""Communication style profile management operations."""

import json
import uuid
import aiosqlite
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from ..personalization_models import (
    CommunicationStyleProfile,
    StyleAttributes,
    ContextType
)
from ..sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
)
from .style_analyzer import StyleAnalyzer

logger = logging.getLogger(__name__)


class CommunicationStyleManager:
    """Manages communication style profiles for different contexts."""
    
    def __init__(self, db_path: str):
        """Initialize the communication style manager.
        
        Args:
            db_path: Path to knowledge database
        """
        self.db_path = db_path
        self.analyzer = StyleAnalyzer()
    
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
    
    async def get_communication_style(
        self,
        context_type: ContextType,
        user_id: str = "default"
    ) -> Optional[CommunicationStyleProfile]:
        """Get communication style for a specific context.
        
        Args:
            context_type: Context type (email_reply, slack, etc.)
            user_id: User ID
            
        Returns:
            CommunicationStyleProfile if found, None otherwise
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM communication_style_profile 
                WHERE user_id = ? AND context_type = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (user_id, context_type.value)
            )
            row = await cursor.fetchone()
            
            if row:
                style_attrs_dict = json.loads(row["style_attributes"])
                return CommunicationStyleProfile(
                    id=row["id"],
                    user_id=row["user_id"],
                    context_type=ContextType(row["context_type"]),
                    style_attributes=StyleAttributes(**style_attrs_dict),
                    confidence=row["confidence"],
                    sample_count=row["sample_count"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None
                )
            return None
    
    async def save_communication_style(
        self,
        style: CommunicationStyleProfile
    ) -> CommunicationStyleProfile:
        """Save or update communication style profile.
        
        Args:
            style: Communication style profile to save
            
        Returns:
            Saved profile
        """
        async with self._get_connection() as conn:
            now = datetime.utcnow().isoformat() + "Z"
            style_attrs_json = style.style_attributes.model_dump_json()
            
            # Check if exists
            cursor = await conn.execute(
                "SELECT id FROM communication_style_profile WHERE id = ?",
                (style.id,)
            )
            exists = await cursor.fetchone()
            
            if exists:
                # Update
                await conn.execute(
                    """
                    UPDATE communication_style_profile 
                    SET style_attributes = ?,
                        confidence = ?,
                        sample_count = ?,
                        updated_at = ?,
                        last_used_at = ?
                    WHERE id = ?
                    """,
                    (
                        style_attrs_json,
                        style.confidence,
                        style.sample_count,
                        now,
                        style.last_used_at.isoformat() if style.last_used_at else None,
                        style.id
                    )
                )
            else:
                # Insert
                # Handle both ContextType enum and string
                context_type_value = style.context_type.value if hasattr(style.context_type, 'value') else style.context_type
                
                await conn.execute(
                    """
                    INSERT INTO communication_style_profile (
                        id, user_id, context_type, style_attributes,
                        confidence, sample_count, created_at, updated_at, last_used_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        style.id,
                        style.user_id,
                        context_type_value,
                        style_attrs_json,
                        style.confidence,
                        style.sample_count,
                        style.created_at.isoformat(),
                        now,
                        style.last_used_at.isoformat() if style.last_used_at else None
                    )
                )
            
            await conn.commit()
            return style
    
    async def analyze_and_update_style(
        self,
        context_type: ContextType,
        user_id: str = "default",
        force_reanalysis: bool = False
    ) -> Optional[CommunicationStyleProfile]:
        """
        Analyze writing samples and update communication style profile.
        
        This method:
        1. Fetches writing samples for the given context
        2. Runs style analysis
        3. Creates or updates the style profile
        
        Args:
            context_type: Context type to analyze
            user_id: User ID
            force_reanalysis: If True, reanalyze even if recent analysis exists
            
        Returns:
            Updated CommunicationStyleProfile or None if no samples
        """
        logger.info(f"Analyzing communication style for context: {context_type.value}")
        
        # Fetch writing samples for this context
        samples = await self._fetch_writing_samples(context_type, user_id)
        
        if not samples:
            logger.warning(f"No writing samples found for context: {context_type.value}")
            return None
        
        logger.info(f"Found {len(samples)} samples for analysis")
        
        # Run style analysis
        analysis_result = await self.analyzer.analyze_samples(samples, context_type.value)
        
        # Create or update style profile
        style_id = str(uuid.uuid4())
        
        # Check if profile already exists
        existing_profile = await self.get_communication_style(context_type, user_id)
        if existing_profile:
            style_id = existing_profile.id
        
        # Create StyleAttributes from analysis
        style_attrs = StyleAttributes(**analysis_result['style_attributes'])
        
        # Create profile
        profile = CommunicationStyleProfile(
            id=style_id,
            user_id=user_id,
            context_type=context_type,
            style_attributes=style_attrs,
            confidence=analysis_result['confidence'],
            sample_count=analysis_result['sample_count'],
            created_at=existing_profile.created_at if existing_profile else datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_used_at=None
        )
        
        # Save to database
        saved_profile = await self.save_communication_style(profile)
        
        logger.info(
            f"Style profile updated for {context_type.value}: "
            f"confidence={saved_profile.confidence:.2f}, "
            f"samples={saved_profile.sample_count}"
        )
        
        return saved_profile
    
    async def analyze_all_contexts(
        self,
        user_id: str = "default"
    ) -> Dict[str, Optional[CommunicationStyleProfile]]:
        """
        Analyze and update style profiles for all contexts that have samples.
        
        Args:
            user_id: User ID
            
        Returns:
            Dict mapping context_type to updated profile (or None if no samples)
        """
        logger.info("Analyzing all context types")
        
        results = {}
        
        # Get all contexts that have samples
        contexts_with_samples = await self._get_contexts_with_samples(user_id)
        
        logger.info(f"Found samples for {len(contexts_with_samples)} contexts")
        
        for context_type_str in contexts_with_samples:
            try:
                context_type = ContextType(context_type_str)
                profile = await self.analyze_and_update_style(context_type, user_id)
                results[context_type_str] = profile
            except Exception as e:
                logger.error(f"Error analyzing context {context_type_str}: {e}")
                results[context_type_str] = None
        
        return results
    
    async def _fetch_writing_samples(
        self,
        context_type: ContextType,
        user_id: str = "default"
    ) -> List[Dict[str, Any]]:
        """
        Fetch writing samples for a specific context.
        
        Args:
            context_type: Context type to fetch samples for
            user_id: User ID
            
        Returns:
            List of writing sample dicts with 'content' field
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT content, created_at, recipient, app_name
                FROM writing_samples
                WHERE user_id = ? AND context_type = ?
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (user_id, context_type.value)
            )
            rows = await cursor.fetchall()
            
            return [
                {
                    'content': row['content'],
                    'created_at': row['created_at'],
                    'recipient': row['recipient'],
                    'app_name': row['app_name']
                }
                for row in rows
            ]
    
    async def _get_contexts_with_samples(
        self,
        user_id: str = "default"
    ) -> List[str]:
        """
        Get list of context types that have writing samples.
        
        Args:
            user_id: User ID
            
        Returns:
            List of context type strings
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT DISTINCT context_type
                FROM writing_samples
                WHERE user_id = ?
                """,
                (user_id,)
            )
            rows = await cursor.fetchall()
            
            return [row['context_type'] for row in rows]

