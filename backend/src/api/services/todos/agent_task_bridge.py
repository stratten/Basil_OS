"""Direct-worker lifecycle registration and recovery for the To-Do domain.

Terminal `origin_type == "todo"` events reconcile worker state through
`TodoService`. Terminal `origin_type == "todo_workspace"` events broadcast a
correlated result and never mutate a To-Do.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_todo_callback_registered = False
_todo_bridge_singleton: Optional["TodoAgentTaskBridge"] = None
_todo_finalizer_tasks: set[asyncio.Task[None]] = set()

_TERMINAL_STATUSES = frozenset({"completed", "failed", "canceled"})


def ensure_todo_agent_task_callback_registered(db_service: Any) -> None:
    """Idempotently register the To-Do database-event callback exactly once
    per process. Safe to call multiple times."""
    global _todo_callback_registered
    if _todo_callback_registered:
        return

    if db_service is None:
        logger.warning("Cannot register To-Do agent-task callback: sqlite_knowledge_service unavailable")
        return
    db_service.register_agent_task_callback(handle_todo_agent_task_event)
    _todo_callback_registered = True
    logger.info("Registered To-Do Agent Task lifecycle callback")


def get_todo_agent_task_bridge() -> Optional["TodoAgentTaskBridge"]:
    return _todo_bridge_singleton


def set_todo_agent_task_bridge(bridge: "TodoAgentTaskBridge") -> None:
    global _todo_bridge_singleton
    _todo_bridge_singleton = bridge


def _track_todo_finalizer(task: asyncio.Task[None]) -> None:
    _todo_finalizer_tasks.add(task)

    def finish(completed: asyncio.Task[None]) -> None:
        _todo_finalizer_tasks.discard(completed)
        if completed.cancelled():
            return
        exception = completed.exception()
        if exception is not None:
            logger.error("To-Do Agent Task finalizer failed: %s", exception)

    task.add_done_callback(finish)


def handle_todo_agent_task_event(event: Any) -> None:
    """Database-event callback. Fires and forgets an async reconciliation
    task so the synchronous callback contract used elsewhere is preserved."""
    bridge = get_todo_agent_task_bridge()
    if bridge is None:
        return
    if event.new_status not in _TERMINAL_STATUSES:
        return
    try:
        loop = asyncio.get_running_loop()
        _track_todo_finalizer(
            loop.create_task(
                bridge.handle_terminal_event(event.agent_task_id),
                name=f"todo-agent-task-finalizer:{event.agent_task_id}",
            )
        )
    except RuntimeError:
        logger.warning(
            "To-Do callback received terminal event without a running loop for agent_task_id=%s",
            event.agent_task_id,
        )


async def recover_todo_agent_task_attempts(todo_service: Any) -> int:
    """Startup recovery: reconcile every To-Do whose direct-origin worker is
    nonterminal but may have missed its terminal callback (e.g. a process
    restart between the worker's terminal write and this callback firing)."""
    return await todo_service.reconcile_all_nonterminal_todo_workers()


async def shutdown_todo_agent_task_finalizers() -> None:
    global _todo_callback_registered, _todo_bridge_singleton
    tasks = tuple(task for task in _todo_finalizer_tasks if not task.done())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _todo_finalizer_tasks.clear()
    _todo_callback_registered = False
    _todo_bridge_singleton = None


class TodoAgentTaskBridge:
    def __init__(self, *, todo_service: Any, agent_task_service: Any, agent_task_submission_service: Any):
        self.todo_service = todo_service
        self.agent_task_service = agent_task_service
        self.agent_task_submission_service = agent_task_submission_service

    async def launch_todo_item_agent_task(self, *, todo_id: str) -> Dict[str, Any]:
        import uuid

        item = await self.todo_service.get_item_detail(todo_id)
        agent_task_id = str(uuid.uuid4())
        todo_worker_context = await self._build_todo_worker_context(item)
        reference_paths = todo_worker_context.get("reference_paths") if todo_worker_context else None
        source_agent_task_ids = (
            todo_worker_context.get("source_agent_task_ids") if todo_worker_context else None
        )
        attached_references = (
            "Attached reference paths:\n"
            + "\n".join(f"- {path}" for path in reference_paths)
            if isinstance(reference_paths, list) and reference_paths
            else "Attached reference paths: (none)"
        )
        prior_investigation_handoff = (
            "Prior investigation handoff:\n"
            "If prior conclusions, artifacts, or source-email identity matter, call "
            "recall_agent_tasks(scope='detail', task_id='<source id>') for a source "
            "Agent Task id below before broad rediscovery:\n"
            + "\n".join(f"- {source_id}" for source_id in source_agent_task_ids)
            if isinstance(source_agent_task_ids, list) and source_agent_task_ids
            else ""
        )
        prompt = (
            f"Complete this To-Do on the user's behalf.\n\n"
            f"Title: {item.title}\n"
            f"Description: {item.description}\n"
            f"Notes: {item.notes}\n\n"
            f"{attached_references}\n\n"
            f"{prior_investigation_handoff}\n\n"
            "Leave concrete evidence of what you did (files touched, messages sent, "
            "research found) in your final result so the user can verify the work."
        )
        try:
            result = await self.agent_task_submission_service.process_agent_task_direct(
                agent_task=prompt,
                agent_task_id=agent_task_id,
                origin_type="todo",
                origin_id=todo_id,
                reference_paths=reference_paths,
                todo_worker_context=todo_worker_context,
            )
        except Exception as exc:
            logger.error("Failed to submit worker Agent Task for To-Do %s: %s", todo_id, exc, exc_info=True)
            await self.todo_service.repository.append_todo_event(
                todo_id=todo_id, event_kind="worker_submission_failed", actor_kind="system",
                actor_id=None, payload={"error": str(exc)},
            )
            return {"success": False, "error": str(exc)}

        if not result.get("success", False):
            await self.todo_service.repository.append_todo_event(
                todo_id=todo_id, event_kind="worker_submission_failed", actor_kind="system",
                actor_id=None, payload=result,
            )
            return {"success": False, "error": result.get("message", "submission rejected")}

        if item.status == "open":
            try:
                await self.todo_service.mark_worker_launched(todo_id, item.revision, agent_task_id)
            except Exception:
                await self.todo_service.reconcile_todo_from_worker_tasks(todo_id)
        else:
            await self.todo_service.repository.append_todo_event(
                todo_id=todo_id, event_kind="worker_launched", actor_kind="agent", actor_id=agent_task_id,
                payload={"agent_task_id": agent_task_id},
            )
        return {"success": True, "agent_task_id": agent_task_id}

    async def _build_todo_worker_context(self, item: Any) -> Optional[Dict[str, Any]]:
        """Read optional durable source context without making the worker a chain turn."""
        worker_handoff = getattr(self.todo_service, "worker_handoff", None)
        if not callable(worker_handoff):
            return None
        try:
            context = worker_handoff(item)
            if inspect.isawaitable(context):
                context = await context
            if isinstance(context, dict):
                return context
            if context is not None:
                logger.warning(
                    "Ignoring malformed To-Do worker handoff for %s: expected a mapping",
                    item.id,
                )
        except Exception as exc:
            logger.warning(
                "Could not build source handoff for To-Do worker %s; continuing without it: %s",
                item.id,
                exc,
            )
        return None

    async def handle_terminal_event(self, agent_task_id: str) -> None:
        agent_task = await self.agent_task_service.get_agent_task(agent_task_id)
        if agent_task is None or not getattr(agent_task, "origin_type", None):
            return

        if agent_task.origin_type == "todo" and agent_task.origin_id:
            await self.todo_service.repository.append_todo_event(
                todo_id=agent_task.origin_id, event_kind="worker_terminal", actor_kind="agent",
                actor_id=agent_task_id, payload={"status": agent_task.status},
            )
            await self.todo_service.reconcile_todo_from_worker_tasks(agent_task.origin_id)
            return

        if agent_task.origin_type == "todo_workspace" and agent_task.origin_id:
            await self._broadcast_workspace_result(agent_task)

    async def _broadcast_workspace_result(self, agent_task: Any) -> None:
        artifacts = agent_task.accumulated_artifacts or {}
        context = artifacts.get("todo_workspace_context") if isinstance(artifacts, dict) else None
        if not isinstance(context, dict):
            return
        result_data = agent_task.result_data or {}
        summary = ""
        if isinstance(result_data, dict):
            summary = result_data.get("message") or (result_data.get("data") or {}).get("message", "") if isinstance(result_data.get("data"), dict) else result_data.get("message", "")
        await self.agent_task_submission_service.broadcast({
            "event_type": "todo_workspace_result",
            "workspace_id": context.get("workspace_id"),
            "request_id": context.get("request_id"),
            "agent_task_id": agent_task.id,
            "status": agent_task.status,
            "summary": summary or "",
            "selected_todo_ids": context.get("selection_ids", []),
        })
