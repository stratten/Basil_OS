"""Unit coverage for the IOPM power-assertion helpers in
``scheduled_run_execution``.

These tests do NOT spin up the full scheduled-run pipeline -- the goal
here is to lock the assertion-lifecycle contract in place so future
edits to ``execute_scheduled_run`` (or to the helpers themselves)
cannot silently drop a sleep-prevention call:

  1. Each ``_prevent_idle_system_sleep_for_scheduled_run`` invocation on
     macOS calls ``IOPMAssertionCreateWithName`` exactly once and
     ``IOPMAssertionRelease`` exactly once with the matching id.
  2. Concurrent / nested ``with`` blocks for distinct runs get
     independent assertion ids; releasing one never releases the other.
  3. On non-darwin platforms (``sys.platform != 'darwin'``) the helpers
     short-circuit to no-ops so Linux CI does not try to dlopen
     IOKit.framework.

These behaviors directly mitigate the 2026-05-22 incident where macOS
Maintenance Sleep suspended an in-flight ``osascript`` subprocess for
957 s during a scheduled run.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Dict, List, Tuple
from unittest.mock import patch

import pytest

from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import (
    scheduled_run_execution as sre,
)


class _FakeIOKit:
    """Pure-Python double for the IOKit symbols we actually use.

    We need to fake at the bound-ctypes layer rather than at the
    helper-function layer because the production helpers go straight
    from ``ctypes.byref`` into IOKit -- there's no Python seam in
    between to intercept. Each instance assigns monotonically
    increasing assertion ids so tests can assert id uniqueness across
    concurrent runs.
    """

    def __init__(self) -> None:
        self._next_id = 1
        self.create_calls: List[Dict[str, object]] = []
        self.release_calls: List[int] = []

    def IOPMAssertionCreateWithName(self, _type, level, _name, id_out):
        assigned = self._next_id
        self._next_id += 1
        self.create_calls.append({"level": level, "assigned_id": assigned})
        # ``id_out`` is a ctypes.byref(c_uint32) pointer; write into it
        # the same way the real IOKit symbol would.
        id_out._obj.value = assigned
        return 0  # kIOReturnSuccess

    def IOPMAssertionRelease(self, assertion_id):
        # The production code wraps the int in ``ctypes.c_uint32`` before
        # the FFI call; unwrap so the assertion list contains plain ints.
        value = assertion_id.value if hasattr(assertion_id, "value") else int(assertion_id)
        self.release_calls.append(value)
        return 0


class _FakeCoreFoundation:
    """Pure-Python double for the two CF symbols we use.

    Returns a non-NULL "pointer" (an opaque int) for every
    ``CFStringCreateWithCString`` call and records release-balance so
    we can assert we don't leak CFString allocations.
    """

    def __init__(self) -> None:
        self._next_handle = 0x1000
        self._live_handles: set[int] = set()
        self.create_count = 0
        self.release_count = 0

    def CFStringCreateWithCString(self, _alloc, _cstr, _encoding):
        self._next_handle += 1
        handle = self._next_handle
        self._live_handles.add(handle)
        self.create_count += 1
        return handle

    def CFRelease(self, handle):
        # The production code passes the raw int back, not a ctypes
        # object, so this is symmetric.
        self.release_count += 1
        # Don't enforce membership -- failure-path tests deliberately
        # call CFRelease on the slots that *did* succeed.
        self._live_handles.discard(int(handle))


def _install_fake_libs() -> Tuple[_FakeIOKit, _FakeCoreFoundation]:
    """Swap the module-level libs for fakes; return them for assertions."""
    fake_iokit = _FakeIOKit()
    fake_cf = _FakeCoreFoundation()
    # The production code accesses _POWER_ASSERTION_LIBS via
    # ``sre._POWER_ASSERTION_LIBS`` and reads either ``iokit`` or ``cf``
    # off of it, so we mirror that shape.
    sre._POWER_ASSERTION_LIBS = {"iokit": fake_iokit, "cf": fake_cf}
    return fake_iokit, fake_cf


@pytest.fixture
def fake_libs(monkeypatch):
    """Install fakes for the test duration and restore on teardown."""
    original = sre._POWER_ASSERTION_LIBS
    fake_iokit, fake_cf = _install_fake_libs()
    try:
        yield fake_iokit, fake_cf
    finally:
        sre._POWER_ASSERTION_LIBS = original


def test_context_manager_acquires_and_releases_exactly_once(fake_libs):
    """Single ``with`` block: 1 create call + 1 matching release call."""
    fake_iokit, fake_cf = fake_libs

    with sre._prevent_idle_system_sleep_for_scheduled_run(
        scheduled_agent_task_id="sched-001",
        run_id="run-A",
    ) as assertion_id:
        # Inside the block the assertion is held.
        assert assertion_id is not None
        assert len(fake_iokit.create_calls) == 1
        assert len(fake_iokit.release_calls) == 0
        # The level we requested must be ``kIOPMAssertionLevelOn`` (255)
        # -- the constant the IOKit docs require for an *active*
        # assertion. Sending 0 would build the assertion but not
        # actually block sleep.
        assert fake_iokit.create_calls[0]["level"] == sre._IOPM_ASSERTION_LEVEL_ON

    # On exit the same id must have been released.
    assert fake_iokit.release_calls == [assertion_id]
    # CFStrings (the type + the name) must be released symmetrically
    # with their creates so we don't leak per-run.
    assert fake_cf.create_count == fake_cf.release_count == 2


def test_concurrent_runs_get_isolated_assertion_ids(fake_libs):
    """Two overlapping ``with`` blocks must not stomp each other's id.

    Simulates two scheduled runs starting before either finishes -- the
    real ``AsyncScheduledAgentTaskRunner`` is unbounded across distinct
    scheduled_agent_task_ids, so this is the realistic case under load.
    """
    fake_iokit, _fake_cf = fake_libs

    cm_a = sre._prevent_idle_system_sleep_for_scheduled_run(
        scheduled_agent_task_id="sched-A",
        run_id="run-A",
    )
    cm_b = sre._prevent_idle_system_sleep_for_scheduled_run(
        scheduled_agent_task_id="sched-B",
        run_id="run-B",
    )

    id_a = cm_a.__enter__()
    id_b = cm_b.__enter__()

    try:
        # Distinct ids -- they're allocated from a counter inside the
        # fake, so id_a < id_b strictly.
        assert id_a is not None
        assert id_b is not None
        assert id_a != id_b
        assert len(fake_iokit.create_calls) == 2
        assert fake_iokit.release_calls == []
    finally:
        # Release in reverse order (B first, then A) -- this is the
        # nesting order Python's contextlib produces for stacked
        # ``with`` blocks. Each ``__exit__`` must release exactly its
        # own id, not the other.
        cm_b.__exit__(None, None, None)
        assert fake_iokit.release_calls == [id_b]
        cm_a.__exit__(None, None, None)
        assert fake_iokit.release_calls == [id_b, id_a]


def test_context_manager_releases_on_exception(fake_libs):
    """An exception inside the ``with`` body must still release the id.

    Without this guarantee, a raise from anywhere in
    ``execute_scheduled_run`` would leak the assertion and pin the
    machine awake until the process exited -- defeating the whole
    point of scoping the assertion per-run.
    """
    fake_iokit, _fake_cf = fake_libs

    with pytest.raises(RuntimeError, match="boom"):
        with sre._prevent_idle_system_sleep_for_scheduled_run(
            scheduled_agent_task_id="sched-001",
            run_id="run-X",
        ):
            assert len(fake_iokit.create_calls) == 1
            raise RuntimeError("boom")

    # Exactly one create + exactly one matching release, even on the
    # exception path.
    assert len(fake_iokit.create_calls) == 1
    assert len(fake_iokit.release_calls) == 1


def test_non_darwin_skip_path_returns_none(monkeypatch):
    """When ``_POWER_ASSERTION_LIBS`` is ``None`` (non-macOS or
    framework dlopen failure), the helpers must short-circuit cleanly:

      * ``_acquire_*`` returns ``None`` without raising.
      * ``_release_*(None, ...)`` is a no-op.
      * The context manager yields ``None`` and exits cleanly.

    This is what lets Linux CI run the rest of the scheduled-tasks
    suite without IOKit available.
    """
    monkeypatch.setattr(sre, "_POWER_ASSERTION_LIBS", None)

    acquired = sre._acquire_prevent_idle_system_sleep(name="basil.scheduled_run:test")
    assert acquired is None

    # Must not raise.
    sre._release_prevent_idle_system_sleep(None, name="basil.scheduled_run:test")

    with sre._prevent_idle_system_sleep_for_scheduled_run(
        scheduled_agent_task_id="sched-skip",
        run_id="run-skip",
    ) as assertion_id:
        assert assertion_id is None


def test_acquire_returns_none_when_iokit_create_fails(fake_libs):
    """A non-zero IOKit return code must surface as a ``None`` id, NOT
    raise, so the calling run continues without sleep protection rather
    than aborting outright.
    """
    fake_iokit, fake_cf = fake_libs

    def failing_create(_type, _level, _name, _id_out):
        return -1  # any non-zero == failure

    with patch.object(fake_iokit, "IOPMAssertionCreateWithName", failing_create):
        with sre._prevent_idle_system_sleep_for_scheduled_run(
            scheduled_agent_task_id="sched-001",
            run_id="run-fail",
        ) as assertion_id:
            assert assertion_id is None

    # Even on the failure path we must release the CFStrings we
    # allocated so we don't leak per-run.
    assert fake_cf.create_count == fake_cf.release_count == 2
    # And ``_release_prevent_idle_system_sleep`` must NOT have been
    # invoked against IOKit since we never got a valid id.
    assert fake_iokit.release_calls == []


def test_load_power_assertion_frameworks_skips_on_non_darwin(monkeypatch):
    """Module loader returns ``None`` on non-darwin platforms instead of
    trying to dlopen IOKit.framework (which would raise ``OSError``)."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert sre._load_power_assertion_frameworks() is None


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Real IOKit framework is only available on macOS",
)
def test_real_iokit_round_trip_on_macos():
    """End-to-end smoke against the real IOKit on macOS: acquire and
    release a short-lived assertion and assert both succeed. Skipped
    on Linux/CI; meant to catch regressions in the ctypes binding
    (argtypes, restype, struct layout) when run locally on a Mac.
    """
    libs = sre._load_power_assertion_frameworks()
    assert libs is not None, "IOKit should load on darwin"
    # Restore the freshly-loaded real libs in case a previous test
    # in the same process installed fakes.
    original = sre._POWER_ASSERTION_LIBS
    sre._POWER_ASSERTION_LIBS = libs
    try:
        assertion_id = sre._acquire_prevent_idle_system_sleep(
            name="basil.tests.power_assertion_smoke"
        )
        assert isinstance(assertion_id, int)
        sre._release_prevent_idle_system_sleep(
            assertion_id, name="basil.tests.power_assertion_smoke"
        )
    finally:
        sre._POWER_ASSERTION_LIBS = original
