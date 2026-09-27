"""Agent-facing recall tool factory (Conversation history)."""

from __future__ import annotations

import json
import logging
from typing import List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

from .conversation_source import ConversationRecallSource

logger = logging.getLogger(__name__)


class RecallConversationsInput(BaseModel):
    """Input schema for recall_conversations."""

    scope: Literal["current_thread", "history", "detail"] = Field(
        default="current_thread",
        description=(
            "'current_thread' (default): the bounded recent messages of THE "
            "Conversation this task was delegated from (no id needed). "
            "'history': search past Conversations by title/content and/or time "
            "window. 'detail': fetch bounded messages for ONE named Conversation "
            "by id (use conversation_id from a 'history' result)."
        ),
    )
    query: Optional[str] = Field(default=None, description="Search text; used only when scope='history'.")
    start_time: Optional[str] = Field(default=None, description="Lower time bound for scope='history': ISO or relative ('yesterday','last_week','this_month').")
    end_time: Optional[str] = Field(default=None, description="Upper time bound for scope='history': ISO or relative ('now','today').")
    limit: int = Field(default=20, description="Maximum messages/results to return (clamped to 1-50).")
    conversation_id: Optional[str] = Field(default=None, description="Required for scope='detail': the id of a Conversation from a 'history' result.")


_FULL_DESCRIPTION = """Recall Basil Conversation history (the chat surface, not agent-task runs).

WHEN TO USE:
- scope='current_thread' (default): read the recent messages of THE Conversation
  this task was delegated from -- what the user already said in this thread,
  right before delegating this request to you. No id needed.
- scope='history': search every past Conversation (all threads) by title/content
  text and/or time window -- "did the user discuss this before in chat".
- scope='detail': fetch bounded messages for ONE Conversation by id. Pass
  conversation_id from the id field of a prior 'history' result.

This is NOT agent-task history (use recall_agent_tasks for prior task runs) and
NOT screen/activity history (use query_activities). It reads only Basil
Conversation messages.

Time tokens for scope='history' start_time/end_time: ISO timestamps or
'today','yesterday','this_week','last_week','this_month','last_month','now'.
"""

SLIM_DESCRIPTION = (
    "Recall Basil Conversation (chat) history. scope='current_thread' (default) "
    "reads the recent messages of the Conversation this task was delegated from "
    "(no id needed). scope='history' searches past Conversations by "
    "title/content + time window. scope='detail' fetches bounded messages for "
    "one Conversation id from a 'history' result. Not agent-task history "
    "(recall_agent_tasks) and not screen activity (query_activities)."
)


def create_recall_conversations_tools(
    profile=None,
    current_conversation_id: Optional[str] = None,
) -> List[StructuredTool]:
    """Build the Conversation recall tool, capturing the delegating conversation id."""
    source = ConversationRecallSource()
    captured_conversation_id = current_conversation_id

    async def _recall_conversations(
        scope: str = "current_thread",
        query: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 20,
        conversation_id: Optional[str] = None,
    ) -> str:
        try:
            bounded = max(1, min(int(limit or 20), 50))
            if scope == "detail":
                if not conversation_id:
                    return json.dumps({
                        "success": False,
                        "scope": "detail",
                        "error": "conversation_id is required for scope='detail'. Pass the id from a prior 'history' result.",
                    }, ensure_ascii=False)
                detail = await source.detail(conversation_id, bounded)
                if detail is None:
                    return json.dumps({
                        "success": False,
                        "scope": "detail",
                        "error": f"No Conversation found with id {conversation_id!r}.",
                    }, ensure_ascii=False)
                return json.dumps({"success": True, "scope": "detail", "conversation": detail}, ensure_ascii=False)
            if scope == "history":
                from ..activity_query_tool import _parse_time_parameter

                start_dt = _parse_time_parameter(start_time, default=None) if start_time else None
                end_dt = _parse_time_parameter(end_time, default=None) if end_time else None
                results = await source.search(query, start_dt, end_dt, bounded)
                return json.dumps({"success": True, "scope": "history", "count": len(results), "results": results}, ensure_ascii=False)
            resolved_conversation_id = captured_conversation_id or conversation_id
            if not resolved_conversation_id:
                return json.dumps({
                    "success": False,
                    "scope": "current_thread",
                    "error": "No delegating Conversation id is available for scope='current_thread'. Use scope='history' with a query to search past Conversations.",
                    "results": [],
                }, ensure_ascii=False)
            results = await source.current_thread(resolved_conversation_id, bounded)
            return json.dumps({
                "success": True,
                "scope": "current_thread",
                "conversation_id": resolved_conversation_id,
                "count": len(results),
                "results": results,
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - tool must always return a string
            logger.error("recall_conversations failed: %s", exc, exc_info=True)
            return json.dumps({"success": False, "error": str(exc), "results": []}, ensure_ascii=False)

    description = select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION)
    return [
        StructuredTool.from_function(
            func=_recall_conversations,
            coroutine=_recall_conversations,
            name="recall_conversations",
            description=description,
            args_schema=RecallConversationsInput,
        )
    ]
