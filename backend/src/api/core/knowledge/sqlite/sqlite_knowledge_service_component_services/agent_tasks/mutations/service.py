"""AgentTask mutation facade for SQLite."""

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from ...infrastructure.connection import get_sync_connection, get_async_connection

from .....models import AgentTask
from . import context_updates, create_update, revision_repository
from .delete_operations import delete_agent_task
from .mappers import (
    build_agent_task_data_dict,
    row_to_agent_task,
)
from .restart_recovery import (
    mark_interrupted_active_agent_tasks,
)
from .root_summary import (
    append_search_value,
    build_search_document,
    extract_result_preview,
    get_finalizer_envelope,
    get_finalizer_file_count,
    recompute_root_summary,
    root_task_id_for_agent_task,
    safe_json_loads,
)
from .title_generation import generate_heuristic_title


class AgentTaskMutations:
    """Handles all agent_task write operations."""

    def __init__(self, db_path: str):
        """Initialize the mutations service.

        Args:
            db_path: Path to the SQLite database.
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper configuration."""
        return get_sync_connection(self.db_path)

    async def _get_async_connection(self) -> aiosqlite.Connection:
        """Get an async database connection with proper configuration."""
        return await get_async_connection(self.db_path)

    # === Shared Mappers (eliminates 6x duplication) ===

    def row_to_agent_task(self, row) -> AgentTask:
        """Convert a database row to a AgentTask object."""
        return row_to_agent_task(row)

    def build_agent_task_data_dict(self, agent_task: AgentTask) -> Dict[str, Any]:
        """Build a dictionary from a AgentTask for event detection."""
        return build_agent_task_data_dict(agent_task)

    # === Root summary compatibility wrappers ===

    def _safe_json_loads(self, value: Optional[str]) -> Any:
        return safe_json_loads(value)

    def _get_finalizer_envelope(self, result_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return get_finalizer_envelope(result_data)

    def _get_finalizer_file_count(self, result_data: Dict[str, Any]) -> int:
        return get_finalizer_file_count(result_data)

    def _extract_result_preview(self, result_data: Any) -> Tuple[Optional[str], int]:
        return extract_result_preview(result_data)

    def _append_search_value(self, parts: List[str], value: Any) -> None:
        append_search_value(parts, value)

    def _build_search_document(self, rows: List[sqlite3.Row]) -> str:
        return build_search_document(rows)

    def _root_task_id_for_agent_task(self, conn: sqlite3.Connection, agent_task_id: str) -> Optional[str]:
        return root_task_id_for_agent_task(conn, agent_task_id)

    def _recompute_root_summary(self, conn: sqlite3.Connection, root_task_id: str) -> None:
        recompute_root_summary(conn, root_task_id)

    # === Write Operations ===

    async def store_agent_task(
        self,
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
        return await create_update.store_agent_task(
            self.db_path,
            agent_task_id=agent_task_id,
            original_prompt=original_prompt,
            transcribed_prompt=transcribed_prompt,
            display_prompt_markdown=display_prompt_markdown,
            app_name=app_name,
            window_title=window_title,
            screen_text=screen_text,
            screen_capture_path=screen_capture_path,
            confidence_score=confidence_score,
            status=status,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
            chain_sequence_number=chain_sequence_number,
            session_type=session_type,
            accumulated_artifacts=accumulated_artifacts,
            title=title,
            origin_type=origin_type,
            origin_id=origin_id,
        )

    async def update_agent_task_status(
        self,
        agent_task_id: str,
        status: str,
        operation_parameters: Optional[Dict[str, Any]] = None,
        result_data: Optional[Dict[str, Any]] = None,
        accumulated_artifacts: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update the status and result data of a agent_task."""
        await create_update.update_agent_task_status(
            self.db_path,
            agent_task_id=agent_task_id,
            status=status,
            operation_parameters=operation_parameters,
            result_data=result_data,
            accumulated_artifacts=accumulated_artifacts,
        )

    async def update_agent_task_status_if_active(
        self,
        agent_task_id: str,
        status: str,
        operation_parameters: Optional[Dict[str, Any]] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update status only while the Agent Task remains non-terminal."""
        return await create_update.update_agent_task_status_if_active(
            self.db_path,
            agent_task_id=agent_task_id,
            status=status,
            operation_parameters=operation_parameters,
            result_data=result_data,
        )

    async def cancel_agent_tasks_if_active(
        self,
        agent_task_ids: List[str],
        result_data: Dict[str, Any],
    ) -> List[str]:
        """Atomically cancel every named nonterminal Agent Task."""
        return await create_update.cancel_agent_tasks_if_active(
            self.db_path,
            agent_task_ids=agent_task_ids,
            result_data=result_data,
        )

    async def clear_agent_task_execution_timeline(self, agent_task_id: str) -> None:
        """Clear visible execution details before starting a new retry attempt."""
        await context_updates.clear_agent_task_execution_timeline(
            self.db_path,
            agent_task_id,
        )

    async def add_agent_task_clarification(
        self,
        agent_task_id: str,
        clarification_text: str,
        clarification_agent_task: Optional[str] = None,
        current_clarifications: List[Dict[str, Any]] = None
    ) -> None:
        """Add a clarification to a agent_task."""
        await context_updates.add_agent_task_clarification(
            self.db_path,
            agent_task_id=agent_task_id,
            clarification_text=clarification_text,
            clarification_agent_task=clarification_agent_task,
            current_clarifications=current_clarifications,
        )

    async def update_agent_task_screen_context(
        self,
        agent_task_id: str,
        screen_text: Optional[str] = None,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        screen_capture_path: Optional[str] = None
    ) -> None:
        """Update the screen context fields directly in the agent_task record."""
        await context_updates.update_agent_task_screen_context(
            self.db_path,
            agent_task_id=agent_task_id,
            screen_text=screen_text,
            app_name=app_name,
            window_title=window_title,
            screen_capture_path=screen_capture_path,
        )

    async def update_execution_timeline(self, agent_task_id: str, timeline: List[Dict[str, Any]]) -> None:
        """Store the unified execution timeline for a agent_task."""
        await context_updates.update_execution_timeline(
            self.db_path,
            agent_task_id,
            timeline,
        )

    async def upsert_execution_timeline_artifact(
        self,
        agent_task_id: str,
        entry: Dict[str, Any],
        artifact_id: str,
        *,
        revision_capture: Optional[Any] = None,
        local_path: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> bool:
        """Atomically replace one active timeline artifact by stable artifact ID."""
        return await context_updates.upsert_execution_timeline_artifact(
            self.db_path,
            agent_task_id,
            entry,
            artifact_id,
            revision_capture=revision_capture,
            local_path=local_path,
            display_name=display_name,
        )

    async def list_artifact_revisions(
        self,
        agent_task_id: str,
        artifact_id: str,
    ) -> List[Dict[str, Any]]:
        """Return metadata-only revisions for one task-owned artifact."""
        return await revision_repository.list_artifact_revisions(
            self.db_path,
            agent_task_id,
            artifact_id,
        )

    async def get_artifact_revision(
        self,
        agent_task_id: str,
        artifact_id: str,
        revision: int,
    ) -> Optional[Dict[str, Any]]:
        """Return one bounded text snapshot for one task-owned artifact."""
        return await revision_repository.get_artifact_revision(
            self.db_path,
            agent_task_id,
            artifact_id,
            revision,
        )

    async def update_execution_timeline_if_active(
        self, agent_task_id: str, timeline: List[Dict[str, Any]]
    ) -> bool:
        """Store a timeline only while the Agent Task remains non-terminal."""
        return await context_updates.update_execution_timeline_if_active(
            self.db_path,
            agent_task_id,
            timeline,
        )

    async def update_agent_task_title(self, agent_task_id: str, title: str) -> None:
        """Update the generated title for a agent_task."""
        await context_updates.update_agent_task_title(
            self.db_path,
            agent_task_id,
            title,
        )

    async def mark_interrupted_active_agent_tasks(self) -> int:
        """Mark active task rows as failed after a backend restart."""
        return await mark_interrupted_active_agent_tasks(self.db_path)

    async def delete_agent_task(self, agent_task_id: str, cascade: bool = True) -> bool:
        """Delete a agent_task by ID."""
        return await delete_agent_task(self.db_path, agent_task_id, cascade)
