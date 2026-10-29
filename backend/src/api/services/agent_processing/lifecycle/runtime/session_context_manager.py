"""
Session Context Manager

Maintains conversational context across multiple agent_tasks to enable natural
continuation patterns like:
- "Draft 3 emails" → "Now summarize those drafts"
- "Create a file" → "Now open it in VSCode"
- "Find top 5 clients" → "Now research the first one"

Architecture:
- Stores recent agent-task results in memory (last 5 agent tasks)
- Each agent_task_id maps to its result artifacts
- Agent can access via special tool or context parameter
- Automatically cleans up old sessions after timeout
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentTaskContext:
    """Context from a single agent-task execution."""
    agent_task_id: str
    agent_task_text: str
    timestamp: datetime
    result_summary: str
    artifacts: Dict[str, Any]  # Files created, emails drafted, data retrieved, etc.
    operation: str  # The operation that was performed
    
    def to_context_string(self) -> str:
        """Convert to natural language context for agent."""
        age = (datetime.now() - self.timestamp).seconds
        age_str = f"{age}s ago" if age < 60 else f"{age//60}m ago"
        
        context = f"[{age_str}] {self.agent_task_text}\n"
        context += f"  Result: {self.result_summary}\n"
        
        if self.artifacts:
            context += f"  Artifacts: "
            artifact_items = []
            if self.artifacts.get('files'):
                artifact_items.append(f"{len(self.artifacts['files'])} files")
            if self.artifacts.get('emails'):
                artifact_items.append(f"{len(self.artifacts['emails'])} emails")
            if self.artifacts.get('data'):
                artifact_items.append("data retrieved")
            context += ", ".join(artifact_items)
        
        return context


class SessionContextManager:
    """
    Manages conversational context across agent_tasks.
    
    Enables natural continuation patterns by maintaining a sliding window
    of recent agent-task results that can be referenced by subsequent agent tasks.
    """
    
    def __init__(self, max_history: int = 5, timeout_minutes: int = 30):
        """
        Initialize context manager.
        
        Args:
            max_history: Maximum number of recent agent tasks to track
            timeout_minutes: How long to keep context before expiring
        """
        self.max_history = max_history
        self.timeout = timedelta(minutes=timeout_minutes)
        self.agent_task_history: List[AgentTaskContext] = []
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def add_agent_task_result(
        self,
        agent_task_id: str,
        agent_task_text: str,
        result_summary: str,
        artifacts: Dict[str, Any],
        operation: str
    ):
        """
        Store the result of an agent-task execution.
        
        Args:
            agent_task_id: Unique agent task identifier
            agent_task_text: The original agent_task
            result_summary: Human-readable summary of what was done
            artifacts: Structured data (files, emails, etc.) created/retrieved
            operation: The operation type (generate_suggestions, multi_step_workflow, etc.)
        """
        context = AgentTaskContext(
            agent_task_id=agent_task_id,
            agent_task_text=agent_task_text,
            timestamp=datetime.now(),
            result_summary=result_summary,
            artifacts=artifacts,
            operation=operation
        )
        
        # Add to history
        self.agent_task_history.append(context)
        
        # Maintain sliding window
        if len(self.agent_task_history) > self.max_history:
            removed = self.agent_task_history.pop(0)
            self.logger.debug(f"Removed old context: {removed.agent_task_id}")
        
        self.logger.info(f"Added agent-task context: {agent_task_id} | History size: {len(self.agent_task_history)}")
    
    def get_recent_context(self, count: int = 3) -> str:
        """
        Get recent agent-task context as formatted string for agent.
        
        Args:
            count: Number of recent agent tasks to include
            
        Returns:
            Formatted context string
        """
        # Clean expired contexts first
        self._clean_expired()
        
        if not self.agent_task_history:
            return "No recent agent tasks."
        
        recent = self.agent_task_history[-count:]
        context_strings = [cmd.to_context_string() for cmd in recent]
        
        return "RECENT AGENT TASKS:\n" + "\n".join(context_strings)
    
    def get_last_agent_task_artifacts(self) -> Optional[Dict[str, Any]]:
        """
        Get artifacts from the most recent agent task.
        
        Useful for agent tasks like "Now summarize that" where "that"
        refers to the output of the previous agent task.
        
        Returns:
            Artifacts dict or None if no recent agent tasks
        """
        self._clean_expired()
        
        if not self.agent_task_history:
            return None
        
        return self.agent_task_history[-1].artifacts
    
    def get_agent_task_by_id(self, agent_task_id: str) -> Optional[AgentTaskContext]:
        """Get context for a specific agent task ID."""
        for agent_task_context in self.agent_task_history:
            if agent_task_context.agent_task_id == agent_task_id:
                return agent_task_context
        return None
    
    def clear_context(self):
        """Clear all context (e.g., when user explicitly resets)."""
        self.agent_task_history.clear()
        self.logger.info("Cleared all session context")
    
    def _clean_expired(self):
        """Remove contexts older than timeout."""
        now = datetime.now()
        self.agent_task_history = [
            cmd for cmd in self.agent_task_history 
            if now - cmd.timestamp < self.timeout
        ]


# Global singleton instance
_session_context_manager = None

def get_session_context_manager() -> SessionContextManager:
    """Get the global session context manager instance."""
    global _session_context_manager
    if _session_context_manager is None:
        _session_context_manager = SessionContextManager()
    return _session_context_manager

