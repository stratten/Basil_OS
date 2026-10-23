"""The resource advisor: samples the machine while recording and keeps a small, steady list of advice."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .models import (
    CLEAR_SECONDS,
    MAX_ADVICE_SHOWN,
    RULE_ORDER,
    SAMPLE_INTERVAL_SECONDS,
    SEVERITY_RANK,
    SUSTAIN_SECONDS,
    THERMAL_REPORT_TTL_SECONDS,
    VALID_THERMAL_STATES,
    Advice,
    ResourceAdviceState,
    ResourceSnapshot,
)
from .rules import evaluate_rules
from .snapshot_provider import SnapshotProvider

logger = logging.getLogger(__name__)

Broadcaster = Callable[[Dict[str, Any]], Awaitable[None]]


async def broadcast_to_clients(message: Dict[str, Any]) -> None:
    from api.services.websocket_connection_manager import broadcast_json_text

    await broadcast_json_text(message, log=logger)


class ResourceAdvisor:
    """A rule is raised only after it has held for the sustain window and cleared only after it has been false for the clear window.

    Dismissing advice hides it until the rule clears or the recording ends.
    """

    def __init__(
        self,
        snapshot_provider: SnapshotProvider,
        *,
        broadcaster: Broadcaster = broadcast_to_clients,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sustain_seconds: float = SUSTAIN_SECONDS,
        clear_seconds: float = CLEAR_SECONDS,
        sample_interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._broadcaster = broadcaster
        self._clock = clock
        self._wall_clock = wall_clock
        self._sustain_seconds = sustain_seconds
        self._clear_seconds = clear_seconds
        self._sample_interval_seconds = sample_interval_seconds
        self._true_since: Dict[str, float] = {}
        self._false_since: Dict[str, float] = {}
        self._raised: Dict[str, Advice] = {}
        self._dismissed: Set[str] = set()
        self._thermal: Optional[Tuple[str, float]] = None
        self._revision = 0
        self._published: Tuple[Tuple[str, str, str, str], ...] = ()
        self._task: Optional[asyncio.Task[None]] = None

    # ------------------------------------------------------------------ inputs

    def report_thermal_state(self, state: str) -> bool:
        """Record the thermal state the desktop client reports; unknown values are rejected."""
        if state not in VALID_THERMAL_STATES:
            return False
        self._thermal = (state, self._clock())
        return True

    def _fresh_thermal_state(self, now: float) -> Optional[str]:
        if self._thermal is None:
            return None
        state, reported_at = self._thermal
        return state if now - reported_at <= THERMAL_REPORT_TTL_SECONDS else None

    def dismiss(self, advice_id: str) -> bool:
        """Hide raised advice; returns False when no such advice is raised."""
        if advice_id not in self._raised:
            return False
        self._dismissed.add(advice_id)
        return True

    # ------------------------------------------------------------------ state

    def state(self) -> ResourceAdviceState:
        visible = [advice for advice in self._ordered() if advice.id not in self._dismissed][:MAX_ADVICE_SHOWN]
        return ResourceAdviceState(revision=self._revision, advice=visible)

    def _ordered(self) -> List[Advice]:
        return sorted(self._raised.values(), key=lambda advice: (SEVERITY_RANK[advice.severity], RULE_ORDER.index(advice.id)))

    def _signature(self) -> Tuple[Tuple[str, str, str, str], ...]:
        return tuple((advice.id, advice.severity, advice.title, advice.detail) for advice in self.state().advice)

    # ------------------------------------------------------------------ sampling

    def sample(self) -> bool:
        """Take one sample and return True when the visible advice changed."""
        now = self._clock()
        snapshot = self._snapshot_provider(self._fresh_thermal_state(now))
        if not snapshot.recording:
            self._reset()
        else:
            self._apply(snapshot, now)
        signature = self._signature()
        if signature == self._published:
            return False
        self._published = signature
        self._revision += 1
        return True

    def _reset(self) -> None:
        self._true_since.clear()
        self._false_since.clear()
        self._raised.clear()
        self._dismissed.clear()

    def _apply(self, snapshot: ResourceSnapshot, now: float) -> None:
        holding = {advice.id: advice for advice in evaluate_rules(snapshot)}
        for advice_id, advice in holding.items():
            self._false_since.pop(advice_id, None)
            started = self._true_since.setdefault(advice_id, now)
            existing = self._raised.get(advice_id)
            if existing is not None:
                self._raised[advice_id] = advice.model_copy(update={"raised_at": existing.raised_at})
            elif now - started >= self._sustain_seconds:
                self._raised[advice_id] = advice.model_copy(update={"raised_at": self._wall_clock()})
        for advice_id in list(self._true_since):
            if advice_id in holding:
                continue
            self._true_since.pop(advice_id, None)
        for advice_id in list(self._raised):
            if advice_id in holding:
                continue
            cleared_since = self._false_since.setdefault(advice_id, now)
            if now - cleared_since >= self._clear_seconds:
                del self._raised[advice_id]
                self._dismissed.discard(advice_id)
                self._false_since.pop(advice_id, None)

    # ------------------------------------------------------------------ loop

    def frame(self) -> Dict[str, Any]:
        state = self.state()
        return {"event_type": "resource_advice", "revision": state.revision, "advice": [advice.model_dump(mode="json") for advice in state.advice]}

    async def publish_if_changed(self) -> bool:
        changed = self.sample()
        if changed:
            await self._broadcaster(self.frame())
        return changed

    async def _run(self) -> None:
        while True:
            try:
                await self.publish_if_changed()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("Resource advisor sample failed: %s", error, exc_info=True)
            await asyncio.sleep(self._sample_interval_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
