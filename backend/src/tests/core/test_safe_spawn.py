"""safe_spawn must route eligible spawns through posix_spawn and leave fork-only spawns alone."""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from api.core.runtime import safe_spawn

pytestmark = pytest.mark.skipif(not getattr(subprocess, "_USE_POSIX_SPAWN", False), reason="posix_spawn unavailable")


@pytest.fixture
def posix_spawn_calls(monkeypatch):
    calls = []
    original = subprocess.Popen._posix_spawn

    def spy(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "_posix_spawn", spy)
    return calls


def test_eligibility_rules():
    assert safe_spawn.posix_spawn_eligible({}) is True
    assert safe_spawn.posix_spawn_eligible({"capture_output": True, "env": {"A": "1"}}) is True
    for blocked in (
        {"cwd": "/tmp"},
        {"start_new_session": True},
        {"preexec_fn": lambda: None},
        {"pass_fds": (5,)},
        {"user": "root"},
        {"group": "wheel"},
        {"process_group": 0},
        {"umask": 0o22},
        {"shell": True},
    ):
        assert safe_spawn.posix_spawn_eligible(blocked) is False, blocked
    assert safe_spawn.posix_spawn_eligible({"umask": -1}) is True


def test_resolve_executable_returns_an_absolute_path_for_known_programs_and_passes_unknown_through():
    assert safe_spawn.resolve_executable("sh").startswith("/")
    assert safe_spawn.resolve_executable("/bin/sh") == "/bin/sh"
    assert safe_spawn.resolve_executable("definitely-not-a-real-program-xyz") == "definitely-not-a-real-program-xyz"


def test_sync_run_uses_posix_spawn_when_eligible(posix_spawn_calls):
    result = safe_spawn.run(["echo", "hello"], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "hello"
    assert len(posix_spawn_calls) == 1


def test_sync_run_keeps_the_fork_path_when_cwd_is_set(posix_spawn_calls, tmp_path):
    result = safe_spawn.run(["pwd"], capture_output=True, text=True, check=True, cwd=str(tmp_path))

    assert result.stdout.strip().endswith(tmp_path.name)
    assert posix_spawn_calls == []


def test_explicit_close_fds_from_the_caller_is_respected(posix_spawn_calls):
    safe_spawn.run(["echo", "x"], capture_output=True, close_fds=True)

    assert posix_spawn_calls == []


def test_missing_program_still_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        safe_spawn.run(["definitely-not-a-real-program-xyz"], capture_output=True)


@pytest.mark.asyncio
async def test_async_spawn_uses_posix_spawn_and_returns_output(posix_spawn_calls):
    process = await safe_spawn.create_subprocess_exec(
        "echo", "async-hello", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _stderr = await process.communicate()

    assert stdout.decode().strip() == "async-hello"
    assert process.returncode == 0
    assert len(posix_spawn_calls) == 1


@pytest.mark.asyncio
async def test_async_spawn_with_start_new_session_keeps_the_fork_path(posix_spawn_calls):
    process = await safe_spawn.create_subprocess_exec(
        "echo", "x", stdout=asyncio.subprocess.PIPE, start_new_session=True
    )
    await process.communicate()

    assert posix_spawn_calls == []


@pytest.mark.asyncio
async def test_slow_spawn_is_reported(monkeypatch):
    async def slow_exec(program, *args, **kwargs):
        return object()

    ticks = iter([100.0, 103.5])
    monkeypatch.setattr(safe_spawn.asyncio, "create_subprocess_exec", slow_exec)
    monkeypatch.setattr(safe_spawn, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    warnings = []
    monkeypatch.setattr(safe_spawn, "logger", SimpleNamespace(warning=lambda message, *args: warnings.append(message % args), debug=lambda *a: None))

    await safe_spawn.create_subprocess_exec("echo", "x")

    assert any("took 3.5s" in warning for warning in warnings)
