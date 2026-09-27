"""Agent task create and status-update operations."""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from api.services.agent_processing.shared.serialization import convert_to_serializable_dict

from ...infrastructure.connection import run_write_transaction_async
from .root_summary import recompute_root_summary, root_task_id_for_agent_task

logger = logging.getLogger(__name__)


async def store_agent_task(
    db_path: str,
    *,
    agent_task_id: str,
    original_prompt: str,
    transcribed_prompt: str,
    display_prompt_markdown: Optional[str] = None,
    app_name: Optional[str] = None,
    window_title: Optional[str] = None,
    screen_text: Optional[str] = None,
    screen_capture_path: Optional[str] = None,
    confidence_score: Optional[float] = None,
    status: str = "processing",
    root_task_id: Optional[str] = None,
    previous_task_id: Optional[str] = None,
    chain_sequence_number: int = 0,
    session_type: Optional[str] = None,
    accumulated_artifacts: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
    origin_type: Optional[str] = None,
    origin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Store a agent_task record."""
    resolved_root_task_id = root_task_id or agent_task_id

    def _body(conn: sqlite3.Connection) -> Dict[str, Any]:
        conn.execute(
            """
            INSERT INTO agent_tasks (
                id, timestamp, original_prompt, transcribed_prompt, display_prompt_markdown,
                app_name, window_title, screen_text, screen_capture_path,
                confidence_score, status, operation_parameters, result_data, clarifications,
                root_task_id, previous_task_id,
                chain_sequence_number, session_type, accumulated_artifacts,
                title, origin_type, origin_id
            ) VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_task_id,
                original_prompt,
                transcribed_prompt,
                display_prompt_markdown,
                app_name,
                window_title,
                screen_text,
                screen_capture_path,
                confidence_score,
                status,
                "{}",
                "{}",
                "[]",
                resolved_root_task_id,
                previous_task_id,
                chain_sequence_number,
                session_type,
                json.dumps(accumulated_artifacts) if accumulated_artifacts else "{}",
                title,
                origin_type,
                origin_id,
            ),
        )
        recompute_root_summary(conn, resolved_root_task_id)
        logger.info("Stored agent_task %s with status '%s'", agent_task_id, status)
        return {
            "id": agent_task_id,
            "timestamp": datetime.now().isoformat(),
            "original_prompt": original_prompt,
            "transcribed_prompt": transcribed_prompt,
            "display_prompt_markdown": display_prompt_markdown,
            "app_name": app_name,
            "window_title": window_title,
            "screen_text": screen_text,
            "screen_capture_path": screen_capture_path,
            "confidence_score": confidence_score,
            "status": status,
            "operation_parameters": {},
            "result_data": {},
            "clarifications": [],
            "root_task_id": resolved_root_task_id,
            "previous_task_id": previous_task_id,
            "chain_sequence_number": chain_sequence_number,
            "origin_type": origin_type,
            "origin_id": origin_id,
            "updated_at": datetime.now().isoformat(),
        }

    return await run_write_transaction_async(db_path, "store_agent_task", _body)


async def update_agent_task_status(
    db_path: str,
    *,
    agent_task_id: str,
    status: str,
    operation_parameters: Optional[Dict[str, Any]] = None,
    result_data: Optional[Dict[str, Any]] = None,
    accumulated_artifacts: Optional[Dict[str, Any]] = None,
) -> None:
    """Update the status and result data of a agent_task."""

    def _body(conn: sqlite3.Connection) -> None:
        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [status]

        if operation_parameters is not None:
            updates.append("operation_parameters = ?")
            params.append(json.dumps(convert_to_serializable_dict(operation_parameters)))

        if result_data is not None:
            updates.append("result_data = ?")
            params.append(json.dumps(convert_to_serializable_dict(result_data)))

        if accumulated_artifacts is not None:
            updates.append("accumulated_artifacts = ?")
            params.append(json.dumps(convert_to_serializable_dict(accumulated_artifacts)))

        params.append(agent_task_id)

        query = f"""
            UPDATE agent_tasks
            SET {', '.join(updates)}
            WHERE id = ?
        """

        conn.execute(query, params)
        root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
        if root_task_id:
            recompute_root_summary(conn, root_task_id)
        logger.info("Updated agent_task %s status to '%s'", agent_task_id, status)
        if operation_parameters:
            logger.debug(
                "AgentTask %s operation parameters: %s",
                agent_task_id,
                operation_parameters,
            )
        if result_data:
            logger.debug(
                "AgentTask %s result data keys: %s",
                agent_task_id,
                list(result_data.keys()),
            )

    await run_write_transaction_async(db_path, "update_agent_task_status", _body)


async def update_agent_task_status_if_active(
    db_path: str,
    *,
    agent_task_id: str,
    status: str,
    operation_parameters: Optional[Dict[str, Any]] = None,
    result_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Update status only when the task has not already reached a terminal state."""

    def _body(conn: sqlite3.Connection) -> bool:
        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [status]
        if operation_parameters is not None:
            updates.append("operation_parameters = ?")
            params.append(json.dumps(convert_to_serializable_dict(operation_parameters)))
        if result_data is not None:
            updates.append("result_data = ?")
            params.append(json.dumps(convert_to_serializable_dict(result_data)))
        params.append(agent_task_id)
        cursor = conn.execute(
            f"""
                UPDATE agent_tasks
                SET {', '.join(updates)}
                WHERE id = ?
                  AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            params,
        )
        changed = cursor.rowcount > 0
        if changed:
            root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
            if root_task_id:
                recompute_root_summary(conn, root_task_id)
            logger.info("Conditionally updated agent_task %s status to '%s'", agent_task_id, status)
        return changed

    return await run_write_transaction_async(
        db_path,
        "update_agent_task_status_if_active",
        _body,
    )


async def cancel_agent_tasks_if_active(
    db_path: str,
    *,
    agent_task_ids: list[str],
    result_data: Dict[str, Any],
) -> list[str]:
    """Atomically mark every named nonterminal Agent Task as cancelled."""
    normalized_ids = list(dict.fromkeys(agent_task_id for agent_task_id in agent_task_ids if agent_task_id))
    if not normalized_ids:
        return []

    def _body(conn: sqlite3.Connection) -> list[str]:
        placeholders = ", ".join("?" for _ in normalized_ids)
        active_rows = conn.execute(
            f"""
                SELECT id
                FROM agent_tasks
                WHERE id IN ({placeholders})
                  AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            normalized_ids,
        ).fetchall()
        changed_ids = [str(row[0]) for row in active_rows]
        if not changed_ids:
            return []

        changed_placeholders = ", ".join("?" for _ in changed_ids)
        serialized_result = json.dumps(convert_to_serializable_dict(result_data))
        conn.execute(
            f"""
                UPDATE agent_tasks
                SET status = 'cancelled',
                    result_data = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({changed_placeholders})
                  AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            [serialized_result, *changed_ids],
        )
        root_task_ids = {
            root_task_id
            for changed_id in changed_ids
            if (root_task_id := root_task_id_for_agent_task(conn, changed_id))
        }
        for root_task_id in root_task_ids:
            recompute_root_summary(conn, root_task_id)
        logger.info("Atomically cancelled %s Agent Tasks", len(changed_ids))
        return changed_ids

    return await run_write_transaction_async(
        db_path,
        "cancel_agent_tasks_if_active",
        _body,
    )
