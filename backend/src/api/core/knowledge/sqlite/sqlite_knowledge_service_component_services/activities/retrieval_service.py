"""Activity retrieval component service for SQLite knowledge service."""

import json
import logging
from datetime import datetime
from typing import Optional
import aiosqlite

from ....models import Activity
from ..infrastructure.connection import get_async_connection

logger = logging.getLogger(__name__)

class ActivityRetrievalService:
    """Component service for retrieving individual activities from SQLite."""
    
    def __init__(self, db_path: str):
        """Initialize the activity retrieval service.
        
        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = db_path
    
    async def _get_async_connection(self) -> aiosqlite.Connection:
        """Get an async database connection with proper configuration."""
        return await get_async_connection(self.db_path)
    
    async def get_activity_by_id(self, activity_id: str) -> Optional[Activity]:
        """Get a single activity by its ID.
        
        Args:
            activity_id: The ID of the activity to retrieve
            
        Returns:
            Activity object if found, None otherwise
        """
        try:
            conn = await self._get_async_connection()
            try:
                # Query for the specific activity
                cursor = await conn.execute(
                    """
                    SELECT id, timestamp, app_name, window_title, 
                           extracted_text, duration, ai_analysis, capture_frequency_minutes
                    FROM activities 
                    WHERE id = ?
                    """,
                    [activity_id]
                )
                row = await cursor.fetchone()
                
                if not row:
                    logger.debug(f"Activity {activity_id} not found")
                    return None
                
                # Get metadata for this activity
                metadata_cursor = await conn.execute(
                    "SELECT key, value FROM activity_metadata WHERE activity_id = ?",
                    [activity_id]
                )
                metadata = {}
                async for meta_row in metadata_cursor:
                    metadata[meta_row[0]] = meta_row[1]
                
                # Parse AI analysis JSON if available
                ai_analysis = None
                if row[6]:  # ai_analysis is the 7th column (index 6)
                    try:
                        ai_analysis = json.loads(row[6])
                    except Exception as e:
                        logger.warning(f"Error parsing AI analysis JSON for activity {activity_id}: {e}")
                
                activity = Activity(
                    id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    app_name=row[2],
                    window_title=row[3],
                    extracted_text=row[4],
                    duration=row[5],
                    metadata=metadata,
                    ai_analysis=ai_analysis,
                    capture_frequency_minutes=row[7]  # capture_frequency_minutes is the 8th column (index 7)
                )
                
                logger.debug(f"Retrieved activity {activity_id}")
                return activity
                
            finally:
                await conn.close()
            
        except Exception as e:
            logger.error(f"Error getting activity by ID {activity_id}: {e}", exc_info=True)
            return None 