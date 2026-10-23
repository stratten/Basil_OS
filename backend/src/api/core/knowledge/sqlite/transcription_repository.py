"""SQLite repository for transcription data."""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import logging
import aiosqlite

from ..models import Transcription
from .sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
    get_async_connection,
)

logger = logging.getLogger(__name__)

class TranscriptionRepository:
    """Repository for storing and retrieving transcription data."""
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize the transcription repository.
        
        Args:
            db_path: Path to the SQLite database file. If None, uses the default path.
        """
        if db_path is None:
            db_path = Path.home() / ".basil" / "knowledge_base.db"

        # Ensure directory exists
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_path)
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.db_path = db_path
            
        # Initialize the database schema
        self._initialize_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper configuration."""
        return get_sync_connection(self.db_path)
    
    def _initialize_db(self) -> None:
        """Initialize database schema if needed."""
        from .schema import get_schema_statements
        
        with self._get_connection() as conn:
            # Check if the transcriptions table exists
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='transcriptions'
            """)
            table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                # If table doesn't exist, apply schema statements
                for statement in get_schema_statements():
                    if "CREATE TABLE IF NOT EXISTS transcriptions" in statement:
                        conn.execute(statement)
                        # Also create the index for transcriptions
                        conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_transcriptions_timestamp 
                        ON transcriptions(timestamp)
                        """)
                        logger.info("Created transcriptions table and index")
                        break
    
    async def _get_async_connection(self) -> aiosqlite.Connection:
        """Get a new async database connection with proper configuration.

        This creates a fresh connection each time to avoid thread reuse issues.
        """
        try:
            return await get_async_connection(self.db_path)
        except Exception as e:
            logger.error(f"Error creating database connection: {e}")
            raise
    
    async def save_transcription(self, transcription: Transcription) -> str:
        """Save a transcription to the database.
        
        Args:
            transcription: The transcription to save
            
        Returns:
            The ID of the saved transcription
        """
        if not transcription.id:
            transcription.id = str(uuid.uuid4())
        
        if not transcription.created_at:
            transcription.created_at = datetime.now()
        if not transcription.last_transcribed_at:
            transcription.last_transcribed_at = transcription.timestamp
        
        try:
            # Check if the transcriptions table exists, create it if not
            await self._ensure_table_exists()
            
            # Check if the transcription already exists
            existing = await self.get_transcription(transcription.id)
            
            if existing:
                # Update existing transcription
                await self._update_transcription(transcription)
            else:
                # Insert new transcription
                await self._insert_transcription(transcription)
            
            return transcription.id
        except Exception as e:
            logger.error(f"Error saving transcription {transcription.id}: {e}")
            # Return the ID even if saving failed - this allows the transcription process to continue
            return transcription.id
    
    async def _ensure_table_exists(self) -> None:
        """Ensure the transcriptions table exists."""
        conn = None
        try:
            conn = await self._get_async_connection()
            # Check if the transcriptions table exists
            cursor = await conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='transcriptions'
            """)
            row = await cursor.fetchone()
            
            if not row:
                # Table doesn't exist, create it
                from .schema import get_schema_statements
                
                for statement in get_schema_statements():
                    if "CREATE TABLE IF NOT EXISTS transcriptions" in statement:
                        await conn.execute(statement)
                        # Also create the index for transcriptions
                        await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_transcriptions_timestamp 
                        ON transcriptions(timestamp)
                        """)
                        await conn.commit()
                        logger.info("Created transcriptions table and index")
                        break
        except Exception as e:
            logger.error(f"Error ensuring transcriptions table exists: {e}")
        finally:
            if conn:
                await conn.close()
    
    async def _insert_transcription(self, transcription: Transcription) -> None:
        """Insert a new transcription into the database."""
        conn = None
        try:
            conn = await self._get_async_connection()
            await conn.execute(
                """
                INSERT INTO transcriptions (
                    id, timestamp, transcription_text, model_name, 
                    audio_file_path, duration_seconds, language, created_at, last_transcribed_at,
                    app_name, window_title, task_category,
                    was_edited, edit_distance, edited_text,
                    confidence_score, processing_time_ms, user_rating, user_feedback,
                    session_id, related_activity_id, action_taken,
                    status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transcription.id,
                    transcription.timestamp.isoformat(),
                    transcription.transcription_text,
                    transcription.model_name,
                    transcription.audio_file_path,
                    transcription.duration_seconds,
                    transcription.language,
                    transcription.created_at.isoformat() if transcription.created_at else None,
                    transcription.last_transcribed_at.isoformat() if transcription.last_transcribed_at else None,
                    transcription.app_name,
                    transcription.window_title,
                    transcription.task_category,
                    transcription.was_edited,
                    transcription.edit_distance,
                    transcription.edited_text,
                    transcription.confidence_score,
                    transcription.processing_time_ms,
                    transcription.user_rating,
                    transcription.user_feedback,
                    transcription.session_id,
                    transcription.related_activity_id,
                    transcription.action_taken,
                    transcription.status,
                    transcription.error_message,
                )
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error inserting transcription {transcription.id}: {e}")
            raise
        finally:
            if conn:
                await conn.close()
    
    async def _update_transcription(self, transcription: Transcription) -> None:
        """Update an existing transcription in the database."""
        conn = None
        try:
            conn = await self._get_async_connection()
            await conn.execute(
                """
                UPDATE transcriptions SET
                    timestamp = ?,
                    transcription_text = ?,
                    model_name = ?,
                    audio_file_path = ?,
                    duration_seconds = ?,
                    language = ?,
                    last_transcribed_at = ?,
                    app_name = ?,
                    window_title = ?,
                    task_category = ?,
                    was_edited = ?,
                    edit_distance = ?,
                    edited_text = ?,
                    confidence_score = ?,
                    processing_time_ms = ?,
                    user_rating = ?,
                    user_feedback = ?,
                    session_id = ?,
                    related_activity_id = ?,
                    action_taken = ?,
                    status = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    transcription.timestamp.isoformat(),
                    transcription.transcription_text,
                    transcription.model_name,
                    transcription.audio_file_path,
                    transcription.duration_seconds,
                    transcription.language,
                    transcription.last_transcribed_at.isoformat() if transcription.last_transcribed_at else None,
                    transcription.app_name,
                    transcription.window_title,
                    transcription.task_category,
                    transcription.was_edited,
                    transcription.edit_distance,
                    transcription.edited_text,
                    transcription.confidence_score,
                    transcription.processing_time_ms,
                    transcription.user_rating,
                    transcription.user_feedback,
                    transcription.session_id,
                    transcription.related_activity_id,
                    transcription.action_taken,
                    transcription.status,
                    transcription.error_message,
                    transcription.id,
                )
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error updating transcription {transcription.id}: {e}")
            raise
        finally:
            if conn:
                await conn.close()

    async def update_status(
        self,
        transcription_id: str,
        status: str,
        *,
        transcription_text: Optional[str] = None,
        error_message: Optional[str] = None,
        processing_time_ms: Optional[int] = None,
        timestamp: Optional[datetime] = None,
        last_transcribed_at: Optional[datetime] = None,
        model_name: Optional[str] = None,
    ) -> bool:
        """Update the lifecycle state of an existing transcription row.

        This is the single SQL statement used by the transcription lifecycle
        helper to flip a pending row to completed or failed. Only the fields
        that are passed are updated; omitted kwargs leave the corresponding
        column untouched. Returns True on success, False if nothing was
        updated or an error occurred.

        When called during retranscription, ``model_name`` should be passed so
        the row reflects the model that actually produced the new text (or
        attempted it and failed) rather than the model that produced the
        original transcription.
        """
        set_clauses: List[str] = ["status = ?"]
        params: List[Any] = [status]

        if transcription_text is not None:
            set_clauses.append("transcription_text = ?")
            params.append(transcription_text)
        if error_message is not None:
            set_clauses.append("error_message = ?")
            params.append(error_message)
        elif status == "completed":
            # Clear any prior failure reason once the row reaches completed.
            set_clauses.append("error_message = NULL")
        if processing_time_ms is not None:
            set_clauses.append("processing_time_ms = ?")
            params.append(processing_time_ms)
        if timestamp is not None:
            set_clauses.append("timestamp = ?")
            params.append(timestamp.isoformat())
        if last_transcribed_at is not None:
            set_clauses.append("last_transcribed_at = ?")
            params.append(last_transcribed_at.isoformat())
        if model_name is not None:
            set_clauses.append("model_name = ?")
            params.append(model_name)

        params.append(transcription_id)
        sql = f"UPDATE transcriptions SET {', '.join(set_clauses)} WHERE id = ?"

        conn = None
        try:
            conn = await self._get_async_connection()
            cursor = await conn.execute(sql, params)
            await conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating status for transcription {transcription_id}: {e}")
            return False
        finally:
            if conn:
                await conn.close()

    async def reset_edit_tracking(self, transcription_id: str) -> bool:
        """Clear was_edited / edited_text / edit_distance for a transcription.

        Called by the retranscribe route after a successful retranscription
        so prior manual edits to the obsolete text don't linger on the row.
        The lifecycle helper deliberately leaves these columns alone so it
        can't accidentally erase edits on an unrelated pending->completed
        transition.
        """
        conn = None
        try:
            conn = await self._get_async_connection()
            await conn.execute(
                """
                UPDATE transcriptions
                SET was_edited = 0,
                    edited_text = NULL,
                    edit_distance = NULL
                WHERE id = ?
                """,
                (transcription_id,),
            )
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error resetting edit tracking for {transcription_id}: {e}")
            return False
        finally:
            if conn:
                await conn.close()

    @staticmethod
    def _row_to_transcription(row: Any) -> Transcription:
        """Build a Transcription from a DB row with defensive status fallback.

        If the database predates the 0.9.0 migration (status/error_message
        columns missing from the row) we fall back to the dataclass defaults,
        which treat the row as a successful completed transcription. This
        keeps the repository usable in the brief window before SchemaManager
        finishes its migrations.
        """
        row_keys = row.keys() if hasattr(row, "keys") else []
        return Transcription(
            id=row['id'],
            timestamp=datetime.fromisoformat(row['timestamp']),
            transcription_text=row['transcription_text'],
            model_name=row['model_name'],
            audio_file_path=row['audio_file_path'],
            duration_seconds=row['duration_seconds'],
            language=row['language'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            last_transcribed_at=(
                datetime.fromisoformat(row['last_transcribed_at'])
                if 'last_transcribed_at' in row_keys and row['last_transcribed_at']
                else None
            ),
            app_name=row['app_name'],
            window_title=row['window_title'],
            task_category=row['task_category'],
            was_edited=bool(row['was_edited']),
            edit_distance=row['edit_distance'],
            edited_text=row['edited_text'],
            confidence_score=row['confidence_score'],
            processing_time_ms=row['processing_time_ms'],
            user_rating=row['user_rating'],
            user_feedback=row['user_feedback'],
            session_id=row['session_id'],
            related_activity_id=row['related_activity_id'],
            action_taken=row['action_taken'],
            status=row['status'] if 'status' in row_keys and row['status'] else "completed",
            error_message=row['error_message'] if 'error_message' in row_keys else None,
        )
    
    async def get_transcription(self, transcription_id: str) -> Optional[Transcription]:
        """Get a transcription by ID.
        
        Args:
            transcription_id: The ID of the transcription to retrieve
            
        Returns:
            The transcription if found, None otherwise
        """
        conn = None
        try:
            conn = await self._get_async_connection()
            cursor = await conn.execute(
                """
                SELECT * FROM transcriptions WHERE id = ?
                """,
                (transcription_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None

            return self._row_to_transcription(row)
        except Exception as e:
            logger.error(f"Error retrieving transcription {transcription_id}: {e}")
            return None
        finally:
            if conn:
                await conn.close()
    
    async def get_recent_transcriptions(self, limit: int = 10) -> List[Transcription]:
        """Get recent transcriptions.
        
        Args:
            limit: Maximum number of transcriptions to retrieve
            
        Returns:
            List of recent transcriptions
        """
        conn = None
        try:
            conn = await self._get_async_connection()
            cursor = await conn.execute(
                """
                SELECT * FROM transcriptions 
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = await cursor.fetchall()

            return [self._row_to_transcription(row) for row in rows]
        except Exception as e:
            logger.error(f"Error retrieving recent transcriptions: {e}")
            return []
        finally:
            if conn:
                await conn.close()
    
    async def search_transcriptions(
        self, 
        query: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        model_name: Optional[str] = None,
        app_name: Optional[str] = None,
        task_category: Optional[str] = None,
        was_edited: Optional[bool] = None,
        user_rated: Optional[bool] = None,
        limit: int = 50
    ) -> List[Transcription]:
        """Search for transcriptions.
        
        Args:
            query: Text to search for in transcription_text
            start_date: Start date for filtering
            end_date: End date for filtering
            model_name: Filter by model name
            app_name: Filter by application name
            task_category: Filter by task category
            was_edited: Filter by whether the transcription was edited
            user_rated: Filter by whether the transcription has a user rating
            limit: Maximum number of results to return
            
        Returns:
            List of matching transcriptions
        """
        logger.info(f"Searching transcriptions with params: query={query}, start_date={start_date}, limit={limit}")
        
        # First ensure the table exists
        await self._ensure_table_exists()
        logger.info("Table existence check completed")
        
        conditions: list[str] = []
        params: list[Any] = []  # SQL parameters can be strings, ints, etc.
        
        if query:
            conditions.append("transcription_text LIKE ?")
            params.append(f"%{query}%")
        
        if start_date:
            conditions.append("timestamp >= ?")
            params.append(start_date.isoformat())
        
        if end_date:
            conditions.append("timestamp <= ?")
            params.append(end_date.isoformat())
        
        if model_name:
            conditions.append("model_name = ?")
            params.append(model_name)
            
        if app_name:
            conditions.append("app_name = ?")
            params.append(app_name)
            
        if task_category:
            conditions.append("task_category = ?")
            params.append(task_category)
            
        if was_edited is not None:
            conditions.append("was_edited = ?")
            params.append(1 if was_edited else 0)
            
        if user_rated is not None:
            if user_rated:
                conditions.append("user_rating IS NOT NULL")
            else:
                conditions.append("user_rating IS NULL")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        logger.info(f"SQL where clause: {where_clause}")
        logger.info(f"SQL params: {params}")
        
        conn = None
        try:
            conn = await self._get_async_connection()
            
            # First check if the table exists
            cursor = await conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='transcriptions'
            """)
            table_exists = await cursor.fetchone() is not None
            logger.info(f"Transcriptions table exists: {table_exists}")
            
            if not table_exists:
                logger.warning("Transcriptions table does not exist, returning empty list")
                return []
                
            query = f"""
                SELECT * FROM transcriptions 
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            logger.info(f"Executing query: {query}")
            
            cursor = await conn.execute(
                query,
                params + [limit]
            )
            rows = await cursor.fetchall()
            
            logger.info(f"Query returned {len(rows)} rows")

            return [self._row_to_transcription(row) for row in rows]
        except Exception as e:
            logger.error(f"Error searching transcriptions: {e}")
            logger.exception("Detailed exception info:")
            return []
        finally:
            if conn:
                await conn.close()
    
    async def delete_transcription(self, transcription_id: str) -> bool:
        """Delete a transcription from the database.
        
        Args:
            transcription_id: The ID of the transcription to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        conn = None
        try:
            conn = await self._get_async_connection()
            await conn.execute("DELETE FROM transcriptions WHERE id = ?", (transcription_id,))
            await conn.commit()
            logger.info(f"Deleted transcription {transcription_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting transcription {transcription_id}: {e}")
            return False
        finally:
            if conn:
                await conn.close()