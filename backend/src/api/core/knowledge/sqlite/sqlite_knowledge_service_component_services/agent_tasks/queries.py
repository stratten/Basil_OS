"""AgentTask query operations (read-only) for SQLite."""

import json
import logging
import re
import sqlite3

from ..infrastructure.connection import get_sync_connection
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable

from ....models import AgentTask

logger = logging.getLogger(__name__)


def _result_severity_for_sidebar(status: Optional[str], result_data: Dict[str, Any]) -> str:
    """Map persisted finalizer outcome to the sidebar status icon semantics.

    This intentionally lives below the route layer so the SQLite service
    does not import a route package while it is being initialized. A partial
    result is a warning, never an error/red-X result.
    """
    envelope = result_data.get("finalizer_result") or result_data.get("final_envelope")
    if not isinstance(envelope, dict):
        nested_data = result_data.get("data")
        envelope = (
            nested_data.get("finalizer_result") or nested_data.get("final_envelope")
            if isinstance(nested_data, dict)
            else None
        )
    payload = envelope.get("result_payload") if isinstance(envelope, dict) else result_data.get("result_payload")
    outcome = payload.get("outcome", "").strip().lower() if isinstance(payload, dict) else ""
    if outcome == "partial":
        return "warning"
    if outcome == "completed_with_warnings" or outcome == "success":
        return "success"
    if outcome == "failure" or (status or "").strip().lower() == "failed":
        return "error"
    if (status or "").strip().lower() == "completed":
        return "success"
    return "neutral"


class AgentTaskQueries:
    """Handles all agent_task read/query operations."""
    
    def __init__(self, db_path: str, row_mapper: Callable):
        """Initialize the queries service.
        
        Args:
            db_path: Path to the SQLite database.
            row_mapper: Function to convert database rows to AgentTask objects.
        """
        self.db_path = db_path
        self._row_to_agent_task = row_mapper
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper configuration."""
        return get_sync_connection(self.db_path)
    
    # === Standard SELECT columns for agent_tasks ===
    
    _SELECT_COLUMNS = """
        id, timestamp, original_prompt, transcribed_prompt, display_prompt_markdown,
        app_name, window_title, screen_text, screen_capture_path,
        confidence_score, status, operation_parameters, result_data, clarifications,
        root_task_id, previous_task_id,
        chain_sequence_number, session_type, session_status,
        workflow_plan, current_step, total_planned_steps, completed_steps,
        pending_steps, accumulated_artifacts, last_interaction_timestamp, interaction_count,
        title, origin_type, origin_id, execution_timeline
    """
    
    # === Query Operations ===

    def _parse_timestamp(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    def _parse_result_data(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _row_to_summary(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "original_prompt": row["original_prompt"],
            "title": row["title"],
            "result_preview": row["result_preview"],
            "timestamp": self._parse_timestamp(row["timestamp"]),
            "status": row["status"],
            "file_count": row["file_count"] or 0,
            "app_name": row["app_name"],
            "follow_up_count": row["follow_up_count"] or 0,
            "origin_type": row["origin_type"] if "origin_type" in row.keys() else None,
            "origin_id": row["origin_id"] if "origin_id" in row.keys() else None,
            "result_data": self._parse_result_data(row["result_data"]) if "result_data" in row.keys() else {},
        }

    def _search_tokens(self, query: str) -> List[str]:
        return [token.lower() for token in re.findall(r"[\w]+", query or "")]

    def _format_fts_query(self, query: str) -> str:
        tokens = self._search_tokens(query)
        return " AND ".join(f'"{token}"*' for token in tokens)

    def _escape_like_token(self, token: str) -> str:
        return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    
    async def get_agent_task(self, agent_task_id: str) -> Optional[AgentTask]:
        """Retrieve a agent_task by ID.
        
        Args:
            agent_task_id: The agent task ID to retrieve.
            
        Returns:
            AgentTask object if found, None otherwise.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"SELECT {self._SELECT_COLUMNS} FROM agent_tasks WHERE id = ?",
                (agent_task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_agent_task(row)

    async def get_agent_task_chain(self, root_task_id: str) -> List[AgentTask]:
        """Retrieve all agent tasks in a chain (the parent and all follow-ups).
        
        Args:
            root_task_id: ID of the root task in the chain.
            
        Returns:
            List of AgentTask objects ordered by chain_sequence_number.
        """
        with self._get_connection() as conn:
            # Get all agent tasks in the chain (parent + all agent tasks with this root_task_id)
            cursor = conn.execute(
                f"""
                SELECT {self._SELECT_COLUMNS}
                FROM agent_tasks 
                WHERE id = ?
                   OR root_task_id = ?
                ORDER BY chain_sequence_number ASC
                """,
                (root_task_id, root_task_id)
            )
            rows = cursor.fetchall()
            
            return [self._row_to_agent_task(row) for row in rows]

    async def get_follow_up_counts(self, agent_task_ids: List[str]) -> Dict[str, int]:
        """Get the count of follow-up agent tasks for a list of parent agent task IDs.
        
        Args:
            agent_task_ids: List of agent task IDs to get follow-up counts for.
            
        Returns:
            Dictionary mapping agent_task_id to follow-up count.
        """
        if not agent_task_ids:
            return {}
            
        with self._get_connection() as conn:
            # Build placeholders for IN clause
            placeholders = ",".join("?" * len(agent_task_ids))
            cursor = conn.execute(
                f"""
                SELECT COALESCE(root_task_id, id) AS root_id, COUNT(*) as count
                FROM agent_tasks 
                WHERE COALESCE(root_task_id, id) IN ({placeholders})
                  AND id != COALESCE(root_task_id, id)
                GROUP BY root_id
                """,
                agent_task_ids
            )
            
            return {row[0]: row[1] for row in cursor.fetchall()}

    async def list_recent_agent_tasks(
        self,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[str] = None
    ) -> List[AgentTask]:
        """List recent agent_tasks ordered by timestamp descending.
        
        Args:
            limit: Maximum number of agent tasks to return (default 50).
            offset: Number of agent tasks to skip for pagination (default 0).
            status_filter: Optional status to filter by (e.g., 'completed').
            
        Returns:
            List of AgentTask objects ordered by timestamp DESC.
        """
        with self._get_connection() as conn:
            # Build query with optional status filter
            # Only show root tasks to avoid duplicating follow-ups.
            order_expr = """COALESCE(
                        (SELECT MAX(fu.timestamp)
                         FROM agent_tasks fu
                         WHERE COALESCE(fu.root_task_id, fu.id) = agent_tasks.id
                           AND fu.id != agent_tasks.id),
                        agent_tasks.timestamp
                    ) DESC"""
            if status_filter:
                cursor = conn.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM agent_tasks 
                    WHERE status = ? AND COALESCE(root_task_id, id) = id
                    ORDER BY {order_expr}
                    LIMIT ? OFFSET ?
                    """,
                    (status_filter, limit, offset)
                )
            else:
                cursor = conn.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM agent_tasks 
                    WHERE COALESCE(root_task_id, id) = id
                    ORDER BY {order_expr}
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset)
                )
            
            rows = cursor.fetchall()
            agent_tasks = [self._row_to_agent_task(row) for row in rows]
            
            logger.info(f"Retrieved {len(agent_tasks)} recent agent_tasks (limit={limit}, offset={offset}, status_filter={status_filter})")
            return agent_tasks

    async def list_recent_agent_task_summaries(
        self,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List root task summaries using only denormalized sidebar fields."""
        conditions: List[str] = ["COALESCE(root.root_task_id, root.id) = root.id"]
        params: List[Any] = []

        if status_filter:
            conditions.append("COALESCE(root.latest_status, root.status) = ?")
            params.append(status_filter)

        params.extend([limit, offset])
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT
                    root.id,
                    root.original_prompt,
                    root.title,
                    root.result_preview,
                    COALESCE(root.last_turn_timestamp, root.timestamp) AS timestamp,
                    COALESCE(root.latest_status, root.status) AS status,
                    COALESCE(root.file_count, 0) AS file_count,
                    root.app_name,
                    root.origin_type,
                    root.origin_id,
                    COALESCE(root.follow_up_count, 0) AS follow_up_count,
                    latest.result_data AS result_data
                FROM agent_tasks root
                LEFT JOIN agent_tasks latest ON latest.id = COALESCE(root.latest_agent_task_id, root.id)
                WHERE {" AND ".join(conditions)}
                ORDER BY COALESCE(root.last_turn_timestamp, root.timestamp) DESC
                LIMIT ? OFFSET ?
                """,
                params
            )
            summaries = [self._row_to_summary(row) for row in cursor.fetchall()]
            logger.info(f"Retrieved {len(summaries)} agent_task summaries (limit={limit}, offset={offset}, status_filter={status_filter})")
            return summaries

    async def list_recent_conversation_task_summaries(
        self,
        conversation_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Return recent terminal root summaries owned by one Conversation only."""
        normalized_conversation_id = conversation_id.strip()
        if not normalized_conversation_id:
            raise ValueError("conversation_id must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        terminal_statuses = ("completed", "failed", "cancelled")
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    root.id,
                    root.original_prompt,
                    root.display_prompt_markdown,
                    root.title,
                    root.result_preview,
                    COALESCE(root.last_turn_timestamp, root.timestamp) AS timestamp,
                    COALESCE(root.latest_status, root.status) AS status,
                    COALESCE(root.latest_agent_task_id, root.id) AS latest_agent_task_id,
                    root.origin_type,
                    root.origin_id
                FROM agent_tasks root
                WHERE COALESCE(root.root_task_id, root.id) = root.id
                  AND root.origin_type = 'conversation'
                  AND root.origin_id = ?
                  AND COALESCE(root.latest_status, root.status) IN (?, ?, ?)
                ORDER BY COALESCE(root.last_turn_timestamp, root.timestamp) DESC, root.id DESC
                LIMIT ?
                """,
                (normalized_conversation_id, *terminal_statuses, limit),
            )
            return [
                {
                    "root_task_id": row["id"],
                    "previous_task_id": row["latest_agent_task_id"],
                    "request_text": row["display_prompt_markdown"] or row["original_prompt"],
                    "outcome_text": row["result_preview"] or "",
                    "status": row["status"],
                }
                for row in cursor.fetchall()
            ]

    async def list_active_agent_tasks(self) -> List[AgentTask]:
        """List all currently active/processing agent_tasks.
        
        Active agent tasks are those with status in ('routing', 'processing', 'awaiting_user_input').
        These represent agents that are currently running or waiting for user input.
        
        Returns:
            List of AgentTask objects for active agent tasks, ordered by timestamp DESC.
        """
        active_statuses = ('routing', 'processing', 'awaiting_user_input')
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT {self._SELECT_COLUMNS}
                FROM agent_tasks 
                WHERE status IN (?, ?, ?)
                ORDER BY timestamp DESC
                """,
                active_statuses
            )
            
            rows = cursor.fetchall()
            agent_tasks = [self._row_to_agent_task(row) for row in rows]
            
            logger.info(f"Retrieved {len(agent_tasks)} active agent_tasks")
            return agent_tasks

    async def search_agent_tasks(
        self,
        query: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        status: Optional[str] = None,
        app_name: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[AgentTask]:
        """Search for agent_tasks with text search and filtering.
        
        Args:
            query: Text to search for in original_prompt and transcribed_prompt.
            start_date: Start date for filtering.
            end_date: End date for filtering.
            status: Filter by status (e.g., 'completed', 'failed').
            app_name: Filter by application name.
            limit: Maximum number of results to return (default 50).
            offset: Number of results to skip for pagination (default 0).
            
        Returns:
            List of matching AgentTask objects ordered by timestamp DESC.
        """
        conditions: List[str] = ["COALESCE(root_task_id, id) = id"]  # Only root tasks
        params: List[Any] = []
        
        if query:
            # Search in both original_prompt and transcribed_prompt
            conditions.append("(original_prompt LIKE ? OR transcribed_prompt LIKE ?)")
            params.append(f"%{query}%")
            params.append(f"%{query}%")
        
        if start_date:
            conditions.append("timestamp >= ?")
            params.append(start_date.isoformat())
        
        if end_date:
            conditions.append("timestamp <= ?")
            params.append(end_date.isoformat())
        
        if status:
            conditions.append("status = ?")
            params.append(status)
        
        if app_name:
            conditions.append("app_name = ?")
            params.append(app_name)
        
        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])
        
        with self._get_connection() as conn:
            order_expr = """COALESCE(
                        (SELECT MAX(fu.timestamp)
                         FROM agent_tasks fu
                         WHERE COALESCE(fu.root_task_id, fu.id) = agent_tasks.id
                           AND fu.id != agent_tasks.id),
                        agent_tasks.timestamp
                    ) DESC"""
            cursor = conn.execute(
                f"""
                SELECT {self._SELECT_COLUMNS}
                FROM agent_tasks 
                WHERE {where_clause}
                ORDER BY {order_expr}
                LIMIT ? OFFSET ?
                """,
                params
            )
            
            rows = cursor.fetchall()
            agent_tasks = [self._row_to_agent_task(row) for row in rows]
            
            logger.info(f"AgentTask search returned {len(agent_tasks)} results (query={query}, status={status}, app={app_name}, limit={limit})")
            return agent_tasks

    async def search_agent_task_summaries(
        self,
        query: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        status: Optional[str] = None,
        app_name: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Search root task summaries using the maintained FTS document."""
        if not query or not query.strip():
            return await self.list_recent_agent_task_summaries(limit, offset, status)

        search_tokens = self._search_tokens(query)
        fts_query = self._format_fts_query(query)
        if not fts_query or not search_tokens:
            return await self.list_recent_agent_task_summaries(limit, offset, status)

        like_params = [f"%{self._escape_like_token(token)}%" for token in search_tokens]
        substring_conditions = [
            "LOWER(content) LIKE ? ESCAPE '\\'"
            for _ in search_tokens
        ]
        tier1_conditions = [
            "LOWER(COALESCE(root.title, '') || ' ' || COALESCE(root.original_prompt, '')) LIKE ? ESCAPE '\\'"
            for _ in search_tokens
        ]
        tier2_conditions = [
            "LOWER(COALESCE(root.result_preview, '') || ' ' || COALESCE(latest.result_data, '')) LIKE ? ESCAPE '\\'"
            for _ in search_tokens
        ]
        params: List[Any] = [fts_query, *like_params, *like_params, *like_params]

        conditions: List[str] = []

        if start_date:
            conditions.append("COALESCE(root.last_turn_timestamp, root.timestamp) >= ?")
            params.append(start_date.isoformat())

        if end_date:
            conditions.append("COALESCE(root.last_turn_timestamp, root.timestamp) <= ?")
            params.append(end_date.isoformat())

        if status:
            conditions.append("COALESCE(root.latest_status, root.status) = ?")
            params.append(status)

        if app_name:
            conditions.append("root.app_name = ?")
            params.append(app_name)

        params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                WITH search_matches AS (
                    SELECT root_task_id
                    FROM agent_task_search_fts
                    WHERE agent_task_search_fts MATCH ?
                    UNION
                    SELECT root_task_id
                    FROM agent_task_search_fts
                    WHERE {" AND ".join(substring_conditions)}
                )
                SELECT
                    root.id,
                    root.original_prompt,
                    root.title,
                    root.result_preview,
                    COALESCE(root.last_turn_timestamp, root.timestamp) AS timestamp,
                    COALESCE(root.latest_status, root.status) AS status,
                    COALESCE(root.file_count, 0) AS file_count,
                    root.app_name,
                    root.origin_type,
                    root.origin_id,
                    COALESCE(root.follow_up_count, 0) AS follow_up_count,
                    latest.result_data AS result_data,
                    CASE
                        WHEN {" AND ".join(tier1_conditions)} THEN 1
                        WHEN {" AND ".join(tier2_conditions)} THEN 2
                        ELSE 3
                    END AS match_tier
                FROM search_matches
                JOIN agent_tasks root ON root.id = search_matches.root_task_id
                LEFT JOIN agent_tasks latest ON latest.id = COALESCE(root.latest_agent_task_id, root.id)
                {"WHERE " + " AND ".join(conditions) if conditions else ""}
                ORDER BY match_tier ASC, COALESCE(root.last_turn_timestamp, root.timestamp) DESC
                LIMIT ? OFFSET ?
                """,
                params
            )
            summaries = [self._row_to_summary(row) for row in cursor.fetchall()]
            logger.info(f"AgentTask summary search returned {len(summaries)} results (query={query}, status={status}, app={app_name}, limit={limit})")
            return summaries

    async def get_last_activity_timestamps(self, agent_task_ids: List[str]) -> Dict[str, datetime]:
        """Get the most recent follow-up timestamp for a list of root agent task IDs.
        
        Args:
            agent_task_ids: List of root agent task IDs to check.
            
        Returns:
            Dictionary mapping agent_task_id to its latest follow-up timestamp.
            Only includes entries where follow-ups exist.
        """
        if not agent_task_ids:
            return {}
            
        with self._get_connection() as conn:
            placeholders = ",".join("?" * len(agent_task_ids))
            cursor = conn.execute(
                f"""
                SELECT COALESCE(root_task_id, id) AS root_id, MAX(timestamp) as last_activity
                FROM agent_tasks 
                WHERE COALESCE(root_task_id, id) IN ({placeholders})
                  AND id != COALESCE(root_task_id, id)
                GROUP BY root_id
                """,
                agent_task_ids
            )
            
            result = {}
            for row in cursor.fetchall():
                ts = row[1]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                result[row[0]] = ts
            return result

    async def list_agent_tasks_by_origin(
        self, origin_type: str, origin_id: str, include_terminal: bool = True
    ) -> List[AgentTask]:
        """Return every Agent Task with this exact origin, oldest first.

        Uses the existing `idx_agent_tasks_conversation_roots` index
        (confirmed in `schema.py`: `CREATE INDEX IF NOT EXISTS
        idx_agent_tasks_conversation_roots ON agent_tasks(origin_type,
        origin_id, last_turn_timestamp DESC)`) as an equality-filter prefix
        on `(origin_type, origin_id)`; this query's own `ORDER BY timestamp
        ASC, id ASC` is satisfied by a sort step rather than the index's
        trailing `last_turn_timestamp DESC` column. `include_terminal=False`
        restricts to the same nonterminal-status set used for startup
        recovery.
        """
        conn = self._get_connection()
        try:
            if include_terminal:
                rows = conn.execute(
                    f"SELECT {self._SELECT_COLUMNS} FROM agent_tasks "
                    "WHERE origin_type = ? AND origin_id = ? ORDER BY timestamp ASC, id ASC",
                    (origin_type, origin_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {self._SELECT_COLUMNS} FROM agent_tasks "
                    "WHERE origin_type = ? AND origin_id = ? "
                    "AND status NOT IN ('completed', 'failed', 'cancelled') "
                    "ORDER BY timestamp ASC, id ASC",
                    (origin_type, origin_id),
                ).fetchall()
            return [self._row_to_agent_task(row) for row in rows]
        finally:
            conn.close()

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str) -> List[AgentTask]:
        """Startup-recovery query: every nonterminal Agent Task with this
        origin type, across all origin ids, oldest first."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                f"SELECT {self._SELECT_COLUMNS} FROM agent_tasks "
                "WHERE origin_type = ? "
                "AND status NOT IN ('completed', 'failed', 'cancelled') "
                "ORDER BY timestamp ASC, id ASC",
                (origin_type,),
            ).fetchall()
            return [self._row_to_agent_task(row) for row in rows]
        finally:
            conn.close()

    async def list_agent_task_origin_ids_by_origin_type(self, origin_type: str) -> List[str]:
        """Return distinct nonblank origin ids for one provenance type.

        Startup reconciliation uses this to include terminal attempts whose
        terminal database event was written just before a process restart.
        """
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT origin_id
                FROM agent_tasks
                WHERE origin_type = ? AND origin_id IS NOT NULL AND origin_id != ''
                """,
                (origin_type,),
            ).fetchall()
            return [str(row["origin_id"]) for row in rows]
        finally:
            conn.close()

    _NONTERMINAL_STATUSES = frozenset({
        "capturing", "routing", "processing", "awaiting_user_input",
        "awaiting_provider_delegation", "awaiting_delegated_agents",
        "needs_clarification", "paused",
    })

    async def list_latest_agent_task_status_by_origins(
        self, origin_type: str, origin_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Return the single most-relevant Agent Task status per origin id.

        Uses the same `idx_agent_tasks_conversation_roots(origin_type,
        origin_id, last_turn_timestamp DESC)` index as
        `list_agent_tasks_by_origin` as an equality-filter prefix on
        `(origin_type, origin_id)`. A currently non-terminal attempt always
        outranks a terminal one for the same origin, even if the terminal
        one is more recent (e.g. a completed follow-up sibling task should
        not hide an in-progress worker); among attempts of the same
        terminal-ness, the most recently updated one wins.

        Returns a dict keyed by origin_id, each value shaped as
        `{"agent_task_id": str, "status": str, "result_severity": str | None,
        "is_active": bool, "updated_at": str}`. Origin ids with no Agent
        Task at all are simply absent from the returned dict.
        """
        if not origin_ids:
            return {}
        placeholders = ",".join("?" * len(origin_ids))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT task.id, root.origin_id, task.status, task.result_data,
                       COALESCE(task.last_interaction_timestamp, task.updated_at, task.timestamp) AS updated_at
                FROM agent_tasks AS task
                JOIN agent_tasks AS root ON root.id = COALESCE(task.root_task_id, task.id)
                WHERE root.origin_type = ? AND root.origin_id IN ({placeholders})
                ORDER BY updated_at ASC
                """,
                (origin_type, *origin_ids),
            ).fetchall()
        best_by_origin: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            origin_id = str(row["origin_id"])
            is_active = row["status"] in self._NONTERMINAL_STATUSES
            result_data = self._parse_result_data(row["result_data"])
            result_severity = _result_severity_for_sidebar(row["status"], result_data)
            candidate = {
                "agent_task_id": row["id"],
                "status": row["status"],
                "result_severity": result_severity,
                "is_active": is_active,
                "updated_at": str(row["updated_at"]),
            }
            existing = best_by_origin.get(origin_id)
            if existing is None or is_active or not existing["is_active"]:
                best_by_origin[origin_id] = candidate
        return best_by_origin
