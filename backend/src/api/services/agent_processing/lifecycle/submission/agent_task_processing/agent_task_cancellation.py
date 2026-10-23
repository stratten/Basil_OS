"""Cancellation state and preemptive task tracking for agent-task processing.

This module owns the per-agent-task cancellation bookkeeping that previously
lived inline in ``AgentTaskOrchestrator``:

  * the set of canceled agent-task ids,
  * the cooperative ``asyncio.Event`` signals threaded into workflow execution,
  * and (new) a registry of the live top-level ``asyncio.Task`` objects running
    each agent task's workflow, so cancellation can *preempt* them via
    ``Task.cancel()`` instead of only cooperatively via the event.

Preemptive cancellation is the primary mechanism; the cooperative event remains
as a secondary signal for nested execution paths and cross-loop waiters.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Dict, Iterable, Set, Tuple

logger = logging.getLogger(__name__)


class ThreadSafeCancellationSignal:
    """An asyncio-compatible cancellation signal that can be set from any thread."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._waiters: Set[Tuple[asyncio.AbstractEventLoop, asyncio.Future]] = set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        self._event.set()
        with self._lock:
            waiters = tuple(self._waiters)
        for loop, future in waiters:
            if loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(self._resolve_waiter, future)
            except RuntimeError:
                continue

    async def wait(self) -> bool:
        if self._event.is_set():
            return True
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        waiter = (loop, future)
        with self._lock:
            self._waiters.add(waiter)
            already_set = self._event.is_set()
        if already_set:
            self._resolve_waiter(future)
        try:
            await future
            return True
        finally:
            with self._lock:
                self._waiters.discard(waiter)

    @staticmethod
    def _resolve_waiter(future: asyncio.Future) -> None:
        if not future.done():
            future.set_result(True)


class AgentTaskCancellationRegistry:
    """Tracks cancellation state and live processing tasks per agent-task id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._canceled_agent_tasks: Set[str] = set()
        self._notified_agent_tasks: Set[str] = set()
        self._cancellation_events: Dict[str, ThreadSafeCancellationSignal] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._active_task_loops: Dict[str, asyncio.AbstractEventLoop] = {}
        self._alias_members: Dict[str, Set[str]] = {}
        self._aliases_by_task: Dict[str, Set[str]] = {}

    def is_canceled(self, agent_task_id: str) -> bool:
        """Return True if this agent task has been marked canceled."""
        with self._lock:
            return any(
                task_id in self._canceled_agent_tasks
                for task_id in self._resolve_ids_locked(agent_task_id)
            )

    def get_cancellation_event(self, agent_task_id: str) -> ThreadSafeCancellationSignal:
        """Return the cooperative cancellation signal for an agent task.

        The event is lazily created and the same instance is returned on every
        subsequent call for the id, so callers that cached the event still see
        it fire when the task is canceled.
        """
        with self._lock:
            event = self._cancellation_events.get(agent_task_id)
            if event is None:
                event = ThreadSafeCancellationSignal()
                if agent_task_id in self._canceled_agent_tasks:
                    event.set()
                self._cancellation_events[agent_task_id] = event
            return event

    def mark_canceled(self, agent_task_ids: Iterable[str]) -> None:
        """Mark ids canceled and set their cooperative events.

        Empty/falsy ids are ignored so a bad id can never create a spurious
        cancellation event.
        """
        signals = []
        with self._lock:
            expanded_ids: Set[str] = set()
            for agent_task_id in agent_task_ids:
                if agent_task_id:
                    expanded_ids.update(self._resolve_ids_locked(agent_task_id))
            for agent_task_id in expanded_ids:
                self._canceled_agent_tasks.add(agent_task_id)
                event = self._cancellation_events.get(agent_task_id)
                if event is None:
                    event = ThreadSafeCancellationSignal()
                    self._cancellation_events[agent_task_id] = event
                signals.append(event)
        for signal in signals:
            signal.set()

    def register_active_task(
        self,
        agent_task_id: str,
        task: asyncio.Task,
        aliases: Iterable[str] = (),
    ) -> None:
        """Record the top-level asyncio.Task currently processing this id."""
        if not agent_task_id or task is None:
            return
        loop = task.get_loop()
        should_cancel = False
        with self._lock:
            self._active_tasks[agent_task_id] = task
            self._active_task_loops[agent_task_id] = loop
            for alias in aliases:
                if not alias or alias == agent_task_id:
                    continue
                self._alias_members.setdefault(alias, set()).add(agent_task_id)
                self._aliases_by_task.setdefault(agent_task_id, set()).add(alias)
                if alias in self._canceled_agent_tasks:
                    self._canceled_agent_tasks.add(agent_task_id)
                    self.get_cancellation_event(agent_task_id).set()
            should_cancel = agent_task_id in self._canceled_agent_tasks
        if should_cancel and not task.done():
            self._schedule_task_cancel(task, loop)

    def register_alias(self, alias: str, agent_task_id: str) -> None:
        """Associate a root/chain identifier with an already registered active turn."""
        if not alias or not agent_task_id or alias == agent_task_id:
            return
        with self._lock:
            self._alias_members.setdefault(alias, set()).add(agent_task_id)
            self._aliases_by_task.setdefault(agent_task_id, set()).add(alias)
            should_cancel = alias in self._canceled_agent_tasks
            task = self._active_tasks.get(agent_task_id)
            loop = self._active_task_loops.get(agent_task_id)
            if should_cancel:
                self._canceled_agent_tasks.add(agent_task_id)
                self.get_cancellation_event(agent_task_id).set()
        if should_cancel and task is not None and loop is not None and not task.done():
            self._schedule_task_cancel(task, loop)

    def clear_canceled(self, agent_task_id: str) -> None:
        """Clear one completed turn's tombstone without disturbing active aliases."""
        if not agent_task_id:
            return
        with self._lock:
            self._canceled_agent_tasks.discard(agent_task_id)
            self._notified_agent_tasks.discard(agent_task_id)
            self._cancellation_events.pop(agent_task_id, None)
            if agent_task_id in self._active_tasks:
                return
            for alias in self._aliases_by_task.pop(agent_task_id, set()):
                members = self._alias_members.get(alias)
                if members is None:
                    continue
                members.discard(agent_task_id)
                if not members:
                    self._alias_members.pop(alias, None)
            members = self._alias_members.get(agent_task_id)
            if members and not any(member in self._active_tasks for member in members):
                self._alias_members.pop(agent_task_id, None)
                for member in members:
                    aliases = self._aliases_by_task.get(member)
                    if aliases is not None:
                        aliases.discard(agent_task_id)
                        if not aliases:
                            self._aliases_by_task.pop(member, None)

    def claim_terminal_notification(self, agent_task_id: str) -> bool:
        """Return True exactly once for each task's cancellation notification."""
        if not agent_task_id:
            return False
        with self._lock:
            if agent_task_id in self._notified_agent_tasks:
                return False
            self._notified_agent_tasks.add(agent_task_id)
            return True

    def release_terminal_notification(self, agent_task_id: str) -> None:
        """Allow retry when a claimed terminal notification failed to send."""
        with self._lock:
            self._notified_agent_tasks.discard(agent_task_id)

    def deregister_active_task(self, agent_task_id: str, task: asyncio.Task) -> None:
        """Remove the recorded task, but only if it is still ``task``.

        Guards against an older coroutine's ``finally`` block clobbering the
        registration of a newer, re-submitted task for the same id.
        """
        with self._lock:
            if self._active_tasks.get(agent_task_id) is task:
                del self._active_tasks[agent_task_id]
                self._active_task_loops.pop(agent_task_id, None)
                for alias in self._aliases_by_task.pop(agent_task_id, set()):
                    members = self._alias_members.get(alias)
                    if members is not None:
                        members.discard(agent_task_id)
                        if not members:
                            self._alias_members.pop(alias, None)

    def cancel_active_task(self, agent_task_id: str) -> bool:
        """Preemptively cancel the live processing task for an id.

        Returns True if a live (not-yet-done) task was found and ``.cancel()``
        was requested; False if nothing is registered or the task already
        finished.
        """
        scheduled = False
        with self._lock:
            handles = [
                (task_id, self._active_tasks.get(task_id), self._active_task_loops.get(task_id))
                for task_id in self._resolve_ids_locked(agent_task_id)
            ]
        for task_id, task, loop in handles:
            if task is None or loop is None or task.done():
                continue
            logger.info(
                "🛑 Preemptively canceling active asyncio.Task for agent_task %s",
                task_id,
            )
            scheduled = self._schedule_task_cancel(task, loop) or scheduled
        return scheduled

    def _resolve_ids_locked(self, agent_task_id: str) -> Set[str]:
        resolved = {agent_task_id}
        resolved.update(self._alias_members.get(agent_task_id, set()))
        for alias in self._aliases_by_task.get(agent_task_id, set()):
            resolved.add(alias)
            resolved.update(self._alias_members.get(alias, set()))
        return resolved

    @staticmethod
    def _schedule_task_cancel(
        task: asyncio.Task,
        loop: asyncio.AbstractEventLoop,
    ) -> bool:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is loop:
            task.cancel()
            return True
        if not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
                return True
            except RuntimeError:
                logger.debug("Cancellation owner loop closed before dispatch")
        return False
