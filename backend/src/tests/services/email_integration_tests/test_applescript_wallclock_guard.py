"""Unit coverage for the wall-clock watchdog in
``AppleScriptAutomationService.execute_applescript``.

The watchdog exists because ``asyncio.wait_for`` is keyed to a
monotonic clock that pauses through macOS sleep. On 2026-05-22 the
8 PM scheduled task ran for 957 s wall-clock with the 90 s
``email_read_applescript_timeout`` never firing, because the laptop
spent ~16 min in Maintenance Sleep mid-call.

Four behaviors are locked here:

  1. Drift WARN fires exactly once per call when wall-clock elapsed
     races ahead of monotonic elapsed (the post-wake signature).
  2. Watchdog terminates the subprocess once wall-clock elapsed
     crosses ``timeout * _WALLCLOCK_BOUND_MULTIPLIER``.
  3. A normal short call produces no WARN, no termination, and
     returns ``success=True`` -- the watchdog stays out of the way.
  4. The error string the watchdog produces preserves the
     ``"Timeout after N seconds"`` prefix that
     ``test_email_task_reliability`` keys off of.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration import (
    applescript_automation_service as svc,
)


@dataclass
class _FakeProcess:
    """In-memory stand-in for ``asyncio.subprocess.Process``.

    Records ``kill()`` invocations so we can assert the watchdog reached
    them. ``communicate()`` blocks until ``kill()`` (simulating a wedged
    osascript) so the production code path -- ``await
    wait_for(process.communicate(), timeout=...)`` -- behaves the same
    way it does against a real subprocess.
    """

    pid: int = 4242
    returncode: Optional[int] = None
    stdout_payload: bytes = b""
    stderr_payload: bytes = b""
    kill_calls: int = 0
    terminate_calls: int = 0
    _done_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def communicate(self):
        await self._done_event.wait()
        return self.stdout_payload, self.stderr_payload

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        self._done_event.set()

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = -15
        self._done_event.set()

    async def wait(self):
        await self._done_event.wait()
        return self.returncode


@dataclass
class _FastForwardClock:
    """Test-controlled wall clock.

    The watchdog reads ``time.time()`` to compute wall-clock elapsed.
    Letting tests yank that value forward simulates "we just woke from
    macOS Maintenance Sleep" without actually sleeping the test
    runner. ``advance(n)`` advances the simulated wall clock by n
    seconds.
    """

    base: float
    offset: float = 0.0

    def __call__(self) -> float:
        return self.base + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += seconds


@pytest.fixture
def fast_watchdog_interval(monkeypatch):
    """Shrink the watchdog poll interval so tests finish in <1 s.

    Production runs at 1 s; tests at 50 ms. Monkey-patching the module
    attribute works because ``_wallclock_watchdog`` looks the constant
    up at call time, not at import time.
    """
    monkeypatch.setattr(svc, "_WATCHDOG_POLL_INTERVAL_SECONDS", 0.05)
    yield


@pytest.fixture
def fake_wall_clock(monkeypatch):
    """Replace ``time.time()`` with a fast-forwardable clock."""
    import time as real_time

    clock = _FastForwardClock(base=real_time.time())
    monkeypatch.setattr(svc.time, "time", clock)
    yield clock


@pytest.fixture
def caplog_warnings(caplog):
    """Capture WARNING+ from the service module logger."""
    caplog.set_level(logging.WARNING, logger=svc.logger.name)
    return caplog


# ---------------------------------------------------------------------------
# Watchdog-in-isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchdog_warns_once_on_post_sleep_drift(
    fast_watchdog_interval, fake_wall_clock, caplog_warnings
):
    """One wall-clock jump produces exactly one drift WARN, even across
    multiple subsequent polls."""
    process = _FakeProcess()
    state = svc._WallclockWatchdogState()
    start_mono = asyncio.get_event_loop().time()
    start_wall = fake_wall_clock()

    task = asyncio.create_task(
        svc._wallclock_watchdog(
            process,
            timeout_seconds=60,
            start_monotonic=start_mono,
            start_wall=start_wall,
            description="metadata fetch (test)",
            state=state,
        )
    )

    # Let the watchdog poll twice with no drift -- this guards against
    # a watchdog that misfires on cold start.
    await asyncio.sleep(0.15)
    assert state.drift_warned is False

    # Simulate a 30 s wall-clock jump (post-Maintenance-Sleep wake)
    # without crossing the kill threshold (60 s * 2 = 120 s).
    fake_wall_clock.advance(30.0)
    await asyncio.sleep(0.15)
    assert state.drift_warned is True
    assert state.terminated_by_watchdog is False
    assert process.kill_calls == 0

    # A second jump (still under the kill threshold) must NOT log a
    # second WARN. The latch is one-shot per call.
    fake_wall_clock.advance(20.0)
    await asyncio.sleep(0.15)
    drift_records = [
        r for r in caplog_warnings.records if "wall-clock drift" in r.message
    ]
    assert len(drift_records) == 1, (
        f"expected exactly one drift WARN, got {len(drift_records)}: "
        f"{[r.message for r in drift_records]}"
    )

    # The watchdog's own ``await asyncio.sleep`` catches CancelledError
    # and returns cleanly (see the production try/except), so canceling
    # the task should NOT propagate CancelledError up to ``await task``.
    task.cancel()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done() and not task.cancelled()


@pytest.mark.asyncio
async def test_watchdog_terminates_subprocess_at_bound_multiplier(
    fast_watchdog_interval, fake_wall_clock
):
    """Wall-clock crossing ``timeout * _WALLCLOCK_BOUND_MULTIPLIER``
    must result in exactly one ``process.kill()`` call and the state
    flag flipping."""
    process = _FakeProcess()
    state = svc._WallclockWatchdogState()
    start_mono = asyncio.get_event_loop().time()
    start_wall = fake_wall_clock()
    timeout = 10  # bound = 20 s wall

    task = asyncio.create_task(
        svc._wallclock_watchdog(
            process,
            timeout_seconds=timeout,
            start_monotonic=start_mono,
            start_wall=start_wall,
            description="test",
            state=state,
        )
    )

    # Jump past the kill threshold in one shot.
    fake_wall_clock.advance(25.0)
    await asyncio.sleep(0.15)

    assert state.terminated_by_watchdog is True
    assert state.wall_elapsed_at_kill >= timeout * svc._WALLCLOCK_BOUND_MULTIPLIER
    assert process.kill_calls == 1

    # Watchdog must exit on its own after the kill -- no need to cancel.
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done() and not task.cancelled()


@pytest.mark.asyncio
async def test_watchdog_no_false_positives_on_short_normal_call(
    fast_watchdog_interval, caplog_warnings
):
    """A short normal call must produce no WARN and no kill.

    We do NOT patch ``time.time`` here -- real wall clock and real
    monotonic clock advance together, so the watchdog should sit idle.
    """
    process = _FakeProcess()
    state = svc._WallclockWatchdogState()
    start_mono = asyncio.get_event_loop().time()
    start_wall = svc.time.time()

    task = asyncio.create_task(
        svc._wallclock_watchdog(
            process,
            timeout_seconds=60,
            start_monotonic=start_mono,
            start_wall=start_wall,
            description="short-normal-call",
            state=state,
        )
    )

    # Let several polls happen.
    await asyncio.sleep(0.25)
    # Subprocess "completes" cleanly.
    process.returncode = 0
    process._done_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert state.drift_warned is False
    assert state.terminated_by_watchdog is False
    assert process.kill_calls == 0
    drift_records = [
        r for r in caplog_warnings.records if "wall-clock drift" in r.message
    ]
    assert drift_records == [], (
        f"watchdog should be silent on a normal call but logged: "
        f"{[r.message for r in drift_records]}"
    )


# ---------------------------------------------------------------------------
# execute_applescript end-to-end (watchdog wired in)
# ---------------------------------------------------------------------------


def _patched_subprocess_exec(process: _FakeProcess):
    """Build an async stand-in for ``asyncio.create_subprocess_exec``."""

    async def _factory(*args, **kwargs):
        return process

    return _factory


@pytest.mark.asyncio
async def test_execute_applescript_preserves_timeout_error_prefix(
    fast_watchdog_interval, fake_wall_clock, monkeypatch
):
    """When the wall-clock watchdog kills the subprocess, the returned
    ``AppleScriptResult.error`` must still start with ``"Timeout after
    N seconds"`` so the existing
    ``test_email_task_reliability`` fixture keeps matching.
    """
    process = _FakeProcess()
    monkeypatch.setattr(
        svc.asyncio,
        "create_subprocess_exec",
        _patched_subprocess_exec(process),
    )

    service = svc.AppleScriptAutomationService(timeout=10)

    async def _drive_watchdog():
        # Wait long enough for the watchdog to poll once with the
        # normal clock, then yank wall clock past the kill threshold.
        await asyncio.sleep(0.1)
        fake_wall_clock.advance(25.0)

    drive = asyncio.create_task(_drive_watchdog())
    result = await service.execute_applescript('tell app "Finder" to return "x"', "test")
    await drive

    assert result.success is False
    assert isinstance(result.error, str)
    assert result.error.startswith("Timeout after 10 seconds"), (
        f"watchdog-driven failure must preserve the 'Timeout after N seconds' "
        f"prefix, got: {result.error!r}"
    )
    assert process.kill_calls >= 1


@pytest.mark.asyncio
async def test_execute_applescript_happy_path_no_watchdog_interference(
    fast_watchdog_interval, monkeypatch
):
    """A subprocess that returns promptly with ``returncode=0`` must
    flow through the existing success path untouched. This guards
    against the watchdog accidentally racing the happy path.
    """
    process = _FakeProcess(stdout_payload=b"hello world", returncode=None)

    async def _eager_factory(*args, **kwargs):
        # Complete the fake subprocess on the very next loop iteration.
        loop = asyncio.get_running_loop()
        loop.call_soon(lambda: (setattr(process, "returncode", 0), process._done_event.set()))
        return process

    monkeypatch.setattr(svc.asyncio, "create_subprocess_exec", _eager_factory)

    service = svc.AppleScriptAutomationService(timeout=30)
    result = await service.execute_applescript('return 1', "test-happy")

    assert result.success is True
    assert result.data == "hello world"
    assert process.kill_calls == 0
    assert process.terminate_calls == 0


@pytest.mark.asyncio
async def test_execute_applescript_monotonic_timeout_still_works(
    fast_watchdog_interval, monkeypatch
):
    """When monotonic time genuinely exceeds the configured timeout
    (no OS sleep), ``asyncio.wait_for`` still raises ``TimeoutError``
    and we get the original ``"Timeout after N seconds"`` error from
    the existing except branch -- the watchdog never enters the
    picture.
    """
    process = _FakeProcess()  # communicate() blocks until kill()/terminate()

    monkeypatch.setattr(
        svc.asyncio,
        "create_subprocess_exec",
        _patched_subprocess_exec(process),
    )

    service = svc.AppleScriptAutomationService(timeout=1)  # 1 s timeout
    result = await service.execute_applescript('return 1', "test-mono-timeout")

    assert result.success is False
    assert result.error == "Timeout after 1 seconds"
    # The existing TimeoutError branch calls ``process.terminate()``
    # first, then escalates to kill if the process doesn't exit
    # within 5 s. Our fake exits immediately on terminate(), so
    # terminate_calls should be 1 and kill_calls should be 0.
    assert process.terminate_calls == 1
    assert process.kill_calls == 0
