"""Unit coverage for the wall-clock watchdog in
``GenericAppleScriptService.execute_applescript``.

Same root cause as
``test_applescript_wallclock_guard.py``: ``asyncio.wait_for`` uses a
monotonic clock that pauses through macOS sleep, so the configured
60 s ``execution_timeout_s`` can be silently bypassed on a sleeping
laptop. The generic service's clocks are flipped relative to the
email service (primary = wall, companion = monotonic) so this file
covers the same four behaviors independently:

  1. Drift WARN fires exactly once per call when wall-clock elapsed
     races ahead of monotonic elapsed.
  2. Watchdog terminates the subprocess once wall-clock elapsed
     crosses ``execution_timeout_s * _WALLCLOCK_BOUND_MULTIPLIER``.
  3. A normal short call produces no WARN, no termination, and
     returns ``success=True``.
  4. The watchdog-triggered failure produces an error string that
     names the watchdog and the wall-clock kill threshold, so
     operators can recognize the OS-sleep failure mode in logs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import pytest

from api.core.models.preferences import BrowserForegroundControlPolicy, Preferences
from api.core.preferences import preferences_io
from api.services.agent_processing.tools.direct_application_interactions.applescript_automation import (
    generic_applescript_service as svc,
)


@dataclass
class _FakeProcess:
    """In-memory ``asyncio.subprocess.Process`` stand-in.

    Identical shape to the email-service watchdog test fixture so the
    two test files cover symmetric behavior. ``communicate()`` blocks
    until either ``kill()`` or ``terminate()`` is called, simulating a
    wedged osascript subprocess.
    """

    pid: int = 7777
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
    """Test-controlled wall clock for simulating macOS sleep wakeups."""
    base: float
    offset: float = 0.0

    def __call__(self) -> float:
        return self.base + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += seconds


@pytest.fixture
def fast_watchdog_interval(monkeypatch):
    """Shrink the watchdog poll interval so tests finish in <1 s."""
    monkeypatch.setattr(svc, "_WATCHDOG_POLL_INTERVAL_SECONDS", 0.05)
    yield


@pytest.fixture
def fake_wall_clock(monkeypatch):
    """Replace ``time.time()`` with a fast-forwardable clock.

    The generic service imports ``time`` at module top now, so the
    watchdog reads ``svc.time.time``.
    """
    import time as real_time

    clock = _FastForwardClock(base=real_time.time())
    monkeypatch.setattr(svc.time, "time", clock)
    yield clock


@pytest.fixture
def caplog_warnings(caplog):
    """Capture WARNING+ from the service module logger."""
    caplog.set_level(logging.WARNING, logger=svc.__name__)
    return caplog


# ---------------------------------------------------------------------------
# Watchdog-in-isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchdog_warns_once_on_post_sleep_drift(
    fast_watchdog_interval, fake_wall_clock, caplog_warnings
):
    """A single wall-clock jump produces exactly one drift WARN even
    across multiple subsequent polls."""
    process = _FakeProcess()
    state = svc._WallclockWatchdogState()
    start_mono = asyncio.get_event_loop().time()
    start_wall = fake_wall_clock()

    task = asyncio.create_task(
        svc._wallclock_watchdog(
            process,
            timeout_seconds=60.0,
            start_monotonic=start_mono,
            start_wall=start_wall,
            description="generic-script (test)",
            state=state,
        )
    )

    # No drift yet: watchdog must remain silent.
    await asyncio.sleep(0.15)
    assert state.drift_warned is False

    # 30 s wall-clock jump (post-Maintenance-Sleep wake), well under
    # the 120 s kill threshold.
    fake_wall_clock.advance(30.0)
    await asyncio.sleep(0.15)
    assert state.drift_warned is True
    assert state.terminated_by_watchdog is False
    assert process.kill_calls == 0

    # Second jump (still under kill threshold) must NOT fire another
    # WARN -- the latch is one-shot per call.
    fake_wall_clock.advance(15.0)
    await asyncio.sleep(0.15)
    drift_records = [
        r for r in caplog_warnings.records if "wall-clock drift" in r.message
    ]
    assert len(drift_records) == 1, (
        f"expected exactly one drift WARN, got {len(drift_records)}: "
        f"{[r.message for r in drift_records]}"
    )

    # Watchdog's own ``asyncio.sleep`` catches CancelledError and
    # returns cleanly, so cancellation should not propagate.
    task.cancel()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done() and not task.cancelled()


@pytest.mark.asyncio
async def test_browser_foreground_policy_blocks_system_events_fallback(monkeypatch):
    preferences = Preferences()
    preferences.browser_automation.foreground_control_policy = (
        BrowserForegroundControlPolicy.BACKGROUND_ONLY
    )
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: preferences)
    service = svc.GenericAppleScriptService()

    result = await service._enforce_browser_foreground_control_policy(
        '''
        tell application "Safari"
            activate
        end tell
        tell application "System Events"
            keystroke "amazon"
        end tell
        ''',
        {"task_description": "add product to Amazon cart"},
    )

    assert result is not None
    assert result.success is False
    assert result.approval_denied is True
    assert "foreground control is disabled" in result.error


@pytest.mark.asyncio
async def test_watchdog_terminates_subprocess_at_bound_multiplier(
    fast_watchdog_interval, fake_wall_clock
):
    """Wall-clock crossing the kill threshold yields one ``kill()``
    call and the state flag flipping."""
    process = _FakeProcess()
    state = svc._WallclockWatchdogState()
    start_mono = asyncio.get_event_loop().time()
    start_wall = fake_wall_clock()
    timeout = 5.0  # kill threshold = 10 s wall

    task = asyncio.create_task(
        svc._wallclock_watchdog(
            process,
            timeout_seconds=timeout,
            start_monotonic=start_mono,
            start_wall=start_wall,
            description="generic-script (kill-path)",
            state=state,
        )
    )

    fake_wall_clock.advance(15.0)  # past 2x timeout
    await asyncio.sleep(0.15)

    assert state.terminated_by_watchdog is True
    assert (
        state.wall_elapsed_at_kill
        >= timeout * svc._WALLCLOCK_BOUND_MULTIPLIER
    )
    assert process.kill_calls == 1

    # Watchdog returns on its own after the kill -- no cancellation
    # needed.
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done() and not task.cancelled()


@pytest.mark.asyncio
async def test_watchdog_no_false_positives_on_short_normal_call(
    fast_watchdog_interval, caplog_warnings
):
    """No WARN, no kill on a normal short call (real wall+monotonic
    clocks advance together).
    """
    process = _FakeProcess()
    state = svc._WallclockWatchdogState()
    start_mono = asyncio.get_event_loop().time()
    start_wall = svc.time.time()

    task = asyncio.create_task(
        svc._wallclock_watchdog(
            process,
            timeout_seconds=60.0,
            start_monotonic=start_mono,
            start_wall=start_wall,
            description="short-normal-call",
            state=state,
        )
    )

    # Run several polls' worth.
    await asyncio.sleep(0.25)
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
    """Async stand-in for ``asyncio.create_subprocess_exec``."""

    async def _factory(*args, **kwargs):
        return process

    return _factory


@pytest.mark.asyncio
async def test_execute_applescript_watchdog_kill_yields_descriptive_error(
    fast_watchdog_interval, fake_wall_clock, monkeypatch
):
    """When the watchdog kills, the returned ``AppleScriptResult.error``
    names the watchdog and the wall-clock kill threshold. Operators
    triaging a stuck scheduled run should be able to recognize the
    OS-sleep failure mode directly from the log line.
    """
    process = _FakeProcess()
    monkeypatch.setattr(
        svc.asyncio,
        "create_subprocess_exec",
        _patched_subprocess_exec(process),
    )

    service = svc.GenericAppleScriptService(knowledge_service=None)
    service.execution_timeout_s = 10.0

    async def _drive_watchdog():
        # Let the watchdog poll once on a normal clock, then yank the
        # wall clock past the kill threshold.
        await asyncio.sleep(0.1)
        fake_wall_clock.advance(25.0)

    drive = asyncio.create_task(_drive_watchdog())
    result = await service.execute_applescript(
        "tell application \"Finder\" to return \"x\"",
        skip_approval_check=True,
    )
    await drive

    assert result.success is False
    assert isinstance(result.error, str)
    # Must mention the timeout in canonical "timed out after Ns" form
    # AND the watchdog so operators can correlate.
    assert "timed out after 10s" in result.error
    assert "wall-clock watchdog" in result.error
    assert process.kill_calls >= 1


@pytest.mark.asyncio
async def test_execute_applescript_happy_path_no_watchdog_interference(
    fast_watchdog_interval, monkeypatch
):
    """A subprocess that returns promptly with ``returncode=0`` must
    flow through the existing success path untouched.
    """
    process = _FakeProcess(stdout_payload=b"hello", returncode=None)

    async def _eager_factory(*args, **kwargs):
        loop = asyncio.get_running_loop()
        loop.call_soon(
            lambda: (
                setattr(process, "returncode", 0),
                process._done_event.set(),
            )
        )
        return process

    monkeypatch.setattr(svc.asyncio, "create_subprocess_exec", _eager_factory)

    service = svc.GenericAppleScriptService(knowledge_service=None)
    service.execution_timeout_s = 30.0
    result = await service.execute_applescript(
        "return 1", skip_approval_check=True
    )

    assert result.success is True
    assert result.output == "hello"
    assert process.kill_calls == 0
    assert process.terminate_calls == 0


@pytest.mark.asyncio
async def test_execute_applescript_monotonic_timeout_still_works(
    fast_watchdog_interval, monkeypatch
):
    """When monotonic time genuinely exceeds the configured timeout
    (no OS sleep), ``asyncio.wait_for`` still raises ``TimeoutError``
    and we get the original "AppleScript execution timed out after
    Ns" error from the existing except branch -- watchdog stays out
    of the picture.
    """
    process = _FakeProcess()

    monkeypatch.setattr(
        svc.asyncio,
        "create_subprocess_exec",
        _patched_subprocess_exec(process),
    )

    service = svc.GenericAppleScriptService(knowledge_service=None)
    service.execution_timeout_s = 1.0
    result = await service.execute_applescript(
        "return 1", skip_approval_check=True
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("AppleScript execution timed out after 1s")
    # The existing TimeoutError branch terminates first; our fake
    # exits on terminate() so kill is not reached.
    assert process.terminate_calls == 1
    assert process.kill_calls == 0
