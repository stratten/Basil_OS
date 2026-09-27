"""Row-to-model conversion and defensive JSON parsing for the To-Do domain."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

from api.routes.agent_tasks.utils import derive_result_severity, extract_result_outcome

from .models import TodoAttention, TodoItemDetail, TodoItemSummary, TodoReference, TodoSource, TodoWorkAttempt


def safe_json_object(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def row_to_todo_summary(row: sqlite3.Row) -> TodoItemSummary:
    return TodoItemSummary(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        responsibility=row["responsibility"],
        priority=row["priority"],
        due_at=row["due_at"],
        completed_at=row["completed_at"],
        revision=row["revision"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        attention=TodoAttention(),
    )


def row_to_todo_detail(
    row: sqlite3.Row,
    *,
    source_rows: List[sqlite3.Row],
    reference_rows: List[sqlite3.Row],
    worker_attempts: List[TodoWorkAttempt],
    attention: TodoAttention,
) -> TodoItemDetail:
    summary = row_to_todo_summary(row)
    summary_data = summary.model_dump()
    summary_data.pop("attention", None)
    return TodoItemDetail(
        **summary_data,
        description=row["description"] or "",
        notes=row["notes"] or "",
        idempotency_key=row["idempotency_key"],
        created_by_kind=row["created_by_kind"],
        created_by_id=row["created_by_id"],
        sources=[row_to_todo_source(source_row) for source_row in source_rows],
        references=[row_to_todo_reference(reference_row) for reference_row in reference_rows],
        worker_attempts=worker_attempts,
        attention=attention,
    )


def row_to_todo_source(row: sqlite3.Row) -> TodoSource:
    return TodoSource(
        id=row["id"],
        todo_id=row["todo_id"],
        source_kind=row["source_kind"],
        source_id=row["source_id"],
        source_locator=safe_json_object(row["source_locator_json"]),
        source_excerpt=row["source_excerpt"] or "",
        created_by_kind=row["created_by_kind"],
        created_at=str(row["created_at"]),
    )


def row_to_todo_reference(row: sqlite3.Row) -> TodoReference:
    return TodoReference(
        id=row["id"],
        todo_id=row["todo_id"],
        path=row["path"],
        created_by_kind=row["created_by_kind"],
        created_by_id=row["created_by_id"],
        created_at=str(row["created_at"]),
    )


def agent_task_to_work_attempt(agent_task: Any) -> TodoWorkAttempt:
    """Project the canonical Agent Task model into a read-only work attempt.

    `agent_task` is the existing `AgentTask` model instance returned by
    `AgentTaskService`/`AgentTaskQueries`; only display-relevant fields are
    copied and no new persistence is introduced.
    """
    nonterminal_statuses = {
        "capturing", "routing", "processing", "awaiting_user_input",
        "awaiting_provider_delegation", "awaiting_delegated_agents",
        "needs_clarification", "paused",
    }
    status = getattr(agent_task, "status", "unknown")
    result_data = getattr(agent_task, "result_data", None) or {}
    result_summary = None
    if isinstance(result_data, dict):
        result_summary = result_data.get("message") or result_data.get("error")
    timestamp = getattr(agent_task, "timestamp", None)
    if timestamp is None:
        timestamp_str = ""
    elif hasattr(timestamp, "isoformat"):
        timestamp_str = timestamp.isoformat()
    else:
        timestamp_str = str(timestamp)
    return TodoWorkAttempt(
        agent_task_id=agent_task.id,
        title=getattr(agent_task, "title", None),
        status=status,
        created_at=timestamp_str,
        updated_at=timestamp_str,
        result_summary=result_summary if isinstance(result_summary, str) else None,
        outcome=extract_result_outcome(result_data if isinstance(result_data, dict) else None),
        result_severity=derive_result_severity(status, result_data if isinstance(result_data, dict) else None),
        attention=status in {"needs_clarification", "awaiting_user_input"},
    )
