"""Tests for the bounded search subprocess runner: partial output, timeouts, truncation, and kill-on-cancel."""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.search_subprocess import (
    run_bounded_search_process,
)


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _wait_for_pid_exit(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(0.05)
    return not _pid_alive(pid)


@pytest.mark.asyncio
async def test_complete_run_returns_all_lines():
    outcome = await run_bounded_search_process(
        _python("print('/a/one.pdf'); print('/a/two.pdf'); print('/a/three.pdf')"),
        timeout_seconds=10,
    )
    assert outcome.lines == ["/a/one.pdf", "/a/two.pdf", "/a/three.pdf"]
    assert outcome.returncode == 0
    assert outcome.timed_out is False
    assert outcome.truncated is False
    assert outcome.complete is True


@pytest.mark.asyncio
async def test_nonzero_exit_keeps_printed_lines_and_stderr_tail():
    code = (
        "import sys; print('/drive/match.pdf', flush=True); "
        "sys.stderr.write('find: /drive/locked: Permission denied\\n'); sys.exit(1)"
    )
    outcome = await run_bounded_search_process(_python(code), timeout_seconds=10)
    assert outcome.lines == ["/drive/match.pdf"]
    assert outcome.returncode == 1
    assert "Permission denied" in outcome.stderr_tail
    assert outcome.complete is False


@pytest.mark.asyncio
async def test_timeout_keeps_partial_lines_and_kills_child():
    code = "import time; print('/early/hit.pdf', flush=True); time.sleep(30)"
    started = time.monotonic()
    outcome = await run_bounded_search_process(_python(code), timeout_seconds=0.75)
    elapsed = time.monotonic() - started
    assert outcome.timed_out is True
    assert outcome.lines == ["/early/hit.pdf"]
    assert outcome.returncode is not None
    assert elapsed < 6.0


@pytest.mark.asyncio
async def test_max_lines_truncates_and_stops_the_child():
    code = "import time\nfor i in range(50):\n    print(f'/many/{i}.txt', flush=True)\ntime.sleep(30)"
    started = time.monotonic()
    outcome = await run_bounded_search_process(_python(code), timeout_seconds=20, max_lines=10)
    assert outcome.truncated is True
    assert len(outcome.lines) == 10
    assert outcome.returncode is not None
    assert time.monotonic() - started < 6.0


@pytest.mark.asyncio
async def test_cancellation_kills_the_process_group(tmp_path):
    pid_file = tmp_path / "child.pid"
    code = (
        "import os, time; "
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid())); "
        "time.sleep(30)"
    )
    task = asyncio.create_task(run_bounded_search_process(_python(code), timeout_seconds=30))
    deadline = time.monotonic() + 5.0
    while not pid_file.exists() or not pid_file.read_text().strip():
        assert time.monotonic() < deadline, "child never started"
        await asyncio.sleep(0.05)
    child_pid = int(pid_file.read_text().strip())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _wait_for_pid_exit(child_pid) is True


@pytest.mark.asyncio
async def test_child_stdin_is_closed_so_reading_input_does_not_hang():
    code = "import sys; data = sys.stdin.read(); print(f'stdin={len(data)}')"
    outcome = await run_bounded_search_process(_python(code), timeout_seconds=5)
    assert outcome.timed_out is False
    assert outcome.lines == ["stdin=0"]
