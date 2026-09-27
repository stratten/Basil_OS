"""Conversation history adapter for the recall toolset."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .recall_core import truncate

MAX_CONVERSATION_THREAD_MESSAGES = 30
MAX_CONVERSATION_THREAD_CHARS = 6000
MAX_CONVERSATION_SEARCH_RESULTS = 50
MAX_CONVERSATION_TITLE_CHARS = 200
MAX_CONVERSATION_PREVIEW_CHARS = 300


def _conversation_repository(knowledge_service: Any):
    from api.core.knowledge.sqlite.conversation_repository import ConversationRepository

    return ConversationRepository(sqlite_service=knowledge_service)


def _format_thread_message(message: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": message.get("id"),
        "role": message.get("role"),
        "content": message.get("content", ""),
        "content_truncated": bool(message.get("content_truncated")),
        "timestamp": message.get("timestamp"),
    }


class ConversationRecallSource:
    """Recall over the conversations/conversation_messages tables."""

    name = "conversations"

    async def current_thread(self, conversation_id: str, limit: int) -> List[Dict[str, Any]]:
        from api.dependencies import get_sqlite_knowledge_service

        repository = _conversation_repository(get_sqlite_knowledge_service())
        bounded_limit = max(1, min(int(limit or MAX_CONVERSATION_THREAD_MESSAGES), MAX_CONVERSATION_THREAD_MESSAGES))
        messages = await repository.get_bounded_recent_messages(
            conversation_id,
            message_limit=bounded_limit,
            character_limit=MAX_CONVERSATION_THREAD_CHARS,
        )
        return [_format_thread_message(message) for message in messages]

    async def search(
        self,
        query: Optional[str],
        start_time: Optional[Any],
        end_time: Optional[Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        from api.dependencies import get_sqlite_knowledge_service

        repository = _conversation_repository(get_sqlite_knowledge_service())
        bounded_limit = max(1, min(int(limit or 20), MAX_CONVERSATION_SEARCH_RESULTS))
        rows = await repository.search_conversations(
            query=query or None,
            start_date=start_time,
            end_date=end_time,
            limit=bounded_limit,
        )
        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append({
                "id": row.get("id"),
                "title": truncate(row.get("title") or "Untitled conversation", MAX_CONVERSATION_TITLE_CHARS),
                "updated_at": row.get("updated_at"),
                "message_count": row.get("message_count", 0),
                "last_message_preview": truncate(row.get("last_message_preview") or "", MAX_CONVERSATION_PREVIEW_CHARS),
            })
        return results

    async def detail(self, conversation_id: str, limit: int) -> Optional[Dict[str, Any]]:
        from api.dependencies import get_sqlite_knowledge_service

        repository = _conversation_repository(get_sqlite_knowledge_service())
        summary = await repository.get_conversation_summary(conversation_id)
        if summary is None:
            return None
        bounded_limit = max(1, min(int(limit or MAX_CONVERSATION_THREAD_MESSAGES), MAX_CONVERSATION_THREAD_MESSAGES))
        messages = await repository.get_bounded_recent_messages(
            conversation_id,
            message_limit=bounded_limit,
            character_limit=MAX_CONVERSATION_THREAD_CHARS,
        )
        return {
            "id": summary["id"],
            "title": truncate(summary.get("title") or "Untitled conversation", MAX_CONVERSATION_TITLE_CHARS),
            "updated_at": summary.get("updated_at"),
            "message_count": summary.get("message_count", 0),
            "messages": [_format_thread_message(message) for message in messages],
            "messages_truncated": summary.get("message_count", 0) > len(messages),
        }
