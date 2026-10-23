"""Activity storage and mutation persistence."""

import asyncio
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


class ActivityStorageRepository:
    def __init__(self, db_path: str, schema: Dict[str, Set[str]]) -> None:
        self.db_path = db_path
        self.schema = schema

    async def store_activity(
        self,
        timestamp: datetime,
        app_name: str,
        window_title: Optional[str] = None,
        extracted_text: Optional[str] = None,
        ai_analysis: Optional[Dict[str, Any]] = None,
        duration: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        capture_frequency_minutes: Optional[float] = None,
        content_fingerprint: Optional[str] = None,
        observation_count: int = 1,
        last_observed_at: Optional[datetime] = None,
    ) -> str:
        """Store an activity with enhanced metadata.

        Returns:
            ID of the created activity record.
        """
        return await asyncio.to_thread(
            self._store_activity_synchronously,
            timestamp,
            app_name,
            window_title,
            extracted_text,
            ai_analysis,
            duration,
            metadata,
            capture_frequency_minutes,
            content_fingerprint,
            observation_count,
            last_observed_at,
        )

    def _store_activity_synchronously(
        self,
        timestamp: datetime,
        app_name: str,
        window_title: Optional[str],
        extracted_text: Optional[str],
        ai_analysis: Optional[Dict[str, Any]],
        duration: Optional[int],
        metadata: Optional[Dict[str, Any]],
        capture_frequency_minutes: Optional[float],
        content_fingerprint: Optional[str],
        observation_count: int,
        last_observed_at: Optional[datetime],
    ) -> str:
        """Run the complete existing activity transaction off the ASGI event loop."""
        activity_id = str(uuid.uuid4())

        print(f"\n>>> SQLITE SERVICE: Storing activity {activity_id} for {app_name} at {timestamp}")
        print(f">>> SQLITE SERVICE: Metadata: {metadata}")
        print(f">>> SQLITE SERVICE: Capture frequency: {capture_frequency_minutes} minutes")

        context_hash = None
        if window_title or extracted_text:
            context_hash = generate_context_hash(app_name, window_title, extracted_text)

        try:
            db_file = Path(self.db_path)
            if db_file.exists():
                print(f">>> SQLITE SERVICE: Database file exists at {self.db_path}, size: {db_file.stat().st_size} bytes")
            else:
                print(f">>> SQLITE SERVICE: Database file does not exist at {self.db_path} before storing activity")

            print(f">>> SQLITE SERVICE: Getting connection to store activity {activity_id}")
            with get_sync_connection(self.db_path) as conn:
                print(f">>> SQLITE SERVICE: Inserting activity {activity_id} into database")

                cursor = conn.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='activities'
                """)
                if cursor.fetchone() is None:
                    print(">>> SQLITE SERVICE: Activities table does not exist, creating it now")
                    for statement in get_schema_statements():
                        if "CREATE TABLE" in statement and "activities" in statement:
                            print(f">>> SQLITE SERVICE: Executing: {statement[:100]}...")
                            conn.execute(statement)
                else:
                    print(">>> SQLITE SERVICE: Activities table exists")

                insert_sql = """
                INSERT INTO activities (
                    id, timestamp, app_name, window_title, 
                    extracted_text, ai_analysis, duration, context_hash, capture_frequency_minutes,
                    content_fingerprint, observation_count, last_observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                print(f">>> SQLITE SERVICE: Executing SQL to insert activity {activity_id}")
                conn.execute(
                    insert_sql,
                    (
                        activity_id,
                        timestamp.isoformat(),
                        app_name,
                        window_title,
                        extracted_text,
                        json.dumps(ai_analysis) if ai_analysis else None,
                        duration,
                        context_hash,
                        capture_frequency_minutes,
                        content_fingerprint,
                        observation_count,
                        (last_observed_at or timestamp).isoformat(),
                    ),
                )
                print(f">>> SQLITE SERVICE: Activity {activity_id} inserted successfully")

                if metadata:
                    print(f">>> SQLITE SERVICE: Processing metadata for {activity_id}")
                    self._store_metadata(conn, activity_id, metadata)

                cursor = conn.execute("SELECT COUNT(*) FROM activities WHERE id = ?", (activity_id,))
                count = cursor.fetchone()[0]
                print(f">>> SQLITE SERVICE: Verification: Found {count} activities with ID {activity_id}")

                conn.commit()
                print(f">>> SQLITE SERVICE: Transaction committed for activity {activity_id}")

                return activity_id
        except Exception as e:
            print(f">>> SQLITE SERVICE: Error storing activity {activity_id}: {e}")
            raise

    async def find_open_sequence_activity(
        self,
        app_name: str,
        work_context_key: Optional[str],
        max_age_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        """Return the latest recent activity that a capture could extend."""
        conn = await get_async_connection(self.db_path)
        try:
            cursor = await conn.execute(
                """
                SELECT a.id, a.timestamp, a.last_observed_at, a.duration,
                       a.observation_count, a.content_fingerprint
                FROM activities a
                LEFT JOIN activity_metadata m
                    ON m.activity_id = a.id AND m.key = 'work_context_key'
                WHERE a.app_name = ?
                  AND COALESCE(m.value, '') = COALESCE(?, '')
                  AND a.content_fingerprint IS NOT NULL
                ORDER BY COALESCE(a.last_observed_at, a.timestamp) DESC
                LIMIT 1
                """,
                (app_name, work_context_key),
            )
            row = await cursor.fetchone()
            if row is None:
                return None

            reference_timestamp_raw = row["last_observed_at"] or row["timestamp"]
            try:
                reference_timestamp = datetime.fromisoformat(reference_timestamp_raw)
            except (TypeError, ValueError):
                return None

            age_seconds = (datetime.now() - reference_timestamp).total_seconds()
            if age_seconds < 0 or age_seconds > max_age_seconds:
                return None

            return dict(row)
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def update_activity(
        self,
        activity_id: str,
        updates: Dict[str, Any],
    ) -> None:
        """Update an activity's fields (validated against the cached schema)."""
        try:
            valid_updates = {
                k: v for k, v in updates.items()
                if k in self.schema.get('activities', set())
            }

            if not valid_updates:
                logger.warning(f"No valid update fields provided for activity {activity_id}")
                return

            set_clause = ", ".join(f"{k} = ?" for k in valid_updates)
            params = list(valid_updates.values())
            params.append(activity_id)

            conn = await get_async_connection(self.db_path)
            try:
                await conn.execute(
                    f"UPDATE activities SET {set_clause} WHERE id = ?",
                    params,
                )
                await conn.commit()
            finally:
                await conn.close()

            logger.info(f"Updated activity {activity_id} with fields: {list(valid_updates.keys())}")

        except Exception as e:
            logger.error(f"Error updating activity {activity_id}: {e}")
            raise

    async def update_activity_metadata(
        self,
        activity_id: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Update (upsert) metadata for an activity."""
        try:
            conn = await get_async_connection(self.db_path)
            try:
                await conn.execute(
                    """
                    DELETE FROM activity_metadata 
                    WHERE activity_id = ? AND key IN ({})
                    """.format(','.join('?' * len(metadata))),
                    [activity_id] + list(metadata.keys()),
                )

                for key, value in metadata.items():
                    if isinstance(value, dict):
                        confidence = value.get('confidence', 1.0)
                        value = value.get('value')
                    else:
                        confidence = 1.0

                    await conn.execute(
                        """
                        INSERT INTO activity_metadata (activity_id, key, value, confidence)
                        VALUES (?, ?, ?, ?)
                        """,
                        (activity_id, key, str(value), confidence),
                    )

                await conn.commit()
                logger.info(f"Updated metadata for activity {activity_id}: {list(metadata.keys())}")
            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"Error updating metadata for activity {activity_id}: {e}")
            raise

    async def delete_activity(self, activity_id: str) -> bool:
        """Delete an activity and all its associated data.

        Returns:
            ``True`` if the activity was deleted, ``False`` if it didn't exist.
        """
        try:
            conn = await get_async_connection(self.db_path)
            try:
                cursor = await conn.execute(
                    "SELECT id FROM activities WHERE id = ?",
                    (activity_id,),
                )
                exists = await cursor.fetchone()

                if not exists:
                    logger.warning(f"Activity {activity_id} not found for deletion")
                    return False

                await conn.execute(
                    "DELETE FROM activities WHERE id = ?",
                    (activity_id,),
                )

                await conn.commit()
                logger.info(f"Deleted activity {activity_id}")
                return True
            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"Error deleting activity {activity_id}: {e}")
            raise

    async def cleanup_old_activities(self, days: int = 30) -> None:
        """Clean up old activities while preserving patterns."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        try:
            conn = await get_async_connection(self.db_path)
            try:
                patterns = await self.get_activity_patterns(days)

                pattern_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT INTO activity_patterns
                    (id, pattern_type, pattern_data, last_seen)
                    VALUES (?, 'historical', ?, CURRENT_TIMESTAMP)
                    """,
                    (pattern_id, json.dumps(patterns)),
                )

                await conn.execute(
                    "DELETE FROM activities WHERE timestamp < ?",
                    (cutoff,),
                )

                await conn.commit()
                logger.info(f"Cleaned up activities older than {cutoff}")
            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"Error during activity cleanup: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_metadata(
        self,
        conn: sqlite3.Connection,
        activity_id: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Store metadata rows for an activity (within an existing transaction)."""
        print(f">>> SQLITE SERVICE: Processing metadata for {activity_id}")
        for key, value in metadata.items():
            if isinstance(value, dict):
                confidence = value.get('confidence', 1.0)
                value = value.get('value')
            else:
                confidence = 1.0

            try:
                print(f">>> SQLITE SERVICE: Inserting metadata {key}: {value} for activity {activity_id}")
                conn.execute(
                    """
                    INSERT INTO activity_metadata (activity_id, key, value, confidence)
                    VALUES (?, ?, ?, ?)
                    """,
                    (activity_id, key, str(value), confidence),
                )
                print(f">>> SQLITE SERVICE: Added metadata {key}: {value}")
            except Exception as e:
                print(f">>> SQLITE SERVICE: Error adding metadata {key}: {value} - {e}")

        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM activity_metadata WHERE activity_id = ?",
                (activity_id,),
            )
            count = cursor.fetchone()[0]
            print(f">>> SQLITE SERVICE: Verification: Found {count} metadata entries for activity {activity_id}")
        except Exception as e:
            print(f">>> SQLITE SERVICE: Error verifying metadata for activity {activity_id}: {e}")

