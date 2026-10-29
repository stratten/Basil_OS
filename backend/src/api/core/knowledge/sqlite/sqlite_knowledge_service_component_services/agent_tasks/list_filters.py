"""Shared sidebar filters for the Agent Task list and search queries (read-only SQL builders)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, FrozenSet, List, Optional, Tuple

from api.core.knowledge.sqlite.filter_time import utc_text

# Statuses that mean a chain is still running or waiting on someone; the "active" status filter value matches these.
ACTIVE_STATUSES: FrozenSet[str] = frozenset({
    "capturing", "routing", "processing", "awaiting_user_input",
    "awaiting_provider_delegation", "awaiting_delegated_agents",
    "needs_clarification", "paused",
})

ACTIVE_STATUS_FILTER = "active"

# Source filter values accepted by the list and search routes.
SOURCE_DIRECT = "direct"
SOURCE_CONVERSATION = "conversation"
SOURCE_TODO = "todo"
SOURCE_MEETING = "meeting"
SOURCE_SCHEDULED = "scheduled"
SOURCE_FILTERS: Tuple[str, ...] = (
    SOURCE_DIRECT,
    SOURCE_CONVERSATION,
    SOURCE_TODO,
    SOURCE_MEETING,
    SOURCE_SCHEDULED,
)

# Last activity of a chain, the same field the list is sorted by.
LAST_ACTIVITY_SQL = "COALESCE(root.last_turn_timestamp, root.timestamp)"
STATUS_SQL = "COALESCE(root.latest_status, root.status)"


@dataclass(frozen=True)
class AgentTaskListFilters:
    """Optional narrowing applied on top of a list or search; every field left as None is not applied.

    ``source`` is one of ``SOURCE_FILTERS``. ``status`` is an exact status or ``ACTIVE_STATUS_FILTER``.
    ``app_contains`` is a case-insensitive substring of the application name.
    ``has_documents`` True keeps chains with files and False keeps chains without.
    ``multi_turn`` True keeps chains with follow-ups and False keeps single-turn chains.
    """

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    source: Optional[str] = None
    status: Optional[str] = None
    app_contains: Optional[str] = None
    has_documents: Optional[bool] = None
    multi_turn: Optional[bool] = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _source_condition(source: str) -> str:
    if source == SOURCE_DIRECT:
        return "(root.origin_type IS NULL OR root.origin_type = '')"
    if source == SOURCE_CONVERSATION:
        return "root.origin_type = 'conversation'"
    if source == SOURCE_TODO:
        return "root.origin_type IN ('todo', 'todo_workspace')"
    if source == SOURCE_MEETING:
        return "root.origin_type = 'meeting'"
    if source == SOURCE_SCHEDULED:
        return (
            "(root.origin_type = 'scheduled_task' OR EXISTS ("
            "SELECT 1 FROM scheduled_agent_task_runs sar WHERE sar.agent_task_id = root.id))"
        )
    raise ValueError(f"Unsupported agent task source filter: {source}")


def build_filter_conditions(filters: Optional[AgentTaskListFilters]) -> Tuple[List[str], List[Any]]:
    """Return SQL conditions and their parameters against the ``root`` table alias.

    Both the list and the search query append these, so a filter means the same thing in either view.
    """
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

    if filters.status:
        if filters.status == ACTIVE_STATUS_FILTER:
            placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
            conditions.append(f"{STATUS_SQL} IN ({placeholders})")
            params.extend(sorted(ACTIVE_STATUSES))
        else:
            conditions.append(f"{STATUS_SQL} = ?")
            params.append(filters.status)

    if filters.source:
        conditions.append(_source_condition(filters.source))

    app_text = (filters.app_contains or "").strip().lower()
    if app_text:
        conditions.append("LOWER(COALESCE(root.app_name, '')) LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(app_text)}%")

    if filters.has_documents is not None:
        conditions.append("COALESCE(root.file_count, 0) > 0" if filters.has_documents else "COALESCE(root.file_count, 0) = 0")

    if filters.multi_turn is not None:
        conditions.append("COALESCE(root.follow_up_count, 0) > 0" if filters.multi_turn else "COALESCE(root.follow_up_count, 0) = 0")

    return conditions, params
