"""SQLite repository for conversation data."""

import base64
import uuid
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple, TYPE_CHECKING
import logging
import aiosqlite
import os
import asyncio

# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from .sqlite_knowledge_service import SQLiteKnowledgeService

# Import schema statements at module level to avoid threading issues
from .schema import get_schema_statements
from .sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
    get_async_connection,
    run_write_transaction,
)
from api.services.conversation.conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    is_conversation_turn_metadata_active,
)

logger = logging.getLogger(__name__)


DEFAULT_CONVERSATION_PAGE_LIMIT = 30
MAX_CONVERSATION_PAGE_LIMIT = 100


def _encode_conversation_page_cursor(updated_at: str, conversation_id: str) -> str:
    payload = json.dumps(
        {"id": conversation_id, "updated_at": updated_at},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_conversation_page_cursor(cursor: Optional[str]) -> Optional[Tuple[str, str]]:
    if cursor is None:
        return None
    normalized = cursor.strip()
    if not normalized:
        raise ValueError("Invalid conversation page cursor")
    try:
        padded = normalized + "=" * (-len(normalized) % 4)
        decoded = base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Invalid conversation page cursor") from error
    if not isinstance(payload, dict) or set(payload) != {"id", "updated_at"}:
        raise ValueError("Invalid conversation page cursor")
    updated_at = payload["updated_at"]
    conversation_id = payload["id"]
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("Invalid conversation page cursor")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise ValueError("Invalid conversation page cursor")
    return updated_at, conversation_id


def _escape_sql_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class ConversationMessagePair:
    """The durable IDs created together for one routed Conversation turn."""

    conversation_id: str
    user_message_id: str
    assistant_message_id: str


class ConversationTurnAdmissionConflict(Exception):
    """Raised when a durable conversation turn is already active."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"A response is already active for conversation {conversation_id}")
        self.conversation_id = conversation_id


@dataclass(frozen=True)
class ConversationAgentNarrationContext:
    """Durable inputs for narrating one linked Agent Task after restart."""

    conversation_id: str
    user_message_id: str
    user_content: str
    user_metadata: Dict[str, Any]
    assistant_message_id: str
    assistant_model_id: str | None
    assistant_metadata: Dict[str, Any]


@dataclass(frozen=True)
class ConversationAgentNarrationRecoveryCandidate:
    """One terminal Agent Task turn whose narration must resume after restart."""

    agent_task_id: str
    assistant_message_id: str
    narration_lifecycle: str


class ConversationRepository:
    """Repository for storing and retrieving conversation data."""
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None, sqlite_service: Optional['SQLiteKnowledgeService'] = None) -> None:
        """Initialize the conversation repository.
        
        Args:
            db_path: Path to the SQLite database file. If None, uses the default path.
            sqlite_service: Optional shared SQLite service for unified database access.
        """
        if sqlite_service is not None:
            self.db_path = sqlite_service.db_path
            logger.info("ConversationRepository initialized with shared SQLiteKnowledgeService")
        else:
            if db_path is None:
                db_path = Path.home() / ".basil" / "knowledge_base.db"

            if isinstance(db_path, Path):
                db_path.parent.mkdir(parents=True, exist_ok=True)
                self.db_path = str(db_path)
            else:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self.db_path = db_path
                
            db_file = Path(self.db_path)
            logger.info(f"ConversationRepository initialized with direct database access: {self.db_path}")
            logger.info(f"Database directory exists: {db_file.parent.exists()}")
            logger.info(f"Database file exists: {db_file.exists()}")
            
            try:
                if not db_file.exists():
                    db_file.touch()
                    logger.info(f"Created database file: {self.db_path}")
                
                if db_file.exists() and not os.access(self.db_path, os.W_OK):
                    logger.warning(f"Database file is not writable: {self.db_path}")
                    
            except Exception as e:
                logger.error(f"Error setting up database file {self.db_path}: {e}")
    
    async def _ensure_tables_exist_in_connection(self, conn: aiosqlite.Connection) -> None:
        """Ensure conversation tables exist using the provided connection."""
        try:
            # Get database path for logging
            db_path = self.db_path
            logger.info(f"Checking conversation tables in database: {db_path}")
            
            # Check if the conversations table exists
            cursor = await conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='conversations'
            """)
            conv_table_exists = await cursor.fetchone()
            
            cursor = await conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='conversation_messages'
            """)
            msg_table_exists = await cursor.fetchone()
            
            logger.info(f"Table status: conversations={bool(conv_table_exists)}, messages={bool(msg_table_exists)}")
            
            if not conv_table_exists or not msg_table_exists:
                logger.info("Creating conversation tables...")
                # Tables don't exist, create them
                statements_executed = 0
                for statement in get_schema_statements():
                    if ("CREATE TABLE IF NOT EXISTS conversations" in statement or 
                        "CREATE TABLE IF NOT EXISTS conversation_messages" in statement or
                        "idx_conversations_" in statement or 
                        "idx_conversation_messages_" in statement):
                        logger.debug(f"Executing: {statement[:100]}...")
                        await conn.execute(statement)
                        statements_executed += 1
                        
                logger.info(f"Created conversation tables and indices ({statements_executed} statements executed)")
            else:
                logger.debug("Conversation tables already exist")
        except Exception as e:
            logger.error(f"Error ensuring conversation tables exist: {e}", exc_info=True)
            raise

    async def _get_async_connection(self) -> aiosqlite.Connection:
        """Get a new async database connection with proper configuration."""
        return await get_async_connection(self.db_path)

    async def create_conversation(self, system_message: Optional[str] = None, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new conversation.
        
        Returns:
            The conversation ID
        """
        conversation_id = str(uuid.uuid4())
        
        def _sync_create():
            conn = get_sync_connection(self.db_path)
            with conn:
                # Ensure conversation tables exist
                for stmt in get_schema_statements():
                    if ("CREATE TABLE IF NOT EXISTS conversations" in stmt or 
                        "CREATE TABLE IF NOT EXISTS conversation_messages" in stmt or
                        "idx_conversations_" in stmt or 
                        "idx_conversation_messages_" in stmt):
                        conn.execute(stmt)
                # Insert conversation
                conn.execute(
                    "INSERT INTO conversations (id, system_message, title, metadata, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (conversation_id, system_message, title, json.dumps(metadata) if metadata else None)
                )
                # Insert system message if provided
                if system_message:
                    msg_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO conversation_messages "
                        "(id, conversation_id, role, content, timestamp) VALUES (?, ?, 'system', ?, CURRENT_TIMESTAMP)",
                        (msg_id, conversation_id, system_message)
                    )
                conn.commit()
            return conversation_id
        
        return await asyncio.to_thread(_sync_create)

    async def add_message(self, conversation_id: str, role: str, content: str, model_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add a message to a conversation.
        
        Returns:
            The message ID
        """
        def _sync_add():
            conn = get_sync_connection(self.db_path)
            with conn:
                msg_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO conversation_messages (id, conversation_id, role, content, model_id, metadata, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (msg_id, conversation_id, role, content, model_id, json.dumps(metadata) if metadata else None)
                )
                conn.execute(
                    "UPDATE conversations SET message_count = message_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (conversation_id,)
                )
                conn.commit()
            return msg_id
        
        return await asyncio.to_thread(_sync_add)

    async def get_conversation_with_messages(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a conversation with all its messages.
        
        Args:
            conversation_id: ID of the conversation
            
        Returns:
            Dictionary containing conversation data and messages, or None if not found
        """
        def _sync_get():
            try:
                conn = get_sync_connection(self.db_path)
                with conn:
                    # Get conversation metadata
                    cursor = conn.execute(
                        """
                        SELECT id, created_at, updated_at, system_message, title, metadata, is_active, message_count
                        FROM conversations WHERE id = ?
                        """,
                        (conversation_id,)
                    )
                    conv_row = cursor.fetchone()
                    
                    if not conv_row:
                        return None
                    
                    # Get messages
                    cursor = conn.execute(
                        """
                        SELECT id, role, content, timestamp, model_id, metadata
                        FROM conversation_messages 
                        WHERE conversation_id = ? 
                        ORDER BY timestamp ASC
                        """,
                        (conversation_id,)
                    )
                    message_rows = cursor.fetchall()
                    
                    # Format response
                    messages = []
                    for row in message_rows:
                        message = {
                            "id": row["id"],
                            "role": row["role"],
                            "content": row["content"],
                            "timestamp": row["timestamp"],
                            "model_id": row["model_id"],
                            "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
                        }
                        messages.append(message)
                    
                    conversation = {
                        "id": conv_row["id"],
                        "created_at": conv_row["created_at"],
                        "updated_at": conv_row["updated_at"],
                        "system_message": conv_row["system_message"],
                        "title": conv_row["title"],
                        "metadata": json.loads(conv_row["metadata"]) if conv_row["metadata"] else {},
                        "is_active": conv_row["is_active"],
                        "message_count": conv_row["message_count"],
                        "messages": messages
                    }
                    
                    return conversation
                    
            except Exception as e:
                logger.error(f"Error getting conversation {conversation_id}: {e}")
                return None
        
        return await asyncio.to_thread(_sync_get)

    async def get_conversation_summary(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a conversation's identity/metadata without loading its messages.

        Used by history/detail lookups that need to confirm a conversation
        exists and read its title before fetching a separately bounded slice
        of messages via get_bounded_recent_messages -- avoids the unbounded
        message load that get_conversation_with_messages performs.
        """
        def _sync_get_summary() -> Optional[Dict[str, Any]]:
            try:
                conn = get_sync_connection(self.db_path)
                with conn:
                    cursor = conn.execute(
                        "SELECT id, created_at, updated_at, title, message_count, is_active "
                        "FROM conversations WHERE id = ?",
                        (conversation_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    return {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "title": row["title"],
                        "message_count": row["message_count"],
                        "is_active": row["is_active"],
                    }
            except Exception as e:
                logger.error(f"Error getting conversation summary {conversation_id}: {e}")
                return None

        return await asyncio.to_thread(_sync_get_summary)

    async def clear_conversation(self, conversation_id: str, keep_system_messages: bool = True) -> bool:
        """Clear all messages from a conversation.
        
        Args:
            conversation_id: ID of the conversation
            keep_system_messages: Whether to keep system messages
            
        Returns:
            True if successful, False otherwise
        """
        def _sync_clear():
            try:
                conn = get_sync_connection(self.db_path)
                with conn:
                    if keep_system_messages:
                        conn.execute(
                            """
                            DELETE FROM conversation_messages 
                            WHERE conversation_id = ? AND role != 'system'
                            """,
                            (conversation_id,)
                        )
                    else:
                        conn.execute(
                            """
                            DELETE FROM conversation_messages 
                            WHERE conversation_id = ?
                            """,
                            (conversation_id,)
                        )
                    
                    # Update message count
                    cursor = conn.execute(
                        """
                        SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = ?
                        """,
                        (conversation_id,)
                    )
                    count = cursor.fetchone()
                    message_count = count[0] if count else 0
                    
                    conn.execute(
                        """
                        UPDATE conversations 
                        SET message_count = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE id = ?
                        """,
                        (message_count, conversation_id)
                    )
                    
                    conn.commit()
                    return True
                    
            except Exception as e:
                logger.error(f"Error clearing conversation {conversation_id}: {e}")
                return False
        
        return await asyncio.to_thread(_sync_clear)

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages.
        
        Args:
            conversation_id: ID of the conversation
            
        Returns:
            True if successful, False otherwise
        """
        def _sync_delete():
            try:
                conn = get_sync_connection(self.db_path)
                with conn:
                    # Delete conversation (messages will be deleted by CASCADE)
                    conn.execute(
                        "DELETE FROM conversations WHERE id = ?",
                        (conversation_id,)
                    )
                    conn.commit()
                    return True
                    
            except Exception as e:
                logger.error(f"Error deleting conversation {conversation_id}: {e}")
                return False
        
        return await asyncio.to_thread(_sync_delete)

    async def list_conversation_page(
        self,
        *,
        query: Optional[str],
        limit: int = DEFAULT_CONVERSATION_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return one stable page of conversation summaries without N+1 reads."""
        if limit < 1 or limit > MAX_CONVERSATION_PAGE_LIMIT:
            raise ValueError(
                f"Conversation page limit must be between 1 and {MAX_CONVERSATION_PAGE_LIMIT}"
            )
        normalized_query = query.strip() if query else ""
        page_cursor = _decode_conversation_page_cursor(cursor)
        search_pattern = f"%{_escape_sql_like_literal(normalized_query)}%"

        def _sync_list_page() -> Dict[str, Any]:
            conn = get_sync_connection(self.db_path)
            with conn:
                conditions: List[str] = []
                parameters: List[Any] = []
                if normalized_query:
                    conditions.append(
                        "(c.title LIKE ? ESCAPE '\\' OR EXISTS ("
                        "SELECT 1 FROM conversation_messages AS matching_messages "
                        "WHERE matching_messages.conversation_id = c.id "
                        "AND matching_messages.content LIKE ? ESCAPE '\\'"
                        "))"
                    )
                    parameters.extend((search_pattern, search_pattern))
                if page_cursor is not None:
                    cursor_updated_at, cursor_id = page_cursor
                    conditions.append(
                        "(c.updated_at < ? OR (c.updated_at = ? AND c.id < ?))"
                    )
                    parameters.extend((cursor_updated_at, cursor_updated_at, cursor_id))
                where_clause = " AND ".join(conditions) if conditions else "1=1"
                parameters.append(limit + 1)
                rows = conn.execute(
                    f"""
                    SELECT
                        c.id,
                        c.created_at,
                        c.updated_at,
                        c.title,
                        (
                            SELECT COUNT(*)
                            FROM conversation_messages AS counted_messages
                            WHERE counted_messages.conversation_id = c.id
                              AND counted_messages.role != 'system'
                        ) AS message_count,
                        (
                            SELECT CASE
                                WHEN length(preview_message.content) > 100
                                    THEN substr(preview_message.content, 1, 100) || char(46, 46, 46)
                                ELSE preview_message.content
                            END
                            FROM conversation_messages AS preview_message
                            WHERE preview_message.conversation_id = c.id
                              AND preview_message.role != 'system'
                            ORDER BY preview_message.timestamp DESC, preview_message.rowid DESC
                            LIMIT 1
                        ) AS last_message_preview
                    FROM conversations AS c
                    WHERE {where_clause}
                    ORDER BY c.updated_at DESC, c.id DESC
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
                page_rows = rows[:limit]
                has_more = len(rows) > limit
                conversations = [
                    {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "title": row["title"],
                        "message_count": row["message_count"],
                        "last_message_preview": row["last_message_preview"],
                    }
                    for row in page_rows
                ]
                next_cursor = None
                if has_more and page_rows:
                    final_row = page_rows[-1]
                    next_cursor = _encode_conversation_page_cursor(
                        final_row["updated_at"],
                        final_row["id"],
                    )
                return {
                    "conversations": conversations,
                    "has_more": has_more,
                    "next_cursor": next_cursor,
                }

        return await asyncio.to_thread(_sync_list_page)

    async def list_conversations(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List conversations ordered by updated_at descending.
        
        Args:
            limit: Maximum number of conversations to return
            offset: Number of conversations to skip
            
        Returns:
            List of conversation dictionaries
        """
        def _sync_list():
            try:
                conn = get_sync_connection(self.db_path)
                with conn:
                    cursor = conn.execute(
                        """
                        SELECT id, created_at, updated_at, title, message_count, is_active
                        FROM conversations 
                        ORDER BY updated_at DESC 
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset)
                    )
                    rows = cursor.fetchall()
                    
                    conversations = []
                    for row in rows:
                        conversations.append({
                            "id": row["id"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                            "title": row["title"],
                            "message_count": row["message_count"],
                            "is_active": row["is_active"]
                        })
                    
                    return conversations
                    
            except Exception as e:
                logger.error(f"Error listing conversations: {e}")
                return []
        
        return await asyncio.to_thread(_sync_list)
    
    async def update_message(self, message_id: str, content: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Update a message's content and/or metadata.
        
        Args:
            message_id: ID of the message to update
            content: New content (if provided)
            metadata: New metadata (if provided)
        """
        def _sync_update():
            conn = get_sync_connection(self.db_path)
            with conn:
                if content is not None and metadata is not None:
                    conn.execute(
                        "UPDATE conversation_messages SET content = ?, metadata = ? WHERE id = ?",
                        (content, json.dumps(metadata), message_id)
                    )
                elif content is not None:
                    conn.execute(
                        "UPDATE conversation_messages SET content = ? WHERE id = ?",
                        (content, message_id)
                    )
                elif metadata is not None:
                    conn.execute(
                        "UPDATE conversation_messages SET metadata = ? WHERE id = ?",
                        (json.dumps(metadata), message_id)
                    )
                conn.commit()
        
        return await asyncio.to_thread(_sync_update)
    
    async def create_message_pair(
        self,
        conversation_id: str,
        user_content: str,
        user_metadata: Optional[Dict[str, Any]],
        assistant_metadata: Optional[Dict[str, Any]],
        assistant_model_id: Optional[str] = None,
    ) -> ConversationMessagePair:
        """Persist a user message and empty assistant placeholder atomically."""
        user_metadata_copy = dict(user_metadata) if user_metadata else None
        assistant_metadata_copy = dict(assistant_metadata) if assistant_metadata else None

        def _sync_create_pair() -> ConversationMessagePair:
            def _body(conn) -> ConversationMessagePair:
                exists = conn.execute(
                    "SELECT 1 FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                if exists is None:
                    raise ValueError(f"Conversation {conversation_id} not found")

                user_message_id = str(uuid.uuid4())
                assistant_message_id = str(uuid.uuid4())
                paired_assistant_metadata = self._with_pair_user_message_id(
                    assistant_metadata_copy,
                    user_message_id,
                )
                conn.execute(
                    "INSERT INTO conversation_messages "
                    "(id, conversation_id, role, content, metadata, timestamp) "
                    "VALUES (?, ?, 'user', ?, ?, CURRENT_TIMESTAMP)",
                    (
                        user_message_id,
                        conversation_id,
                        user_content,
                        json.dumps(user_metadata_copy) if user_metadata_copy else None,
                    ),
                )
                conn.execute(
                    "INSERT INTO conversation_messages "
                    "(id, conversation_id, role, content, model_id, metadata, timestamp) "
                    "VALUES (?, ?, 'assistant', '', ?, ?, CURRENT_TIMESTAMP)",
                    (
                        assistant_message_id,
                        conversation_id,
                        assistant_model_id,
                        json.dumps(paired_assistant_metadata) if paired_assistant_metadata else None,
                    ),
                )
                conn.execute(
                    "UPDATE conversations "
                    "SET message_count = message_count + 2, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (conversation_id,),
                )
                return ConversationMessagePair(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                )

            return run_write_transaction(self.db_path, "create_message_pair", _body)

        return await asyncio.to_thread(_sync_create_pair)

    async def admit_and_create_message_pair(
        self,
        conversation_id: str,
        user_content: str,
        user_metadata: Optional[Dict[str, Any]],
        assistant_metadata: Optional[Dict[str, Any]],
        assistant_model_id: Optional[str] = None,
    ) -> ConversationMessagePair:
        """Atomically reject active turns and persist one new routed message pair."""
        user_metadata_copy = dict(user_metadata) if user_metadata else None
        assistant_metadata_copy = dict(assistant_metadata) if assistant_metadata else None

        def _sync_admit_and_create() -> ConversationMessagePair:
            def _body(conn) -> ConversationMessagePair:
                exists = conn.execute(
                    "SELECT 1 FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                if exists is None:
                    raise ValueError(f"Conversation {conversation_id} not found")

                rows = conn.execute(
                    "SELECT metadata FROM conversation_messages "
                    "WHERE conversation_id = ? AND role = 'assistant' AND metadata IS NOT NULL "
                    "ORDER BY timestamp DESC, rowid DESC",
                    (conversation_id,),
                ).fetchall()
                for row in rows:
                    try:
                        metadata = json.loads(row["metadata"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(metadata, dict):
                        continue
                    if isinstance(metadata.get("conversation_turn"), dict):
                        if is_conversation_turn_metadata_active(metadata):
                            raise ConversationTurnAdmissionConflict(conversation_id)
                        break

                user_message_id = str(uuid.uuid4())
                assistant_message_id = str(uuid.uuid4())
                paired_assistant_metadata = self._with_pair_user_message_id(
                    assistant_metadata_copy,
                    user_message_id,
                )
                conn.execute(
                    "INSERT INTO conversation_messages "
                    "(id, conversation_id, role, content, metadata, timestamp) "
                    "VALUES (?, ?, 'user', ?, ?, CURRENT_TIMESTAMP)",
                    (
                        user_message_id,
                        conversation_id,
                        user_content,
                        json.dumps(user_metadata_copy) if user_metadata_copy else None,
                    ),
                )
                conn.execute(
                    "INSERT INTO conversation_messages "
                    "(id, conversation_id, role, content, model_id, metadata, timestamp) "
                    "VALUES (?, ?, 'assistant', '', ?, ?, CURRENT_TIMESTAMP)",
                    (
                        assistant_message_id,
                        conversation_id,
                        assistant_model_id,
                        json.dumps(paired_assistant_metadata) if paired_assistant_metadata else None,
                    ),
                )
                conn.execute(
                    "UPDATE conversations "
                    "SET message_count = message_count + 2, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (conversation_id,),
                )
                return ConversationMessagePair(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                )

            return run_write_transaction(
                self.db_path,
                "admit_and_create_message_pair",
                _body,
            )

        return await asyncio.to_thread(_sync_admit_and_create)

    @staticmethod
    def _with_pair_user_message_id(
        metadata: Optional[Dict[str, Any]],
        user_message_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Attach the durable user-message link without changing other metadata."""
        if metadata is None:
            return None
        paired_metadata = dict(metadata)
        raw_turn = paired_metadata.get(CONVERSATION_TURN_METADATA_KEY)
        if not isinstance(raw_turn, dict):
            return paired_metadata
        paired_turn = dict(raw_turn)
        paired_turn["user_message_id"] = user_message_id
        paired_metadata[CONVERSATION_TURN_METADATA_KEY] = paired_turn
        return paired_metadata

    @staticmethod
    def _merge_metadata(
        existing: Dict[str, Any],
        patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(existing)
        for key, patch_value in patch.items():
            existing_value = merged.get(key)
            if isinstance(existing_value, dict) and isinstance(patch_value, dict):
                merged[key] = ConversationRepository._merge_metadata(
                    existing_value,
                    patch_value,
                )
            else:
                merged[key] = patch_value
        return merged

    async def merge_message_metadata(
        self,
        message_id: str,
        metadata_patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Recursively merge metadata into one message without erasing other keys."""
        if not metadata_patch:
            raise ValueError("metadata_patch must not be empty")
        metadata_patch_copy = dict(metadata_patch)

        def _sync_merge_metadata() -> Dict[str, Any]:
            def _body(conn) -> Dict[str, Any]:
                row = conn.execute(
                    "SELECT conversation_id, metadata FROM conversation_messages WHERE id = ?",
                    (message_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Conversation message {message_id} not found")
                existing_metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                if not isinstance(existing_metadata, dict):
                    raise ValueError(f"Conversation message {message_id} has invalid metadata")
                merged_metadata = self._merge_metadata(
                    existing_metadata,
                    metadata_patch_copy,
                )
                conn.execute(
                    "UPDATE conversation_messages SET metadata = ? WHERE id = ?",
                    (json.dumps(merged_metadata), message_id),
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row["conversation_id"],),
                )
                return merged_metadata

            return run_write_transaction(self.db_path, "merge_message_metadata", _body)

        return await asyncio.to_thread(_sync_merge_metadata)

    async def get_bounded_recent_messages(
        self,
        conversation_id: str,
        message_limit: int,
        character_limit: int,
    ) -> List[Dict[str, Any]]:
        """Return bounded non-system messages in chronological order."""
        if message_limit < 1:
            raise ValueError("message_limit must be at least 1")
        if character_limit < 1:
            raise ValueError("character_limit must be at least 1")

        def _sync_get_bounded_messages() -> List[Dict[str, Any]]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    "SELECT id, role, content, timestamp, model_id, metadata "
                    "FROM conversation_messages "
                    "WHERE conversation_id = ? AND role != 'system' "
                    "ORDER BY timestamp DESC, rowid DESC LIMIT ?",
                    (conversation_id, message_limit),
                ).fetchall()
                remaining_characters = character_limit
                retained_messages: List[Dict[str, Any]] = []
                has_retained_nonempty_content = False
                for row in rows:
                    content = row["content"]
                    if len(content) > remaining_characters and has_retained_nonempty_content:
                        continue
                    truncated = len(content) > remaining_characters
                    retained_messages.append(
                        {
                            "id": row["id"],
                            "role": row["role"],
                            "content": content[:remaining_characters] if truncated else content,
                            "content_truncated": truncated,
                            "timestamp": row["timestamp"],
                            "model_id": row["model_id"],
                            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                        }
                    )
                    remaining_characters -= min(len(content), remaining_characters)
                    has_retained_nonempty_content = has_retained_nonempty_content or bool(content)
                retained_messages.reverse()
                return retained_messages

        return await asyncio.to_thread(_sync_get_bounded_messages)

    async def find_conversation_turn_by_agent_task_id(
        self,
        agent_task_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Find an assistant placeholder linked to one durable Agent Task ID."""
        normalized_agent_task_id = agent_task_id.strip()
        if not normalized_agent_task_id:
            raise ValueError("agent_task_id must not be empty")

        def _sync_find() -> Optional[Dict[str, Any]]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    "SELECT id, conversation_id, model_id, metadata FROM conversation_messages "
                    "WHERE role = 'assistant' AND metadata IS NOT NULL"
                ).fetchall()
                for row in rows:
                    try:
                        metadata = json.loads(row["metadata"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(metadata, dict):
                        continue
                    turn = metadata.get("conversation_turn")
                    if not isinstance(turn, dict):
                        continue
                    if turn.get("agent_task_id") != normalized_agent_task_id:
                        continue
                    return {
                        "conversation_id": row["conversation_id"],
                        "assistant_message_id": row["id"],
                        "assistant_model_id": row["model_id"],
                        "metadata": metadata,
                    }
            return None

        return await asyncio.to_thread(_sync_find)

    async def get_latest_conversation_turn_metadata(
        self,
        conversation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the most recent routed-turn placeholder metadata for one conversation."""
        normalized_conversation_id = conversation_id.strip()
        if not normalized_conversation_id:
            raise ValueError("conversation_id must not be empty")

        def _sync_find() -> Optional[Dict[str, Any]]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    "SELECT metadata FROM conversation_messages "
                    "WHERE conversation_id = ? AND role = 'assistant' AND metadata IS NOT NULL "
                    "ORDER BY timestamp DESC, rowid DESC",
                    (normalized_conversation_id,),
                ).fetchall()
                for row in rows:
                    try:
                        metadata = json.loads(row["metadata"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(metadata, dict):
                        continue
                    if isinstance(metadata.get("conversation_turn"), dict):
                        return metadata
            return None

        return await asyncio.to_thread(_sync_find)

    async def get_conversation_agent_narration_context(
        self,
        agent_task_id: str,
    ) -> Optional[ConversationAgentNarrationContext]:
        """Load durable original-request and model inputs for later narration."""
        normalized_agent_task_id = agent_task_id.strip()
        if not normalized_agent_task_id:
            raise ValueError("agent_task_id must not be empty")
        linked_turn = await self.find_conversation_turn_by_agent_task_id(
            normalized_agent_task_id,
        )
        if linked_turn is None:
            return None
        assistant_metadata = linked_turn.get("metadata")
        if not isinstance(assistant_metadata, dict):
            return None
        raw_turn = assistant_metadata.get("conversation_turn")
        if not isinstance(raw_turn, dict):
            return None
        user_message_id = raw_turn.get("user_message_id")
        if not isinstance(user_message_id, str) or not user_message_id.strip():
            return None
        conversation_id = linked_turn.get("conversation_id")
        assistant_message_id = linked_turn.get("assistant_message_id")
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            return None
        if not isinstance(assistant_message_id, str) or not assistant_message_id.strip():
            return None

        def _sync_get() -> Optional[ConversationAgentNarrationContext]:
            conn = get_sync_connection(self.db_path)
            with conn:
                row = conn.execute(
                    "SELECT content, metadata FROM conversation_messages "
                    "WHERE id = ? AND conversation_id = ? AND role = 'user'",
                    (user_message_id, conversation_id),
                ).fetchone()
                if row is None:
                    return None
                try:
                    user_metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                except (TypeError, json.JSONDecodeError):
                    return None
                if not isinstance(user_metadata, dict):
                    return None
                return ConversationAgentNarrationContext(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    user_content=row["content"],
                    user_metadata=user_metadata,
                    assistant_message_id=assistant_message_id,
                    assistant_model_id=linked_turn.get("assistant_model_id"),
                    assistant_metadata=assistant_metadata,
                )

        return await asyncio.to_thread(_sync_get)

    async def list_recoverable_conversation_agent_narrations(
        self,
    ) -> List[ConversationAgentNarrationRecoveryCandidate]:
        """List terminal Agent Task turns whose narration must resume after restart."""
        from ....services.conversation.conversation_turn_contract import (
            ConversationTurnRoute,
            is_terminal_conversation_turn_lifecycle,
            parse_conversation_turn_metadata,
        )

        _RECOVERABLE_NARRATION_LIFECYCLES = frozenset({"ready", "narrating", "retrying"})

        def _sync_list() -> List[ConversationAgentNarrationRecoveryCandidate]:
            conn = get_sync_connection(self.db_path)
            candidates: List[ConversationAgentNarrationRecoveryCandidate] = []
            seen_agent_task_ids: set[str] = set()
            with conn:
                rows = conn.execute(
                    "SELECT id, metadata FROM conversation_messages "
                    "WHERE role = 'assistant' AND metadata IS NOT NULL"
                ).fetchall()
                for row in rows:
                    try:
                        metadata = json.loads(row["metadata"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    parsed = parse_conversation_turn_metadata(metadata)
                    if parsed is None or parsed.route is not ConversationTurnRoute.AGENT_TASK:
                        continue
                    if not isinstance(parsed.agent_task_id, str) or not parsed.agent_task_id.strip():
                        continue
                    if not is_terminal_conversation_turn_lifecycle(parsed.lifecycle):
                        continue
                    if parsed.narration.lifecycle.value not in _RECOVERABLE_NARRATION_LIFECYCLES:
                        continue
                    assistant_message_id = row["id"]
                    if not isinstance(assistant_message_id, str) or not assistant_message_id.strip():
                        continue
                    if parsed.agent_task_id in seen_agent_task_ids:
                        continue
                    seen_agent_task_ids.add(parsed.agent_task_id)
                    candidates.append(
                        ConversationAgentNarrationRecoveryCandidate(
                            agent_task_id=parsed.agent_task_id,
                            assistant_message_id=assistant_message_id,
                            narration_lifecycle=parsed.narration.lifecycle.value,
                        )
                    )
            return candidates

        return await asyncio.to_thread(_sync_list)

    async def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """Update a conversation's title.
        
        Args:
            conversation_id: ID of the conversation to update
            title: New title for the conversation
            
        Returns:
            True if successful, False if conversation not found
        """
        def _sync_update():
            conn = get_sync_connection(self.db_path)
            try:
                with conn:
                    # Update the title and updated_at timestamp
                    cursor = conn.execute(
                        """UPDATE conversations 
                           SET title = ?, updated_at = CURRENT_TIMESTAMP 
                           WHERE id = ?""",
                        (title, conversation_id)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Error updating conversation title: {e}")
                return False
        
        return await asyncio.to_thread(_sync_update)

    async def search_conversations(
        self,
        query: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Search for conversations by title or message content.
        
        Args:
            query: Text to search for in conversation titles and message content
            start_date: Start date for filtering
            end_date: End date for filtering
            limit: Maximum number of conversations to return (default 50)
            offset: Number of conversations to skip for pagination (default 0)
            
        Returns:
            List of matching conversation dictionaries with metadata
        """
        def _sync_search():
            try:
                conn = get_sync_connection(self.db_path)
                with conn:
                    # Build the query - search in titles and message content
                    # Return distinct conversations that match
                    conditions = []
                    params = []
                    
                    if query:
                        # Search in both title and message content
                        conditions.append("""
                            (c.title LIKE ? OR c.id IN (
                                SELECT DISTINCT conversation_id 
                                FROM conversation_messages 
                                WHERE content LIKE ?
                            ))
                        """)
                        params.append(f"%{query}%")
                        params.append(f"%{query}%")
                    
                    if start_date:
                        conditions.append("c.updated_at >= ?")
                        params.append(start_date.isoformat())
                    
                    if end_date:
                        conditions.append("c.updated_at <= ?")
                        params.append(end_date.isoformat())
                    
                    where_clause = " AND ".join(conditions) if conditions else "1=1"
                    params.extend([limit, offset])
                    
                    cursor = conn.execute(
                        f"""
                        SELECT c.id, c.created_at, c.updated_at, c.title, c.message_count, c.is_active
                        FROM conversations c
                        WHERE {where_clause}
                        ORDER BY c.updated_at DESC 
                        LIMIT ? OFFSET ?
                        """,
                        params
                    )
                    rows = cursor.fetchall()
                    
                    conversations = []
                    for row in rows:
                        # Get last message preview for each conversation
                        last_msg_cursor = conn.execute(
                            """
                            SELECT content FROM conversation_messages 
                            WHERE conversation_id = ? AND role != 'system'
                            ORDER BY timestamp DESC 
                            LIMIT 1
                            """,
                            (row["id"],)
                        )
                        last_msg_row = last_msg_cursor.fetchone()
                        last_message_preview = None
                        if last_msg_row:
                            content = last_msg_row["content"]
                            last_message_preview = content[:100] + "..." if len(content) > 100 else content
                        
                        conversations.append({
                            "id": row["id"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                            "title": row["title"],
                            "message_count": row["message_count"],
                            "is_active": row["is_active"],
                            "last_message_preview": last_message_preview
                        })
                    
                    logger.info(f"Conversation search returned {len(conversations)} results (query={query})")
                    return conversations
                    
            except Exception as e:
                logger.error(f"Error searching conversations: {e}")
                return []
        
        return await asyncio.to_thread(_sync_search)