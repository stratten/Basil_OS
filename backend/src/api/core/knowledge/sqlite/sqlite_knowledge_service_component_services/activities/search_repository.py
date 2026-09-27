"""Activity search and similarity persistence."""

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


class ActivitySearchRepository:
    def __init__(self, db_path: str, schema: Dict[str, Set[str]]) -> None:
        self.db_path = db_path
        self.schema = schema

    async def search_activities(
        self,
        time_range: Optional[Dict[str, datetime]] = None,
        text_search: Optional[str] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Activity]:
        """Search for activities with optional filters.

        Args:
            time_range: Optional dict with ``'start'`` and ``'end'`` datetime objects.
            text_search: Optional FTS5 formatted search string.
            metadata_filters: Optional dict of metadata key-value pairs.
            limit: Maximum number of results to return.

        Returns:
            List of matching Activity objects.
        """
        try:
            print("\n==== SQLITE SEARCH ACTIVITIES DEBUG ====")
            print(f"Database path: {self.db_path}")
            print(f"Path exists: {Path(self.db_path).exists()}")
            print(f"Path is file: {Path(self.db_path).is_file() if Path(self.db_path).exists() else 'N/A'}")
            print(f"Parameters:")
            print(f"  - Time range: {time_range}")
            print(f"  - Text search: '{text_search}'")
            print(f"  - Metadata filters: {metadata_filters}")
            print(f"  - Limit: {limit}")

            columns = [
                'id', 'timestamp', 'app_name', 'window_title',
                'extracted_text', 'duration', 'ai_analysis', 'capture_frequency_minutes',
            ]
            conditions: List[tuple] = []

            if time_range:
                print("Adding time range conditions to query")
                if time_range.get('start'):
                    conditions.append(('timestamp', '>=', time_range['start'].isoformat()))
                    print(f"  - Start time: {time_range['start'].isoformat()}")
                if time_range.get('end'):
                    conditions.append(('timestamp', '<=', time_range['end'].isoformat()))
                    print(f"  - End time: {time_range['end'].isoformat()}")

            params = [value for _, _, value in conditions]

            if conditions:
                print("Adding WHERE conditions to query")
                for col, op, val in conditions:
                    print(f"  - Condition: {col} {op} {val}")
                base_query = f"""
                    SELECT {', '.join(f'a.{col}' for col in columns)}
                    FROM activities a
                    WHERE {' AND '.join(f'{col} {op} ?' for col, op, _ in conditions)}
                """
            else:
                base_query = f"""
                    SELECT {', '.join(f'a.{col}' for col in columns)}
                    FROM activities a
                """

            query = base_query

            if text_search:
                print(f"Adding full-text search for: '{text_search}'")
                cleaned_search = re.sub(r'\{[!$]?[\w.]+\}|\{[^}]*\}', ' ', text_search)
                cleaned_search = self._sanitize_fts_query(cleaned_search)
                print(f"Cleaned search query: '{cleaned_search}'")

                if cleaned_search:
                    query = f"""
                        WITH prev_results AS ({query})
                        SELECT DISTINCT {', '.join(f'a.{col}' for col in columns)}
                        FROM prev_results a
                        JOIN activities_fts fts ON a.id = fts.activity_id
                        WHERE fts.content MATCH ?
                    """
                    params.append(cleaned_search)

            if metadata_filters:
                print("Adding metadata filters to query")
                for key, value in metadata_filters.items():
                    print(f"  - Filter: {key} = {value}")
                    if isinstance(value, (list, tuple)):
                        placeholders = ','.join(['?' for _ in value])
                        query = f"""
                            WITH prev_results AS ({query})
                            SELECT DISTINCT {', '.join(f'prev.{col}' for col in columns)}
                            FROM prev_results prev
                            JOIN activity_metadata m_{key}
                            ON prev.id = m_{key}.activity_id
                            AND m_{key}.key = ?
                            AND m_{key}.value IN ({placeholders})
                        """
                        params.append(key)
                        params.extend(value)
                    else:
                        query = f"""
                            WITH prev_results AS ({query})
                            SELECT DISTINCT {', '.join(f'prev.{col}' for col in columns)}
                            FROM prev_results prev
                            JOIN activity_metadata m_{key}
                            ON prev.id = m_{key}.activity_id
                            AND m_{key}.key = ?
                            AND m_{key}.value = ?
                        """
                        params.extend([key, value])

            query = f"""
                WITH final_results AS ({query})
                SELECT DISTINCT {', '.join(f'f.{col}' for col in columns)}
                FROM final_results f
                ORDER BY f.timestamp DESC LIMIT ?
            """
            params.append(limit)

            print("\nFinal SQL query:")
            print(query.strip())
            print(f"Parameters: {params}")

            print("\nConnecting to database...")
            conn = await get_async_connection(self.db_path)
            print(f"Connection established: {conn}")
            try:
                print("\nChecking if activities table exists...")
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='activities'"
                )
                table_exists = await cursor.fetchone()
                if table_exists:
                    print(f"Activities table exists: {table_exists[0]}")
                else:
                    print("WARNING: Activities table does not exist!")

                print("\nExecuting query...")
                cursor = await conn.execute(query, params)
                rows = await cursor.fetchall()
                print(f"Query returned {len(rows)} rows")

                if rows:
                    print("\nFirst 5 results:")
                    for i, row in enumerate(rows[:5]):
                        print(f"  {i+1}. ID: {row[0]}, Time: {row[1]}, App: {row[2]}, Title: {row[3]}")
                else:
                    print("NO RESULTS FOUND!")
                    print("\nTrying a simple query to check if the database has any activities:")
                    simple_cursor = await conn.execute("SELECT COUNT(*) FROM activities")
                    count = await simple_cursor.fetchone()
                    print(f"Total activities in database: {count[0]}")

                    if time_range and time_range.get('start'):
                        date_part = time_range['start'].date().isoformat()
                        print(f"\nTrying a LIKE query with just the date part: {date_part}")
                        like_cursor = await conn.execute(
                            "SELECT COUNT(*) FROM activities WHERE timestamp LIKE ?",
                            [f"{date_part}%"],
                        )
                        like_count = await like_cursor.fetchone()
                        print(f"Activities matching date {date_part}: {like_count[0]}")

                        if like_count[0] > 0:
                            print("\nSample activities for this date:")
                            sample_cursor = await conn.execute(
                                "SELECT id, timestamp, app_name FROM activities WHERE timestamp LIKE ? LIMIT 5",
                                [f"{date_part}%"],
                            )
                            sample_rows = await sample_cursor.fetchall()
                            for i, row in enumerate(sample_rows):
                                print(f"  {i+1}. ID: {row[0]}, Time: {row[1]}, App: {row[2]}")

                activities = []
                for row in rows:
                    metadata_cursor = await conn.execute(
                        "SELECT key, value FROM activity_metadata WHERE activity_id = ?",
                        [row[0]],
                    )
                    metadata: Dict[str, str] = {}
                    async for meta_row in metadata_cursor:
                        metadata[meta_row[0]] = meta_row[1]

                    ai_analysis = None
                    if row[6]:
                        try:
                            ai_analysis = json.loads(row[6])
                        except Exception as e:
                            logger.warning(f"Error parsing AI analysis JSON for activity {row[0]}: {e}")

                    activity = Activity(
                        id=row[0],
                        timestamp=datetime.fromisoformat(row[1]),
                        app_name=row[2],
                        window_title=row[3],
                        extracted_text=row[4],
                        duration=row[5],
                        metadata=metadata,
                        ai_analysis=ai_analysis,
                        capture_frequency_minutes=row[7],
                    )
                    activities.append(activity)

                print(f"\nConverted {len(activities)} rows to Activity objects")
                print("==== END SQLITE SEARCH ACTIVITIES DEBUG ====\n")
                return activities
            finally:
                await conn.close()
                print("Database connection closed")

        except Exception as e:
            print(f"ERROR in search_activities: {e}")
            import traceback
            print(traceback.format_exc())
            logger.error(f"Error searching activities: {e}", exc_info=True)
            raise

    async def count_activities_by_metadata(self, key: str, value: str) -> int:
        """Return the indexed count of activities with one metadata value."""
        conn = await get_async_connection(self.db_path)
        try:
            cursor = await conn.execute(
                """
                SELECT COUNT(*)
                FROM activity_metadata
                WHERE key = ? AND value = ?
                """,
                (key, value),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            await conn.close()

    async def count_automatic_captures_since(self, cutoff: Optional[datetime]) -> int:
        """Return the durable count of automatic-capture activities at or after ``cutoff``.

        Uses a single indexed COUNT query rather than ``search_activities``'s
        row-fetching path, since that path caps results at its ``limit``
        argument and would silently undercount once true daily capture volume
        (several hundred per day) exceeds a reasonable limit over a 7- or
        30-day window. ``cutoff=None`` counts every automatic-capture activity
        ever recorded.
        """
        conn = await get_async_connection(self.db_path)
        try:
            if cutoff is not None:
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM activities a
                    JOIN activity_metadata m
                      ON m.activity_id = a.id AND m.key = 'automatic_capture'
                    WHERE a.timestamp >= ?
                    """,
                    (cutoff.isoformat(),),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM activities a
                    JOIN activity_metadata m
                      ON m.activity_id = a.id AND m.key = 'automatic_capture'
                    """
                )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # Patterns
    # ------------------------------------------------------------------

    async def get_similar_activities(
        self,
        activity_id: str,
        min_similarity: float = 0.5,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get activities similar to the given one based on context hash."""
        with get_sync_connection(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT context_hash FROM activities WHERE id = ?",
                (activity_id,),
            )
            row = cursor.fetchone()

            if not row or not row['context_hash']:
                return []

            cursor = conn.execute(
                """
                SELECT a.*, 1.0 as similarity
                FROM activities a
                WHERE a.context_hash = ?
                AND a.id != ?
                ORDER BY a.timestamp DESC
                LIMIT ?
                """,
                (row['context_hash'], activity_id, limit),
            )

            activities = []
            for row in cursor:
                activity = dict(row)
                if activity['ai_analysis']:
                    activity['ai_analysis'] = json.loads(activity['ai_analysis'])
                activities.append(activity)

            return activities

    # ------------------------------------------------------------------
    # CRUD mutations
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_fts_query(query_text: str) -> str:
        """Sanitize text for FTS5 query."""
        if not query_text:
            return ""

        sanitized = query_text.replace('"', '""')
        sanitized = re.sub(r'[*^:(){}\[\].,~`!@#$%&+=|<>?\\]', ' ', sanitized)
        terms = [term.strip() for term in sanitized.split() if term.strip()]
        quoted_terms = [f'"{term}"' for term in terms if len(term) > 1]
        return ' OR '.join(quoted_terms) if quoted_terms else ""

