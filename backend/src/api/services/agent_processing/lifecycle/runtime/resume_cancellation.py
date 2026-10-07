"""Registers resumed workflow runs so Stop can cancel them like first runs."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, TypeVar

from ...shared.agent_run_registry import process_cancellation_registry

T = TypeVar("T")


class ResumedRunCanceled(Exception):
    """The user stopped a resumed run."""


async def run_registered_resume(agent_task_id: Any, awaitable: Awaitable[T]) -> T:
    registry = process_cancellation_registry()
    task_id = str(agent_task_id or "").strip()
    if registry is None or not task_id:
        return await awaitable
    child = asyncio.ensure_future(awaitable)
    registry.register_active_task(task_id, child)
    try:
        return await child
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if child.cancelled() and (current is None or current.cancelling() == 0):
            raise ResumedRunCanceled() from None
        raise
    finally:
        registry.deregister_active_task(task_id, child)
