"""AgentTask event system for change detection and callbacks."""

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class AgentTaskEvent:
    """Represents a agent_task database event."""
    agent_task_id: str
    event_type: str  # 'created', 'updated', 'status_changed', 'clarification_added'
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    old_clarifications: Optional[List[str]] = None
    new_clarifications: Optional[List[str]] = None
    agent_task_data: Optional[Dict[str, Any]] = None


class AgentTaskEventManager:
    """Handles event registration, dispatching, and change detection for agent_tasks."""
    
    def __init__(self):
        """Initialize the event manager."""
        self._callbacks: List[Callable[[AgentTaskEvent], None]] = []
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def register_callback(self, callback: Callable[[AgentTaskEvent], None]) -> None:
        """Register a callback to be called when agent_task events occur."""
        self._callbacks.append(callback)
        logger.info(f"Registered agent_task callback: {callback.__name__}")
    
    def unregister_callback(self, callback: Callable[[AgentTaskEvent], None]) -> None:
        """Unregister a agent_task callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            logger.info(f"Unregistered agent_task callback: {callback.__name__}")
    
    def dispatch_event(self, event: AgentTaskEvent) -> None:
        """Dispatch a agent_task event to all registered callbacks."""
        logger.debug(f"Dispatching agent_task event: {event.event_type} for request {event.agent_task_id}")
        for callback in self._callbacks:
            try:
                # Check if callback is async and schedule it properly
                if inspect.iscoroutinefunction(callback):
                    # Try to get the current event loop, or create a task if we're in one
                    try:
                        loop = asyncio.get_running_loop()
                        # Schedule the async callback as a task
                        loop.create_task(callback(event))
                    except RuntimeError:
                        # No event loop running, log warning
                        logger.warning(f"No event loop running for async callback {callback.__name__}")
                else:
                    # Synchronous callback, call directly
                    callback(event)
            except Exception as e:
                logger.error(f"Error in agent_task callback {callback.__name__}: {e}")
    
    def cache_state(self, agent_task_id: str, agent_task_data: Dict[str, Any]) -> None:
        """Cache agent_task state for change detection."""
        self._cache[agent_task_id] = {
            'status': agent_task_data.get('status'),
            'clarifications': agent_task_data.get('clarifications', []),
            'operation': agent_task_data.get('operation'),
            'updated_at': agent_task_data.get('updated_at')
        }
    
    def detect_changes(self, agent_task_id: str, new_data: Dict[str, Any]) -> Optional[AgentTaskEvent]:
        """Detect changes in agent_task and create appropriate event.
        
        Args:
            agent_task_id: The agent task ID to check for changes.
            new_data: The new agent task data to compare against cached state.
            
        Returns:
            AgentTaskEvent if changes detected, None otherwise.
        """
        cached_data = self._cache.get(agent_task_id)
        
        if cached_data is None:
            # New agent task
            event = AgentTaskEvent(
                agent_task_id=agent_task_id,
                event_type='created',
                new_status=new_data.get('status'),
                agent_task_data=new_data
            )
            self.cache_state(agent_task_id, new_data)
            return event
        
        # Check for status changes
        old_status = cached_data.get('status')
        new_status = new_data.get('status')
        if old_status != new_status:
            event = AgentTaskEvent(
                agent_task_id=agent_task_id,
                event_type='status_changed',
                old_status=old_status,
                new_status=new_status,
                agent_task_data=new_data
            )
            self.cache_state(agent_task_id, new_data)
            return event
        
        # Check for clarification changes
        old_clarifications = cached_data.get('clarifications', [])
        new_clarifications = new_data.get('clarifications', [])
        if old_clarifications != new_clarifications:
            event = AgentTaskEvent(
                agent_task_id=agent_task_id,
                event_type='clarification_added',
                old_clarifications=old_clarifications,
                new_clarifications=new_clarifications,
                agent_task_data=new_data
            )
            self.cache_state(agent_task_id, new_data)
            return event
        
        # General update
        if cached_data.get('updated_at') != new_data.get('updated_at'):
            event = AgentTaskEvent(
                agent_task_id=agent_task_id,
                event_type='updated',
                agent_task_data=new_data
            )
            self.cache_state(agent_task_id, new_data)
            return event
        
        return None
