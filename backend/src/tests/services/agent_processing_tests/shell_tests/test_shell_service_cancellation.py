"""Negative test: ShellService must not orphan its child process on cancel.

Before the fix, ShellService.execute_command had no ``except asyncio.CancelledError``
around ``proc.communicate()``, so a Task.cancel() (e.g. from preemptive agent-task
cancellation) unwound the coroutine while leaving the spawned subprocess running.
This test launches a long-lived ``sleep`` child, cancels the awaiting task, and
asserts the child is terminated (returncode set) and CancelledError propagates.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from api.services.agent_processing.tools.direct_application_interactions.shell import (
    shell_service as shell_service_module,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import (
    ShellService,
)


@pytest.mark.asyncio
async def test_execute_command_terminates_subprocess_on_cancel(monkeypatch):
    service = ShellService()

    captured: dict = {}
    real_exec = asyncio.create_subprocess_exec

    async def _capturing_exec(*args, **kwargs):
        proc = await real_exec(*args, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(
        shell_service_module.asyncio, "create_subprocess_exec", _capturing_exec
    )

    task = asyncio.create_task(
        service.execute_command(
            command="sleep", args=["30"], skip_approval_check=True
        )
    )

    # Wait until the child process has actually been spawned.
    for _ in range(500):
        if "proc" in captured:
            break
        await asyncio.sleep(0.01)
    assert "proc" in captured, "subprocess was never launched"

    proc = captured["proc"]
    assert proc.returncode is None, "child should still be running before cancel"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The cancel handler must have terminated (SIGTERM/SIGKILL) and reaped the
    # child, so its returncode is now populated instead of orphaned.
    assert proc.returncode is not None


@pytest.mark.asyncio
async def test_execute_command_terminates_shell_process_group_on_cancel(tmp_path):
    service = ShellService()
    child_pid_path = tmp_path / "child.pid"
    command = f"sleep 30 & echo $! > {child_pid_path}; wait"
    task = asyncio.create_task(
        service.execute_command(
            command="bash",
            args=["-lc", command],
            skip_approval_check=True,
        )
    )

    for _ in range(200):
        if child_pid_path.exists() and child_pid_path.read_text().strip():
            break
        await asyncio.sleep(0.01)
    assert child_pid_path.exists()
    child_pid = int(child_pid_path.read_text().strip())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail(f"shell child process {child_pid} survived cancellation")
