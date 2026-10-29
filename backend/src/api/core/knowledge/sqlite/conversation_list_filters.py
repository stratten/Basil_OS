"""Sidebar filters for the Chats conversation list (read-only SQL builders against the ``c`` conversations alias)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, Tuple

from api.core.knowledge.sqlite.filter_time import utc_text
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.list_filters import ACTIVE_STATUSES

AGENT_WORK_NONE = "none"
AGENT_WORK_ANY = "any"
AGENT_WORK_ACTIVE = "active"
AGENT_WORK_FAILED = "failed"
AGENT_WORK_FILTERS: Tuple[str, ...] = (AGENT_WORK_NONE, AGENT_WORK_ANY, AGENT_WORK_ACTIVE, AGENT_WORK_FAILED)

LENGTH_SINGLE = "single"
LENGTH_MULTI = "multi"
LENGTH_FILTERS: Tuple[str, ...] = (LENGTH_SINGLE, LENGTH_MULTI)

# Last activity of a conversation, the same field the list is sorted by.
LAST_ACTIVITY_SQL = "c.updated_at"

# Every Agent Task chain started from this conversation, reaching follow-ups through their root, exactly as
# ``list_latest_agent_task_status_by_origins`` does when it picks the status icon.
_CHAIN_TASKS_SQL = (
    "FROM agent_tasks AS task "
    "JOIN agent_tasks AS root ON root.id = COALESCE(task.root_task_id, task.id) "
    "WHERE root.origin_type = 'conversation' AND root.origin_id = c.id"
)
_TASK_ACTIVITY_SQL = "datetime(COALESCE(task.last_interaction_timestamp, task.updated_at, task.timestamp))"


@dataclass(frozen=True)
class ConversationListFilters:
    """Optional narrowing applied on top of a conversation page; every field left as None is not applied.

    ``agent_work`` is one of ``AGENT_WORK_FILTERS``: ``none`` keeps conversations that never started an Agent Task,
    ``any`` keeps those that did, ``active`` keeps those with a task still running or waiting on someone, and
    ``failed`` keeps those whose latest finished task failed while none is still running.
    ``length`` is ``single`` for a conversation with at most one user message (one exchange) and ``multi`` for more.
    """

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    agent_work: Optional[str] = None
    length: Optional[str] = None


def _agent_work_condition(agent_work: str) -> Tuple[str, List[Any]]:
    active_placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
    active_exists = f"EXISTS (SELECT 1 {_CHAIN_TASKS_SQL} AND task.status IN ({active_placeholders}))"
    active_params = sorted(ACTIVE_STATUSES)
    if agent_work == AGENT_WORK_NONE:
        return f"NOT EXISTS (SELECT 1 {_CHAIN_TASKS_SQL})", []
    if agent_work == AGENT_WORK_ANY:
        return f"EXISTS (SELECT 1 {_CHAIN_TASKS_SQL})", []
    if agent_work == AGENT_WORK_ACTIVE:
        return active_exists, active_params
    if agent_work == AGENT_WORK_FAILED:
        latest_status = (
            f"(SELECT task.status {_CHAIN_TASKS_SQL} "
            f"ORDER BY {_TASK_ACTIVITY_SQL} DESC, task.rowid DESC LIMIT 1)"
        )
        return f"(NOT {active_exists} AND {latest_status} = 'failed')", active_params
    raise ValueError(f"Unsupported conversation agent work filter: {agent_work}")


def _length_condition(length: str) -> str:
    user_messages = (
        "(SELECT COUNT(*) FROM conversation_messages AS user_messages "
        "WHERE user_messages.conversation_id = c.id AND user_messages.role = 'user')"
    )
    if length == LENGTH_SINGLE:
        return f"{user_messages} <= 1"
    if length == LENGTH_MULTI:
        return f"{user_messages} > 1"
    raise ValueError(f"Unsupported conversation length filter: {length}")


def build_conversation_filter_conditions(
    filters: Optional[ConversationListFilters],
) -> Tuple[List[str], List[Any]]:
    """Return SQL conditions and their parameters against the ``c`` conversations alias."""
    conditions: List[str] = []
    params: List[Any] = []
    if filters is None:
        return conditions, params

    if filters.start_date is not None:
        conditions.append(f"datetime({LAST_ACTIVITY_SQL}) >= ?")
        params.append(utc_text(filters.start_date))

    if filters.end_date is not None:
        conditions.append(f"datetime({LAST_ACTIVITY_SQL}) <= ?")
        params.append(utc_text(filters.end_date))

    if filters.agent_work:
        condition, condition_params = _agent_work_condition(filters.agent_work)
        conditions.append(condition)
        params.extend(condition_params)

    if filters.length:
        conditions.append(_length_condition(filters.length))

    return conditions, params
