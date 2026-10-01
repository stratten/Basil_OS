"""AgentTask component service for SQLite knowledge service.

This is the public interface - all external code imports from here.
Internally delegates to events, mutations, and queries modules.
"""

import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from ....models import AgentTask
from .events import AgentTaskEvent, AgentTaskEventManager
from .mutations.service import AgentTaskMutations
from .queries import AgentTaskQueries

logger = logging.getLogger(__name__)


class AgentTaskService:
    """Component service for agent_task operations in SQLite.
    
    Orchestrates events, mutations, and queries modules.
    All external code should import from this class.
    """
    
    def __init__(self, db_path: str):
        """Initialize the agent_task service.
        
        Args:
            db_path: Path to the SQLite database.
        """
        self.db_path = db_path
        
        # Compose internal modules
        self._events = AgentTaskEventManager()
        self._mutations = AgentTaskMutations(db_path)
        self._queries = AgentTaskQueries(db_path, self._mutations.row_to_agent_task)
    
    # === Event System (delegated) ===
    
    def register_agent_task_callback(self, callback: Callable[[AgentTaskEvent], None]) -> None:
        """Register a callback to be called when agent_task events occur."""
        return self._events.register_callback(callback)
    
    def unregister_agent_task_callback(self, callback: Callable[[AgentTaskEvent], None]) -> None:
        """Unregister a agent_task callback."""
        return self._events.unregister_callback(callback)
    
    # === Mutations (delegated + event dispatching) ===
    
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
    ) -> str:
        """Store a agent_task record.
        
        Args:
            agent_task_id: Unique identifier for the agent task.
            original_prompt: The raw agent task text.
            transcribed_prompt: The processed/cleaned agent task text.
            app_name: Application where the agent task was issued.
            window_title: Window title where the agent task was issued.
            screen_text: Extracted text from screen capture.
            screen_capture_path: Path to screenshot file.
            confidence_score: Transcription confidence.
            status: Current processing status.
            root_task_id: Stable root task ID for this thread.
            previous_task_id: Immediate predecessor task ID for this turn.
            chain_sequence_number: Position in task chain.
            session_type: Type of session.
            accumulated_artifacts: Artifacts from previous steps.
            title: Generated display title for sidebar.
            origin_type: Provenance surface type (e.g. conversation, scheduled_task).
            origin_id: ID within that surface (e.g. conversation_id).
            
        Returns:
            The agent_task_id that was stored.
        """
        agent_task_data = await self._mutations.store_agent_task(
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
        
        # Detect and dispatch events
        event = self._events.detect_changes(agent_task_id, agent_task_data)
        if event:
            self._events.dispatch_event(event)
        
        return agent_task_id

    async def update_agent_task_status(
        self,
        agent_task_id: str,
        status: str,
        operation_parameters: Optional[Dict[str, Any]] = None,
        result_data: Optional[Dict[str, Any]] = None,
        accumulated_artifacts: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update the status and result data of a agent_task.
        
        Args:
            agent_task_id: The agent task ID to update.
            status: New status (processing, completed, failed, needs_clarification).
            operation_parameters: Parameters used for the operation (optional).
            result_data: Result data from processing (optional).
            accumulated_artifacts: Replaces the durable accumulated_artifacts
                blob when provided (e.g. a retry persisting a model_id
                override). Omitted/`None` leaves it untouched.
        """
        await self._mutations.update_agent_task_status(
            agent_task_id=agent_task_id,
            status=status,
            operation_parameters=operation_parameters,
            result_data=result_data,
            accumulated_artifacts=accumulated_artifacts,
        )

        # Get updated agent-task data for event detection
        updated_agent_task = await self._queries.get_agent_task(agent_task_id)
        if updated_agent_task:
            agent_task_data = self._mutations.build_agent_task_data_dict(updated_agent_task)
            event = self._events.detect_changes(agent_task_id, agent_task_data)
            if event:
                self._events.dispatch_event(event)
            await self._settle_active_work_session(updated_agent_task, status)

    async def update_agent_task_status_if_active(
        self,
        agent_task_id: str,
        status: str,
        operation_parameters: Optional[Dict[str, Any]] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update and dispatch status only while the Agent Task remains non-terminal."""
        changed = await self._mutations.update_agent_task_status_if_active(
            agent_task_id=agent_task_id,
            status=status,
            operation_parameters=operation_parameters,
            result_data=result_data,
        )
        if not changed:
            return False
        updated_agent_task = await self._queries.get_agent_task(agent_task_id)
        if updated_agent_task:
            agent_task_data = self._mutations.build_agent_task_data_dict(updated_agent_task)
            event = self._events.detect_changes(agent_task_id, agent_task_data)
            if event:
                self._events.dispatch_event(event)
            await self._settle_active_work_session(updated_agent_task, status)
        return True

    _TERMINAL_AGENT_TASK_STATUSES = {"completed", "failed", "canceled"}

    async def _settle_active_work_session(self, agent_task: Optional[Any], status: str) -> None:
        """Best-effort: close out a still-open work session when its task ends.

        Never raises and never blocks the status write that already happened;
        an agent that never explicitly finishes its own work session should
        not leave it "active" forever. Uses "partial" (not a
        COMPLETE_SESSION_STATUSES value) for anything short of a clean
        success, so AgentWorkSessionRepository.finish never rejects the
        update over unresolved claimable items.
        """
        if status not in self._TERMINAL_AGENT_TASK_STATUSES or agent_task is None:
            return
        root_task_id = getattr(agent_task, "root_task_id", None) or getattr(agent_task, "id", None)
        if not root_task_id:
            return
        try:
            from ..agent_work.session_repository import AgentWorkSessionRepository

            sessions = AgentWorkSessionRepository(self.db_path)
            session = await sessions.get_latest_session_for_root(root_task_id)
            if not session:
                return
            settled_statuses = (
                AgentWorkSessionRepository.COMPLETE_SESSION_STATUSES
                | AgentWorkSessionRepository.INCOMPLETE_SESSION_STATUSES
            )
            if session.get("status") in settled_statuses:
                return
            final_status = "completed" if status == "completed" else "partial"
            await sessions.finish(session_id=session["id"], status=final_status)
        except Exception as settle_error:  # pragma: no cover - defensive
            logger.warning(
                "Best-effort work-session settle failed for agent_task=%s: %s",
                getattr(agent_task, "id", None),
                settle_error,
            )

    async def cancel_agent_tasks_if_active(
        self,
        agent_task_ids: List[str],
        result_data: Dict[str, Any],
    ) -> List[str]:
        """Atomically cancel named active tasks and dispatch their durable events."""
        changed_ids = await self._mutations.cancel_agent_tasks_if_active(
            agent_task_ids=agent_task_ids,
            result_data=result_data,
        )
        for agent_task_id in changed_ids:
            updated_agent_task = await self._queries.get_agent_task(agent_task_id)
            if not updated_agent_task:
                continue
            agent_task_data = self._mutations.build_agent_task_data_dict(updated_agent_task)
            event = self._events.detect_changes(agent_task_id, agent_task_data)
            if event:
                self._events.dispatch_event(event)
        return changed_ids

    async def add_agent_task_clarification(
        self,
        agent_task_id: str,
        clarification_text: str,
        clarification_agent_task: Optional[str] = None
    ) -> None:
        """Add a clarification to a agent_task.
        
        Args:
            agent_task_id: The AgentTask ID to add clarification to.
            clarification_text: The clarification text from the user.
            clarification_agent_task: Optional agent-task context for processing the clarification.
        """
        # Get current state
        current_agent_task = await self._queries.get_agent_task(agent_task_id)
        if not current_agent_task:
            raise ValueError(f"AgentTask {agent_task_id} not found")
        
        await self._mutations.add_agent_task_clarification(
            agent_task_id=agent_task_id,
            clarification_text=clarification_text,
            clarification_agent_task=clarification_agent_task,
            current_clarifications=current_agent_task.clarifications.copy() if current_agent_task.clarifications else []
        )
        
        # Get updated agent-task data for event detection
        updated_agent_task = await self._queries.get_agent_task(agent_task_id)
        if updated_agent_task:
            agent_task_data = self._mutations.build_agent_task_data_dict(updated_agent_task)
            event = self._events.detect_changes(agent_task_id, agent_task_data)
            if event:
                self._events.dispatch_event(event)
        
        # Also update status to indicate clarification was added (for routing to retry)
        await self.update_agent_task_status(agent_task_id, "clarification_added")

    async def update_agent_task_screen_context(
        self,
        agent_task_id: str,
        screen_text: Optional[str] = None,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        screen_capture_path: Optional[str] = None
    ) -> None:
        """Update the screen context fields directly in the agent_task record.
        
        Args:
            agent_task_id: The agent task ID to update.
            screen_text: The extracted screen text to store.
            app_name: The application name to store.
            window_title: The window title to store.
            screen_capture_path: The captured screenshot path to store.
        """
        await self._mutations.update_agent_task_screen_context(
            agent_task_id=agent_task_id,
            screen_text=screen_text,
            app_name=app_name,
            window_title=window_title,
            screen_capture_path=screen_capture_path
        )

    async def delete_agent_task(self, agent_task_id: str, cascade: bool = True) -> bool:
        """Delete a agent_task by ID.
        
        Args:
            agent_task_id: The ID of the agent task to delete.
            cascade: If True, also delete all follow-up agent tasks in the chain.
            
        Returns:
            True if deletion was successful, False if agent task not found.
        """
        return await self._mutations.delete_agent_task(agent_task_id, cascade)
    
    # === Queries (direct delegation, no events needed) ===
    
    async def get_agent_task(self, agent_task_id: str) -> Optional[AgentTask]:
        """Retrieve a agent_task by ID.
        
        Args:
            agent_task_id: The agent task ID to retrieve.
            
        Returns:
            AgentTask object if found, None otherwise.
        """
        return await self._queries.get_agent_task(agent_task_id)

    async def get_agent_task_chain(self, root_task_id: str) -> List[AgentTask]:
        """Retrieve all agent tasks in a chain (the parent and all follow-ups).
        
        Args:
            root_task_id: ID of the root task in the chain.
            
        Returns:
            List of AgentTask objects ordered by chain_sequence_number.
        """
        return await self._queries.get_agent_task_chain(root_task_id)

    async def get_follow_up_counts(self, agent_task_ids: List[str]) -> Dict[str, int]:
        """Get the count of follow-up agent tasks for a list of parent agent task IDs.
        
        Args:
            agent_task_ids: List of agent task IDs to get follow-up counts for.
            
        Returns:
            Dictionary mapping agent_task_id to follow-up count.
        """
        return await self._queries.get_follow_up_counts(agent_task_ids)

    async def get_last_activity_timestamps(self, agent_task_ids: List[str]) -> Dict[str, 'datetime']:
        """Get the most recent follow-up timestamp for a list of root agent task IDs.
        
        Args:
            agent_task_ids: List of root agent task IDs to check.
            
        Returns:
            Dictionary mapping agent_task_id to its latest follow-up timestamp.
        """
        return await self._queries.get_last_activity_timestamps(agent_task_ids)

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
        return await self._queries.list_recent_agent_tasks(limit, offset, status_filter)

    async def list_recent_agent_task_summaries(
        self,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List root task summaries using the lightweight sidebar query."""
        return await self._queries.list_recent_agent_task_summaries(limit, offset, status_filter)

    async def list_recent_conversation_task_summaries(
        self,
        conversation_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Return bounded terminal task-chain summaries for one Conversation."""
        return await self._queries.list_recent_conversation_task_summaries(
            conversation_id,
            limit,
        )

    async def list_active_agent_tasks(self) -> List[AgentTask]:
        """List all currently active/processing agent_tasks.
        
        Returns:
            List of AgentTask objects for active agent tasks, ordered by timestamp DESC.
        """
        return await self._queries.list_active_agent_tasks()

    async def mark_interrupted_active_agent_tasks(self) -> int:
        """Mark in-process task rows as failed during backend startup."""
        return await self._mutations.mark_interrupted_active_agent_tasks()

    async def clear_agent_task_execution_timeline(self, agent_task_id: str) -> None:
        """Clear visible execution details before retrying a task."""
        await self._mutations.clear_agent_task_execution_timeline(agent_task_id)

    async def update_execution_timeline(
        self,
        agent_task_id: str,
        timeline: List[Dict[str, Any]],
    ) -> None:
        """Persist the presentation timeline for a completed or fixture task."""
        await self._mutations.update_execution_timeline(agent_task_id, timeline)

    async def list_artifact_revisions(
        self,
        agent_task_id: str,
        artifact_id: str,
    ) -> List[Dict[str, Any]]:
        """Return metadata-only revisions for one task-owned artifact."""
        return await self._mutations.list_artifact_revisions(agent_task_id, artifact_id)

    async def get_artifact_revision(
        self,
        agent_task_id: str,
        artifact_id: str,
        revision: int,
    ) -> Optional[Dict[str, Any]]:
        """Return one bounded text snapshot for one task-owned artifact."""
        return await self._mutations.get_artifact_revision(agent_task_id, artifact_id, revision)

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
        return await self._queries.search_agent_tasks(
            query=query,
            start_date=start_date,
            end_date=end_date,
            status=status,
            app_name=app_name,
            limit=limit,
            offset=offset
        )

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
        """Search root task summaries using the maintained FTS index."""
        return await self._queries.search_agent_task_summaries(
            query=query,
            start_date=start_date,
            end_date=end_date,
            status=status,
            app_name=app_name,
            limit=limit,
            offset=offset
        )

    async def list_agent_tasks_by_origin(self, origin_type: str, origin_id: str, include_terminal: bool = True):
        return await self._queries.list_agent_tasks_by_origin(origin_type, origin_id, include_terminal)

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str):
        return await self._queries.list_nonterminal_agent_tasks_by_origin_type(origin_type)

    async def list_agent_task_origin_ids_by_origin_type(self, origin_type: str):
        return await self._queries.list_agent_task_origin_ids_by_origin_type(origin_type)

    async def list_latest_agent_task_status_by_origins(
        self, origin_type: str, origin_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        return await self._queries.list_latest_agent_task_status_by_origins(origin_type, origin_ids)
