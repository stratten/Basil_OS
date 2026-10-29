"""Which messages of one conversation a sidebar search query matches (read-only)."""

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from .sqlite_knowledge_service_component_services.infrastructure.connection import get_sync_connection


@dataclass(frozen=True)
class ConversationSearchMatches:
    """The searched phrase and the ids of the non-system messages that contain it, oldest first."""

    tokens: List[str]
    matched_message_ids: List[str]


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def find_conversation_search_matches(
    db_path: str,
    conversation_id: str,
    query: Optional[str],
) -> Optional[ConversationSearchMatches]:
    """Find the messages of a conversation that hold the query, or None when the conversation does not exist.

    The conversation list searches title and message text for the whole phrase as one escaped substring, so a message
    matches here under exactly the same rule (``LIKE ... ESCAPE``, case-insensitive for ASCII). The phrase is returned
    as the single highlight token. A blank query matches nothing.
    """
    phrase = query.strip() if query else ""

    def _sync_find() -> Optional[ConversationSearchMatches]:
        conn = get_sync_connection(db_path)
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if exists is None:
                return None
            if not phrase:
                return ConversationSearchMatches(tokens=[], matched_message_ids=[])
            rows = conn.execute(
                "SELECT id FROM conversation_messages "
                "WHERE conversation_id = ? AND role != 'system' AND content LIKE ? ESCAPE '\\' "
                "ORDER BY timestamp ASC, rowid ASC",
                (conversation_id, f"%{_escape_like_literal(phrase)}%"),
            ).fetchall()
            return ConversationSearchMatches(tokens=[phrase], matched_message_ids=[row["id"] for row in rows])

    return await asyncio.to_thread(_sync_find)
