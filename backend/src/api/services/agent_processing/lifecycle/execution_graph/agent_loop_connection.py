"""Ride out a lost network connection mid-run, and pause the run with its progress saved when it does not come back.

A run that already made model calls has real progress in its conversation. When the model cannot be reached,
failing the whole run throws that progress away. Instead the model call waits for connectivity (the wait is
excluded from the run's time budget, and extends after the Mac slept), and if the connection stays down the run
pauses like a user pause so the user can resume it, with the same model or a different one they choose.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from api.core.logging.api_logger import api_logger

from ...shared.workflow_budget_pause import current_pausable_deadline
from ...tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

logger = api_logger.getChild("agent_loop_connection")

CONNECTION_WAIT_SECONDS = 180.0
# After the Mac slept, the network usually needs a while to rejoin Wi-Fi, renew DNS, and re-establish VPNs.
CONNECTION_WAIT_AFTER_SLEEP_SECONDS = 600.0
CONNECTION_BACKOFF_BASE_SECONDS = 2.0
CONNECTION_BACKOFF_CAP_SECONDS = 30.0
# Wall-clock time minus monotonic time grows only while the machine sleeps (monotonic time stops during sleep on macOS).
SLEEP_DRIFT_THRESHOLD_SECONDS = 30.0
CONNECTION_BUDGET_PAUSE_REASON = "model_connection_wait"
# Set in the run context when the user resumes an interrupted run with a different model.
RESUME_MODEL_SWITCH_KEY = "resume_model_switch"

CONNECTION_LOST_PROMPT = (
    "Basil lost its connection to the model, so it paused the run. Your progress so far is saved. "
    "Resume when you are back online, or choose a different model to continue with."
)

_CONNECTIVITY_MARKERS = (
    "connection",
    "network",
    "dns",
    "name resolution",
    "nodename nor servname",
    "temporary failure",
    "socket",
    "broken pipe",
    "timed out",
    "timeout",
    "unreachable",
    "offline",
    "eof occurred",
    "end of file",
)
# The service answered but is busy; a long wait for the network would not help, so these keep the short retry.
_SERVICE_BUSY_MARKERS = ("rate limit", "too many requests", "overloaded", "service unavailable", "bad gateway", "gateway timeout")
_CONNECTIVITY_TYPE_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
        "ReadError",
        "WriteError",
        "NetworkError",
        "TimeoutException",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "TimeoutError",
        "gaierror",
    }
)


class ConnectionLostPause(CheckpointRequest):
    """The model could not be reached for long enough that the run pauses, saved like a user pause so it can resume."""

    is_connection_loss = True

    def __init__(self, original_error: BaseException, *, model_label: str = "", waited_seconds: float = 0.0) -> None:
        super().__init__(
            {
                "checkpoint_id": f"connection_lost_{uuid4().hex}",
                "prompt": CONNECTION_LOST_PROMPT,
                "input_type": "text",
                "metadata": {"source": "connection_lost"},
            }
        )
        self.original_error = original_error
        self.model_label = model_label
        self.waited_seconds = waited_seconds
        self.basil_pending_messages: list[Any] = []


def _error_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: Optional[BaseException] = error
    while current is not None and current not in chain and len(chain) < 8:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def is_connectivity_error(error: BaseException) -> bool:
    """True when the failure means the network or DNS is down (not that a reachable service is busy or rejected the call)."""
    for item in _error_chain(error):
        if type(item).__name__ in _CONNECTIVITY_TYPE_NAMES:
            return True
        text = str(item).lower()
        if any(marker in text for marker in _SERVICE_BUSY_MARKERS):
            return False
        if any(marker in text for marker in _CONNECTIVITY_MARKERS):
            return True
    return False


ConnectionNotice = Callable[[str, str], Awaitable[None]]


class ConnectionWait:
    """One run's wait for the network, shared by every model call so a long outage is judged as one outage."""

    def __init__(
        self,
        *,
        notify: Optional[ConnectionNotice] = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._notify = notify
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._alive_mark = (self._wall_clock(), self._monotonic())
        self._started_at: Optional[float] = None
        self._attempts = 0
        self._deadline: Optional[Any] = None

    @property
    def waiting(self) -> bool:
        return self._started_at is not None

    def waited_seconds(self) -> float:
        return 0.0 if self._started_at is None else max(0.0, self._monotonic() - self._started_at)

    def slept_since_last_success(self) -> bool:
        wall_start, monotonic_start = self._alive_mark
        drift = (self._wall_clock() - wall_start) - (self._monotonic() - monotonic_start)
        return drift > SLEEP_DRIFT_THRESHOLD_SECONDS

    def _budget_seconds(self) -> float:
        return CONNECTION_WAIT_AFTER_SLEEP_SECONDS if self.slept_since_last_success() else CONNECTION_WAIT_SECONDS

    async def _announce(self, lifecycle_state: str, title: str) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(lifecycle_state, title)
        except Exception:
            logger.debug("Could not announce the connection wait", exc_info=True)

    def _begin_budget_pause(self) -> None:
        deadline = current_pausable_deadline()
        if deadline is not None:
            deadline.begin_pause(CONNECTION_BUDGET_PAUSE_REASON)
            self._deadline = deadline

    def _end_budget_pause(self) -> None:
        deadline, self._deadline = self._deadline, None
        if deadline is not None:
            deadline.end_pause(CONNECTION_BUDGET_PAUSE_REASON)

    async def wait_before_retry(self, error: BaseException) -> bool:
        """Sleep before the next attempt and return True, or return False once waiting longer is pointless."""
        now = self._monotonic()
        if self._started_at is None:
            self._started_at = now
            self._begin_budget_pause()
            logger.warning("📡 Lost the model connection: %s", str(error)[:200])
            await self._announce("in_progress", "Waiting for the network to come back")
        budget = self._budget_seconds()
        remaining = budget - (now - self._started_at)
        if remaining <= 0:
            logger.error("📡 The model connection did not return within %.0fs", budget)
            return False
        delay = min(
            CONNECTION_BACKOFF_CAP_SECONDS,
            CONNECTION_BACKOFF_BASE_SECONDS * (2 ** self._attempts),
            remaining,
        )
        self._attempts += 1
        logger.info("📡 Retrying the model in %.1fs (waited %.0fs of %.0fs)", delay, now - self._started_at, budget)
        await self._sleep(delay)
        return True

    async def restored(self) -> None:
        """A model call succeeded: end any outage and remember when the machine was last known to be working."""
        was_waiting = self.waiting
        waited = self.waited_seconds()
        self.close()
        self._alive_mark = (self._wall_clock(), self._monotonic())
        if was_waiting:
            logger.info("📡 The model connection returned after %.0fs", waited)
            await self._announce("completed", "Network connection restored")

    async def gave_up(self) -> None:
        self.close()
        await self._announce("failed", "Network connection lost; the run is paused")

    def close(self) -> None:
        """End the outage bookkeeping and the budget pause. Safe to call repeatedly, including on cancellation."""
        self._started_at = None
        self._attempts = 0
        self._end_budget_pause()
