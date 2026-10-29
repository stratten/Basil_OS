"""Bounded concurrency primitives for meeting analysis model calls."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Deque, Dict, List, Sequence, Tuple, TypeVar

from api.core.models.reasoning.model_runtime_profile import (
    resolve_runtime_model_profile,
)

from .meeting_analysis_models import AnalysisMode

logger = logging.getLogger(__name__)

API_MODEL_CONCURRENCY = 3
LOCAL_MODEL_CONCURRENCY = 1
CONCURRENCY_ENV_VAR = "BASIL_ANALYSIS_CONCURRENCY"
_API_HANDLERS = frozenset({"openai_api", "anthropic_api", "gemini_api"})

MODE_DEPENDENCIES: Dict[str, Tuple[str, ...]] = {
    AnalysisMode.SUGGESTED_ACTIONS.value: (AnalysisMode.ACTION_ITEMS.value,),
}

_T = TypeVar("_T")


def is_api_analysis_model(model: Any) -> bool:
    """True only for hosted API handlers; local and unknown handlers are serialized."""
    try:
        handler = resolve_runtime_model_profile(model).handler
    except Exception:
        return False
    return handler in _API_HANDLERS


def resolve_analysis_concurrency(model: Any) -> int:
    """Return the in-flight model-call bound for this model.

    The environment override exists so a baseline (value 1) and a tuned run can be
    compared on the same meeting without a code change.
    """
    override = os.environ.get(CONCURRENCY_ENV_VAR, "").strip()
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            logger.warning(
                "Ignoring non-integer %s=%r", CONCURRENCY_ENV_VAR, override
            )
    return API_MODEL_CONCURRENCY if is_api_analysis_model(model) else LOCAL_MODEL_CONCURRENCY


class AnalysisCallLimiter:
    """Bounds concurrent model calls; the bound can be lowered mid-run.

    Every state change is synchronous, so cancellation can never leak a slot.
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._in_flight = 0
        self._waiters: Deque["asyncio.Future[None]"] = deque()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def _wake(self) -> None:
        while self._waiters and self._in_flight < self._limit:
            waiter = self._waiters.popleft()
            if waiter.done():
                continue
            self._in_flight += 1
            waiter.set_result(None)

    async def acquire(self) -> None:
        if self._in_flight < self._limit and not self._waiters:
            self._in_flight += 1
            return
        waiter: "asyncio.Future[None]" = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():
                self._in_flight -= 1
                self._wake()
            else:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    pass
            raise

    def release(self) -> None:
        self._in_flight -= 1
        self._wake()

    def set_limit(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._wake()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self.acquire()
        try:
            yield
        finally:
            self.release()


async def gather_cancel_on_error(coroutines: Sequence[Awaitable[_T]]) -> List[_T]:
    """Run awaitables concurrently, preserving order, and cancel siblings on failure."""
    tasks = [asyncio.ensure_future(coroutine) for coroutine in coroutines]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
