"""Activity pattern persistence and aggregation."""

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

import aiosqlite

from ....models import Activity
from ...schema import get_schema_statements
from ..infrastructure.connection import get_sync_connection, get_async_connection, generate_context_hash

logger = logging.getLogger(__name__)


class ActivityPatternRepository:
    def __init__(self, db_path: str, schema: Dict[str, Set[str]]) -> None:
        self.db_path = db_path
        self.schema = schema

    async def get_activity_patterns(self, lookback_days: int = 7) -> Dict[str, Any]:
        """Get activity patterns and statistics."""
        conn = await get_async_connection(self.db_path)
        try:
            cursor = await conn.execute("SELECT MAX(timestamp) as latest FROM activities")
            row = await cursor.fetchone()
            if not row or not row['latest']:
                return {'apps': {}, 'temporal': {}, 'metadata': {}}

            latest = datetime.fromisoformat(row['latest'])
            cutoff = (latest - timedelta(days=lookback_days)).isoformat()

            patterns = {
                'apps': await self._get_app_patterns(conn, cutoff),
                'temporal': await self._get_temporal_patterns(conn, cutoff),
                'metadata': await self._get_metadata_patterns(conn, cutoff),
            }

            return patterns
        finally:
            await conn.close()

    async def store_pattern(
        self,
        pattern_type: str,
        pattern_data: Dict[str, Any],
        confidence: float = 1.0,
    ) -> str:
        """Store a detected pattern."""
        pattern_id = str(uuid.uuid4())

        with get_sync_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO activity_patterns (
                    id, pattern_type, pattern_data, confidence
                ) VALUES (?, ?, ?, ?)
                """,
                (pattern_id, pattern_type, json.dumps(pattern_data), confidence),
            )
            conn.commit()

        return pattern_id

    async def _get_app_patterns(self, conn: aiosqlite.Connection, cutoff: str) -> Dict[str, Any]:
        """Get application usage patterns."""
        cursor = await conn.execute("SELECT COUNT(*) as count FROM activities")
        row = await cursor.fetchone()
        logger.info(f"Total activities: {row['count']}")

        cursor = await conn.execute("""
            SELECT 
                app_name,
                COUNT(*) as count,
                AVG(duration) as avg_duration,
                GROUP_CONCAT(DISTINCT substr(timestamp, 11, 2)) as hours
            FROM activities
            WHERE timestamp > ?
            GROUP BY app_name
            HAVING count > 5
            ORDER BY count DESC
        """, (cutoff,))

        rows = await cursor.fetchall()
        logger.info(f"Found {len(rows)} app patterns")

        return {
            row['app_name']: {
                'frequency': row['count'],
                'avg_duration': row['avg_duration'],
                'active_hours': row['hours'].split(','),
            }
            for row in rows
        }

    async def _get_temporal_patterns(self, conn: aiosqlite.Connection, cutoff: str) -> Dict[str, Any]:
        """Get temporal activity patterns."""
        cursor = await conn.execute("""
            SELECT 
                substr(timestamp, 11, 2) as hour,
                COUNT(*) as count,
                GROUP_CONCAT(DISTINCT app_name) as apps
            FROM activities
            WHERE timestamp > ?
            GROUP BY hour
            ORDER BY count DESC
        """, (cutoff,))

        rows = await cursor.fetchall()
        return {
            row['hour']: {
                'activity_count': row['count'],
                'active_apps': row['apps'].split(','),
            }
            for row in rows
        }

    async def _get_metadata_patterns(
        self, conn: aiosqlite.Connection, cutoff: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get patterns in metadata usage."""
        cursor = await conn.execute("""
            SELECT 
                m.key,
                m.value,
                COUNT(*) as count,
                AVG(m.confidence) as avg_confidence
            FROM activity_metadata m
            JOIN activities a ON a.id = m.activity_id
            WHERE a.timestamp > ?
            GROUP BY m.key, m.value
            HAVING count > 3
            ORDER BY count DESC
        """, (cutoff,))

        rows = await cursor.fetchall()
        patterns: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            if row['key'] not in patterns:
                patterns[row['key']] = []
            patterns[row['key']].append({
                'value': row['value'],
                'frequency': row['count'],
                'confidence': row['avg_confidence'],
            })

        return patterns
