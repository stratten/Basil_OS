"""Scheduled agent task persistence repository for the SQLite knowledge service.

This is the data-access layer (repository) for the scheduled-agent-tasks feature.
It owns nothing but row-level CRUD/query helpers against the
``scheduled_agent_tasks`` and ``scheduled_agent_task_runs`` tables. All scheduling
logic, next-run computation, LLM-driven prompt interpretation, Huey enqueue,
and orchestration live one layer up in
``api.services.scheduled_agent_tasks.scheduled_agent_task_service.ScheduledAgentTaskService``.

The class was previously named ``ScheduledAgentTaskService`` and lived next to
the orchestrator service of the same name, which made stack traces, imports,
and casual reading needlessly ambiguous. It is now ``ScheduledAgentTaskRepository``
to match its actual role.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from ..infrastructure.connection import run_in_worker_thread, get_sync_connection
import uuid
from typing import Any, Dict, List, Optional
from api.core.utc_time import utc_now_naive_iso

logger = logging.getLogger(__name__)


class ScheduledAgentTaskRepository:
    """CRUD/query helpers for scheduled agent tasks and scheduled run history."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        return get_sync_connection(self.db_path)

    @staticmethod
    def _serialize_config(config: Dict[str, Any]) -> str:
        return json.dumps(config or {})

    @staticmethod
    def _decode_config_json(raw: Optional[str]) -> Dict[str, Any]:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    @staticmethod
    def _serialize_reference_paths(paths: Optional[List[str]]) -> str:
        # Always store a JSON array; ``None`` collapses to ``[]`` so downstream
        # callers can treat the field as a non-nullable list of strings.
        return json.dumps(list(paths or []))

    @staticmethod
    def _decode_reference_paths(raw: Optional[str]) -> List[str]:
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except Exception:
            return []
        if not isinstance(decoded, list):
            return []
        return [str(item) for item in decoded if isinstance(item, str)]

    @staticmethod
    def _serialize_connection_ids(connection_ids: Optional[List[str]]) -> str:
        # Same shape as the reference paths: always a JSON array of unique, non-empty ids in the order given.
        cleaned = [str(item).strip() for item in (connection_ids or []) if isinstance(item, str) and str(item).strip()]
        return json.dumps(list(dict.fromkeys(cleaned)))

    @staticmethod
    def _row_to_scheduled_agent_task(row: sqlite3.Row) -> Dict[str, Any]:
        row_keys = row.keys()
        reference_paths_raw = row["reference_paths"] if "reference_paths" in row_keys else None
        connection_ids_raw = row["connection_ids"] if "connection_ids" in row_keys else None
        return {
            "id": row["id"],
            "title": row["title"],
            "agent_task_text": row["agent_task_text"],
            "schedule_type": row["schedule_type"],
            "schedule_config": ScheduledAgentTaskRepository._decode_config_json(row["schedule_config"]),
            "timezone": row["timezone"],
            "is_active": bool(row["is_active"]),
            "source_type": row["source_type"],
            "reference_paths": ScheduledAgentTaskRepository._decode_reference_paths(reference_paths_raw),
            "connection_ids": ScheduledAgentTaskRepository._decode_reference_paths(connection_ids_raw),
            "model_id": (row["model_id"] if "model_id" in row_keys else None) or None,
            "next_run_at": row["next_run_at"],
            "last_run_at": row["last_run_at"],
            "last_status": row["last_status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "run_count": row["run_count"] if "run_count" in row_keys else 0,
            "last_scheduled_for": row["last_scheduled_for"] if "last_scheduled_for" in row_keys else None,
        }

    @staticmethod
    def _row_to_scheduled_run(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "scheduled_agent_task_id": row["scheduled_agent_task_id"],
            "agent_task_id": row["agent_task_id"],
            "scheduled_for": row["scheduled_for"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "status": row["status"],
            "error_message": row["error_message"],
            "notice": row["notice"] if "notice" in row.keys() else None,
            "created_at": row["created_at"],
        }

    async def create_scheduled_agent_task(
        self,
        title: str,
        agent_task_text: str,
        schedule_type: str,
        schedule_config: Dict[str, Any],
        timezone: str,
        next_run_at: Optional[str],
        source_type: str = "manual",
        is_active: bool = True,
        reference_paths: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        scheduled_agent_task_id = str(uuid.uuid4())
        await self._execute_write(
            """
            INSERT INTO scheduled_agent_tasks (
                id, title, agent_task_text, schedule_type, schedule_config,
                timezone, is_active, source_type, reference_paths, connection_ids, model_id, next_run_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scheduled_agent_task_id,
                title,
                agent_task_text,
                schedule_type,
                self._serialize_config(schedule_config),
                timezone,
                1 if is_active else 0,
                source_type,
                self._serialize_reference_paths(reference_paths),
                self._serialize_connection_ids(connection_ids),
                (model_id or "").strip() or None,
                next_run_at,
            ),
        )
        created = await self.get_scheduled_agent_task(scheduled_agent_task_id)
        if not created:
            raise RuntimeError("Failed to load created scheduled agent task")
        return created

    @run_in_worker_thread
    def get_scheduled_agent_task(self, scheduled_agent_task_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    sc.*,
                    COUNT(scr.id) AS run_count,
                    MAX(scr.scheduled_for) AS last_scheduled_for
                FROM scheduled_agent_tasks sc
                LEFT JOIN scheduled_agent_task_runs scr
                    ON scr.scheduled_agent_task_id = sc.id
                WHERE sc.id = ?
                GROUP BY sc.id
                """,
                (scheduled_agent_task_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_scheduled_agent_task(row)

    @run_in_worker_thread
    def list_scheduled_agent_tasks(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        where_clause = ""
        params: List[Any] = []
        if not include_inactive:
            where_clause = "WHERE sc.is_active = 1"
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    sc.*,
                    COUNT(scr.id) AS run_count,
                    MAX(scr.scheduled_for) AS last_scheduled_for
                FROM scheduled_agent_tasks sc
                LEFT JOIN scheduled_agent_task_runs scr
                    ON scr.scheduled_agent_task_id = sc.id
                {where_clause}
                GROUP BY sc.id
                ORDER BY sc.updated_at DESC
                """,
                params,
            ).fetchall()
        return [self._row_to_scheduled_agent_task(row) for row in rows]

    async def update_scheduled_agent_task(
        self,
        scheduled_agent_task_id: str,
        *,
        title: Optional[str] = None,
        agent_task_text: Optional[str] = None,
        schedule_type: Optional[str] = None,
        schedule_config: Optional[Dict[str, Any]] = None,
        timezone: Optional[str] = None,
        is_active: Optional[bool] = None,
        next_run_at: Optional[str] = None,
        clear_next_run_at: bool = False,
        last_status: Optional[str] = None,
        last_run_at: Optional[str] = None,
        reference_paths: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        # ``next_run_at=None`` is treated as "do not touch this column" so
        # callers that pass partial updates don't accidentally wipe the
        # next-run timestamp. To actually clear it (e.g. after a one-time
        # schedule completes successfully, or when toggling a schedule
        # inactive), pass ``clear_next_run_at=True``. ``next_run_at`` and
        # ``clear_next_run_at`` are mutually exclusive: if both are set,
        # the explicit value wins.
        updates: List[str] = ["updated_at = CURRENT_TIMESTAMP"]
        params: List[Any] = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if agent_task_text is not None:
            updates.append("agent_task_text = ?")
            params.append(agent_task_text)
        if schedule_type is not None:
            updates.append("schedule_type = ?")
            params.append(schedule_type)
        if schedule_config is not None:
            updates.append("schedule_config = ?")
            params.append(self._serialize_config(schedule_config))
        if timezone is not None:
            updates.append("timezone = ?")
            params.append(timezone)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
        if next_run_at is not None:
            updates.append("next_run_at = ?")
            params.append(next_run_at)
        elif clear_next_run_at:
            updates.append("next_run_at = NULL")
        if last_status is not None:
            updates.append("last_status = ?")
            params.append(last_status)
        if last_run_at is not None:
            updates.append("last_run_at = ?")
            params.append(last_run_at)
        if reference_paths is not None:
            updates.append("reference_paths = ?")
            params.append(self._serialize_reference_paths(reference_paths))
        if connection_ids is not None:
            # ``None`` leaves the stored ids alone; an empty list clears every tag.
            updates.append("connection_ids = ?")
            params.append(self._serialize_connection_ids(connection_ids))
        if model_id is not None:
            # ``None`` leaves the stored model alone; an empty string clears it back to the default model.
            updates.append("model_id = ?")
            params.append(model_id.strip() or None)
        params.append(scheduled_agent_task_id)
        await self._execute_write(
            f"UPDATE scheduled_agent_tasks SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        return await self.get_scheduled_agent_task(scheduled_agent_task_id)

    @run_in_worker_thread
    def delete_scheduled_agent_task(self, scheduled_agent_task_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM scheduled_agent_tasks WHERE id = ?",
                (scheduled_agent_task_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    @run_in_worker_thread
    def _insert_scheduled_run_if_absent(
        self,
        scheduled_agent_task_id: str,
        scheduled_for: str,
        status: str,
        agent_task_id: Optional[str],
    ) -> tuple[Optional[Dict[str, Any]], str]:
        """Return the existing pending run for the slot, or insert a new row; the second element is the new run id."""
        with self._get_connection() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM scheduled_agent_task_runs
                WHERE scheduled_agent_task_id = ?
                  AND scheduled_for = ?
                  AND status IN ('scheduled', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (scheduled_agent_task_id, scheduled_for),
            ).fetchone()
            if existing:
                return self._row_to_scheduled_run(existing), ""

        run_id = str(uuid.uuid4())
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_agent_task_runs (
                    id, scheduled_agent_task_id, agent_task_id, scheduled_for, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, scheduled_agent_task_id, agent_task_id, scheduled_for, status),
            )
            conn.commit()
        return None, run_id

    @run_in_worker_thread
    def _execute_write(self, sql: str, params: Any) -> None:
        """Run one write statement and commit it on a worker thread."""
        with self._get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

    async def create_scheduled_run(
        self,
        scheduled_agent_task_id: str,
        scheduled_for: str,
        status: str = "scheduled",
        agent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing_run, run_id = await self._insert_scheduled_run_if_absent(
            scheduled_agent_task_id, scheduled_for, status, agent_task_id
        )
        if existing_run is not None:
            return existing_run
        run = await self.get_scheduled_run(run_id)
        if not run:
            raise RuntimeError("Failed to load created scheduled run")
        return run

    @run_in_worker_thread
    def get_scheduled_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_agent_task_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_scheduled_run(row)

    async def update_scheduled_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        agent_task_id: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        error_message: Optional[str] = None,
        notice: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        updates: List[str] = []
        params: List[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if agent_task_id is not None:
            updates.append("agent_task_id = ?")
            params.append(agent_task_id)
        if started_at is not None:
            updates.append("started_at = ?")
            params.append(started_at)
        if completed_at is not None:
            updates.append("completed_at = ?")
            params.append(completed_at)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if notice is not None:
            updates.append("notice = ?")
            params.append(notice)
        if not updates:
            return await self.get_scheduled_run(run_id)
        params.append(run_id)
        await self._execute_write(
            f"UPDATE scheduled_agent_task_runs SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        return await self.get_scheduled_run(run_id)

    @run_in_worker_thread
    def claim_scheduled_run(self, run_id: str, started_at: str) -> bool:
        """Atomically move a run from 'scheduled' to 'running'; return False when another caller already claimed or finalized it.

        A separate read of the status followed by a write is not enough, because concurrent callers can all read 'scheduled' before any of them writes.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE scheduled_agent_task_runs SET status = 'running', started_at = ? WHERE id = ? AND status = 'scheduled'",
                (started_at, run_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    @run_in_worker_thread
    def list_runs_for_agent_task(self, scheduled_agent_task_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM scheduled_agent_task_runs
                WHERE scheduled_agent_task_id = ?
                ORDER BY scheduled_for DESC
                LIMIT ?
                """,
                (scheduled_agent_task_id, limit),
            ).fetchall()
        return [self._row_to_scheduled_run(row) for row in rows]

    @run_in_worker_thread
    def list_runs_with_agent_task(self, scheduled_agent_task_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Runs of one schedule, each carrying the status and raw result_data of the agent task it started.

        The agent task is the source of truth for how a run went, so surfaces draw a run from the task and not from the run row's own two-state status.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT scr.*, at.status AS agent_task_status, at.result_data AS agent_task_result_data
                FROM scheduled_agent_task_runs scr
                LEFT JOIN agent_tasks at ON at.id = scr.agent_task_id
                WHERE scr.scheduled_agent_task_id = ?
                ORDER BY scr.scheduled_for DESC
                LIMIT ?
                """,
                (scheduled_agent_task_id, limit),
            ).fetchall()
        return [
            {
                **self._row_to_scheduled_run(row),
                "agent_task_status": row["agent_task_status"],
                "agent_task_result_data": row["agent_task_result_data"],
            }
            for row in rows
        ]

    @run_in_worker_thread
    def list_due_agent_tasks(self, now_iso: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_agent_tasks
                WHERE is_active = 1
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (now_iso,),
            ).fetchall()
        return [self._row_to_scheduled_agent_task(row) for row in rows]

    @run_in_worker_thread
    def list_active_scheduled_agent_tasks(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM scheduled_agent_tasks
                WHERE is_active = 1
                ORDER BY next_run_at ASC, updated_at DESC
                """
            ).fetchall()
        return [self._row_to_scheduled_agent_task(row) for row in rows]

    @run_in_worker_thread
    def list_active_runs(self) -> List[Dict[str, Any]]:
        """Return every scheduled-agent-task run currently in ``running`` status.

        Joined to the parent ``scheduled_agent_tasks`` row so callers (the
        floating mini panel, primarily) can render a meaningful row label
        without a second round-trip. Used to hydrate the panel UI on
        cold-open: the panel may attach (re-render, app re-launch) after
        a run has already started, so it asks "what's already running?"
        and seeds its in-memory state from the answer.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    scr.id              AS run_id,
                    scr.scheduled_agent_task_id,
                    scr.agent_task_id,
                    scr.scheduled_for,
                    scr.started_at,
                    sc.title            AS title,
                    sc.agent_task_text     AS agent_task_text,
                    at.status           AS agent_task_status,
                    at.result_data      AS agent_task_result_data
                FROM scheduled_agent_task_runs scr
                JOIN scheduled_agent_tasks sc ON sc.id = scr.scheduled_agent_task_id
                LEFT JOIN agent_tasks at ON at.id = scr.agent_task_id
                WHERE scr.status = 'running'
                ORDER BY scr.started_at ASC
                """
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "scheduled_agent_task_id": row["scheduled_agent_task_id"],
                "agent_task_id": row["agent_task_id"],
                "scheduled_for": row["scheduled_for"],
                "started_at": row["started_at"],
                "title": row["title"],
                "agent_task_text": row["agent_task_text"],
                "agent_task_status": row["agent_task_status"],
                "agent_task_result_data": row["agent_task_result_data"],
            }
            for row in rows
        ]

    @run_in_worker_thread
    def get_scheduled_run_mapping(self, agent_task_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not agent_task_ids:
            return {}
        placeholders = ",".join("?" * len(agent_task_ids))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    scr.agent_task_id,
                    scr.scheduled_agent_task_id,
                    sc.title AS scheduled_agent_task_title
                FROM scheduled_agent_task_runs scr
                JOIN scheduled_agent_tasks sc ON sc.id = scr.scheduled_agent_task_id
                WHERE scr.agent_task_id IN ({placeholders})
                """,
                agent_task_ids,
            ).fetchall()
        mapping: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            mapping[row["agent_task_id"]] = {
                "scheduled_agent_task_id": row["scheduled_agent_task_id"],
                "scheduled_agent_task_title": row["scheduled_agent_task_title"],
            }
        return mapping

    @run_in_worker_thread
    def mark_missed_runs_before(self, now_iso: str) -> int:
        """Mark old queued/scheduled runs as missed when startup recovery runs."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE scheduled_agent_task_runs
                SET status = 'missed',
                    completed_at = COALESCE(completed_at, ?),
                    error_message = COALESCE(error_message, 'App inactive at scheduled time')
                WHERE status IN ('scheduled', 'running')
                  AND scheduled_for < ?
                """,
                (utc_now_naive_iso(), now_iso),
            )
            conn.commit()
            return cursor.rowcount

    @run_in_worker_thread
    def cancel_pending_runs_for_agent_task(self, scheduled_agent_task_id: str) -> int:
        """Cancel all not-yet-started runs for a scheduled agent task.

        Used by the orchestrator to enforce the "at most one pending run
        per scheduled agent task" invariant: any time we re-enqueue a
        scheduled agent task (initial create, edit, toggle-active, recovery,
        finalize-into-next-occurrence) we first mark all existing
        ``scheduled`` runs as ``canceled`` so the in-process
        ``AsyncScheduledAgentTaskRunner`` finds the run row in a
        non-actionable state on its defensive status re-check inside
        ``execute_scheduled_run`` and skips execution. The runner's own
        ``cancel(scheduled_agent_task_id)`` is invoked alongside this DB
        update so the in-memory ``asyncio.Task`` is also torn down.

        Deliberately scoped to ``status = 'scheduled'`` only:

        * ``running`` runs are mid-execution; we let them complete normally.
          Canceling them mid-flight would leave the voice_listener in an
          inconsistent state (partial agent execution, dangling
          agent_tasks rows) for no benefit.
        * Terminal statuses (``completed``, ``failed``, ``skipped``,
          ``missed``, ``canceled``) are already finalized and don't need
          touching.

        Returns the number of rows transitioned to ``canceled``.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE scheduled_agent_task_runs
                SET status = 'canceled',
                    completed_at = COALESCE(completed_at, ?),
                    error_message = COALESCE(error_message, 'Superseded by reschedule')
                WHERE scheduled_agent_task_id = ?
                  AND status = 'scheduled'
                """,
                (utc_now_naive_iso(), scheduled_agent_task_id),
            )
            conn.commit()
            return cursor.rowcount
