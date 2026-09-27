"""Scheduled agent tasks feature package.

Three layers, top to bottom:

  * ``ScheduledAgentTaskService`` (orchestrator, this package): LLM-driven
    schedule interpretation, next-run computation, run lifecycle, recovery
    of missed runs after the app was inactive, and dispatch into the
    in-process runner.
  * ``AsyncScheduledAgentTaskRunner`` (this package): ephemeral asyncio-based
    timer that holds ``scheduled_agent_task_id -> asyncio.Task`` for in-flight
    runs. Rebuilt from the database on every cold start; no persistence of
    its own.
  * ``ScheduledAgentTaskRepository`` (in
    ``api.core.knowledge.sqlite.sqlite_knowledge_service_component_services``):
    SQLite data-access layer. Reached via
    ``self.db.scheduled_agent_task_repository``.
"""

from .async_scheduled_agent_task_runner import (
    AsyncScheduledAgentTaskRunner,
    get_async_scheduled_agent_task_runner,
)
from .scheduled_agent_task_service import (
    InterpretedScheduleContract,
    ScheduledAgentTaskService,
    _detect_local_timezone_name,
    initialize_scheduled_agent_task_runtime,
    shutdown_scheduled_agent_task_runtime,
)

__all__ = [
    "ScheduledAgentTaskService",
    "InterpretedScheduleContract",
    "AsyncScheduledAgentTaskRunner",
    "get_async_scheduled_agent_task_runner",
    "initialize_scheduled_agent_task_runtime",
    "shutdown_scheduled_agent_task_runtime",
    "_detect_local_timezone_name",
]
