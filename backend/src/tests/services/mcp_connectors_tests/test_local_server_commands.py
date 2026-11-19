"""Running preparation commands: no shell, a trimmed environment, time limits, and bounded output."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from api.services.mcp_connectors.local_server_commands import MAX_OUTPUT_CHARS, run_command, scrubbed_env, search_path


@pytest.mark.asyncio
async def test_a_command_runs_without_a_shell_and_reports_its_output_and_exit_code(tmp_path):
    ok = await run_command([sys.executable, "-c", "print('hello; echo not-a-shell')"], cwd=tmp_path)
    failed = await run_command([sys.executable, "-c", "import sys; print('bad'); sys.exit(3)"])

    assert ok.ok and ok.output == "hello; echo not-a-shell"
    assert failed.returncode == 3 and failed.output == "bad" and not failed.ok


@pytest.mark.asyncio
async def test_a_missing_program_and_an_unstartable_one_are_reported_not_raised(tmp_path):
    missing = await run_command(["definitely-not-a-real-program-xyz"])
    not_executable = tmp_path / "plain.txt"
    not_executable.write_text("x")
    unrunnable = await run_command([str(not_executable)])

    assert missing.returncode == 127 and "was not found" in missing.output
    assert unrunnable.returncode == 127


@pytest.mark.asyncio
async def test_basils_own_secrets_are_not_passed_but_declared_values_are(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("HOME", "/Users/someone")

    result = await run_command([sys.executable, "-c", "import os; print(sorted(k for k in os.environ if 'KEY' in k or k == 'DECLARED')); print(os.environ['HOME'])"], extra_env={"DECLARED": "yes"})

    assert result.output.splitlines() == ["['DECLARED']", "/Users/someone"]


def test_the_search_path_keeps_the_current_entries_first_and_adds_the_usual_install_places_once():
    path = search_path({"PATH": "/custom/bin:/usr/bin"}).split(os.pathsep)

    assert path[:2] == ["/custom/bin", "/usr/bin"]
    assert "/opt/homebrew/bin" in path and "/usr/local/go/bin" in path
    assert len(path) == len(set(path))
    assert scrubbed_env({"PATH": "/x", "SECRET": "s", "HOME": "/h"}, {"A": "b"}) == {"HOME": "/h", "PATH": search_path({"PATH": "/x"}), "A": "b"}


@pytest.mark.asyncio
async def test_a_command_that_runs_too_long_is_stopped(tmp_path):
    marker = tmp_path / "survived"
    code = f"import time, pathlib; time.sleep(30); pathlib.Path({str(marker)!r}).write_text('x')"

    result = await run_command([sys.executable, "-c", code], timeout=0.5)

    assert result.returncode == 124 and "did not finish within" in result.output
    await asyncio.sleep(0.2)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_canceling_the_caller_kills_the_command_and_its_children(tmp_path):
    pid_file = tmp_path / "child.pid"
    code = f"import os, subprocess, sys, time; child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); open({str(pid_file)!r}, 'w').write(str(child.pid)); time.sleep(60)"
    task = asyncio.create_task(run_command([sys.executable, "-c", code]))
    for _ in range(200):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.02)
    child_pid = int(pid_file.read_text())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.asyncio
async def test_very_long_output_is_cut_to_its_end():
    result = await run_command([sys.executable, "-c", "print('x' * 100000 + 'END')"])

    assert result.output.endswith("END") and len(result.output) <= MAX_OUTPUT_CHARS + 1
