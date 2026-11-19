"""Tests for the shell process runner: prompts, relays, partial output, and both timeout clocks."""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

from api.services.agent_processing.tools.direct_application_interactions.shell import (
    shell_process_runner as runner_module,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_process_runner import (
    MAX_INPUT_RELAYS,
    CommandInputReply,
    run_shell_process,
)


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _env() -> dict[str, str]:
    return dict(os.environ)


class RecordingRequester:
    def __init__(self, replies, delay_seconds: float = 0.0):
        self._replies = list(replies)
        self._delay_seconds = delay_seconds
        self.calls: list[tuple[str, bool]] = []

    async def __call__(self, prompt: str, secret: bool) -> CommandInputReply:
        self.calls.append((prompt, secret))
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        if len(self._replies) > 1:
            return self._replies.pop(0)
        return self._replies[0]


@pytest.mark.asyncio
async def test_timeout_keeps_partial_output():
    run = await run_shell_process(
        _python("import time; print('first line', flush=True); time.sleep(30)"),
        cwd=None,
        env=_env(),
        timeout_seconds=1.0,
    )
    assert run.timed_out is True
    assert run.timeout_clock == "monotonic"
    assert b"first line" in run.stdout_bytes
    assert run.exit_code is not None


@pytest.mark.asyncio
async def test_wall_clock_bound_stops_command_after_sleep_jump(monkeypatch):
    real_wall_clock = time.time
    calls = {"count": 0}

    def jumping_wall_clock() -> float:
        calls["count"] += 1
        return real_wall_clock() if calls["count"] == 1 else real_wall_clock() + 100.0

    monkeypatch.setattr(runner_module, "_wall_clock", jumping_wall_clock)
    started = time.monotonic()
    run = await run_shell_process(
        _python("import time; time.sleep(30)"),
        cwd=None,
        env=_env(),
        timeout_seconds=30.0,
    )
    assert run.timed_out is True
    assert run.timeout_clock == "wall_clock"
    assert time.monotonic() - started < 10.0


@pytest.mark.asyncio
async def test_terminal_password_prompt_is_relayed_and_never_echoed():
    code = (
        "import os\n"
        "fd = os.open('/dev/tty', os.O_RDWR)\n"
        "os.write(fd, b'Password: ')\n"
        "answer = b''\n"
        "while not answer.endswith(b'\\n'):\n"
        "    answer += os.read(fd, 1)\n"
        "print('got:' + answer.decode().strip(), flush=True)\n"
    )
    requester = RecordingRequester([CommandInputReply(status="answered", text="hunter2")])
    run = await run_shell_process(
        _python(code), cwd=None, env=_env(), timeout_seconds=20.0, input_requester=requester
    )
    assert run.exit_code == 0
    assert b"got:hunter2" in run.stdout_bytes
    assert requester.calls == [("Password:", True)]
    assert "Password:" in run.terminal_output
    assert "hunter2" not in run.terminal_output
    assert run.input_exchanges == [{"prompt": "Password:", "secret": True, "status": "answered"}]


@pytest.mark.asyncio
async def test_stdin_confirmation_prompt_is_relayed():
    requester = RecordingRequester([CommandInputReply(status="answered", text="y")])
    run = await run_shell_process(
        _python("answer = input('Continue? [y/N] '); print('answer=' + answer)"),
        cwd=None,
        env=_env(),
        timeout_seconds=20.0,
        input_requester=requester,
    )
    assert run.exit_code == 0
    assert b"answer=y" in run.stdout_bytes
    assert requester.calls == [("Continue? [y/N]", False)]


@pytest.mark.asyncio
async def test_prompt_without_requester_stops_quickly_with_input_required():
    started = time.monotonic()
    run = await run_shell_process(
        _python("input('Overwrite existing file? [y/N] ')"),
        cwd=None,
        env=_env(),
        timeout_seconds=30.0,
    )
    assert run.input_status == "input_required"
    assert run.pending_prompt == "Overwrite existing file? [y/N]"
    assert run.timed_out is False
    assert time.monotonic() - started < 10.0


@pytest.mark.asyncio
async def test_canceled_reply_stops_the_command():
    requester = RecordingRequester([CommandInputReply(status="canceled")])
    run = await run_shell_process(
        _python("input('Proceed? '); print('should not print')"),
        cwd=None,
        env=_env(),
        timeout_seconds=20.0,
        input_requester=requester,
    )
    assert run.input_status == "input_canceled"
    assert b"should not print" not in run.stdout_bytes


@pytest.mark.asyncio
async def test_time_waiting_for_the_user_does_not_count_against_the_timeout():
    requester = RecordingRequester([CommandInputReply(status="answered", text="ok")], delay_seconds=3.0)
    run = await run_shell_process(
        _python("answer = input('Name: '); print('hello ' + answer)"),
        cwd=None,
        env=_env(),
        timeout_seconds=2.5,
        input_requester=requester,
    )
    assert run.timed_out is False
    assert b"hello ok" in run.stdout_bytes
    assert run.input_wait_ms >= 2_900


@pytest.mark.asyncio
async def test_relay_limit_stops_after_max_relays():
    code = "for i in range(MAX + 2):\n    input(f'Value {i}: ')\n".replace("MAX", str(MAX_INPUT_RELAYS))
    requester = RecordingRequester([CommandInputReply(status="answered", text="x")])
    run = await run_shell_process(
        _python(code), cwd=None, env=_env(), timeout_seconds=40.0, input_requester=requester
    )
    assert run.input_status == "input_limit"
    assert len(run.input_exchanges) == MAX_INPUT_RELAYS


@pytest.mark.asyncio
async def test_newline_terminated_output_is_not_treated_as_a_prompt():
    requester = RecordingRequester([CommandInputReply(status="answered", text="unused")])
    run = await run_shell_process(
        _python("import time; print('Results:', flush=True); time.sleep(1.6); print('done')"),
        cwd=None,
        env=_env(),
        timeout_seconds=20.0,
        input_requester=requester,
    )
    assert run.exit_code == 0
    assert requester.calls == []
    assert b"done" in run.stdout_bytes


@pytest.mark.asyncio
async def test_missing_executable_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        await run_shell_process(
            ["basil-definitely-missing-executable"], cwd=None, env=_env(), timeout_seconds=5.0
        )


@pytest.mark.asyncio
async def test_pid_reported_to_on_started_is_the_command_itself():
    started_pids: list[int] = []
    run = await run_shell_process(
        _python("import os; print(os.getpid())"),
        cwd=None,
        env=_env(),
        timeout_seconds=10.0,
        on_started=started_pids.append,
    )
    assert started_pids == [run.pid]
    assert run.stdout_bytes.decode().strip() == str(run.pid)
