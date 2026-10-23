"""Process runner for ShellService.

Runs one command with stdout and stderr captured as pipes and stdin attached to a private pseudo-terminal that becomes the child's controlling terminal. Basil can therefore see prompts a program writes to its terminal (sudo, ssh, git credential prompts, confirmations), relay them to the user, and write the answer back. It still kills the whole process group on timeout or cancellation and keeps whatever output was produced before a timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import re
import shutil
import signal
import struct
import sys
import termios
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

WALL_CLOCK_BOUND_MULTIPLIER = 2.0
MAX_INPUT_RELAYS = 5
PROMPT_IDLE_SECONDS = 1.0
_POLL_SECONDS = 0.1
_TERMINATE_GRACE_SECONDS = 0.5
_DRAIN_SECONDS = 1.0
_TERMINAL_CAPTURE_LIMIT_BYTES = 64 * 1024
_PROMPT_TAIL_CHARS = 512
_READ_CHUNK_BYTES = 65_536

_monotonic = time.monotonic
_wall_clock = time.time

NON_INTERACTIVE_ENV_DEFAULTS: Dict[str, str] = {
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "MANPAGER": "cat",
    "TERM": "dumb",
}

PTY_HELPER_SOURCE = (
    "import fcntl, os, sys, termios\n"
    "try:\n"
    "    fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n"
    "except OSError:\n"
    "    pass\n"
    "os.execv(sys.argv[1], sys.argv[2:])\n"
)

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_PROMPT_LINE_PATTERN = re.compile(
    r"(?:[:?]$|\[[yn]/[yn]\]$|\((?:yes/no|y/n)[^)]*\)\??$|press (?:any key|enter|return))",
    re.IGNORECASE,
)
_SECRET_PROMPT_PATTERN = re.compile(
    r"pass(?:word|phrase|code)|\bpin\b|token|secret|\botp\b|one[- ]time|verification code|api[ _-]?key",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CommandInputReply:
    """The user's reply to a relayed prompt: answered, canceled, timeout, or unavailable."""

    status: str
    text: Optional[str] = None


InputRequester = Callable[[str, bool], Awaitable[CommandInputReply]]


@dataclass
class ShellRunOutcome:
    stdout_bytes: bytes
    stderr_bytes: bytes
    terminal_output: str
    exit_code: Optional[int]
    pid: Optional[int]
    duration_ms: int
    timed_out: bool = False
    timeout_clock: Optional[str] = None
    input_wait_ms: int = 0
    input_exchanges: List[Dict[str, Any]] = field(default_factory=list)
    input_status: Optional[str] = None
    pending_prompt: Optional[str] = None


def is_secret_prompt(prompt: str) -> bool:
    return bool(_SECRET_PROMPT_PATTERN.search(prompt or ""))


def resolve_executable(command: str, *, cwd: Optional[str], env: Mapping[str, str]) -> str:
    """Resolve the executable the way ``execvp`` would, raising FileNotFoundError when it is missing."""
    if not command:
        raise FileNotFoundError(command)
    if os.sep in command:
        base = cwd or os.getcwd()
        candidate = command if os.path.isabs(command) else os.path.join(base, command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        raise FileNotFoundError(command)
    resolved = shutil.which(command, path=env.get("PATH"))
    if resolved is None:
        raise FileNotFoundError(command)
    return resolved


class PromptDetector:
    """Track recent output and report a prompt once the process goes quiet on one."""

    def __init__(self) -> None:
        self._tail = ""
        self._last_output_at = _monotonic()
        self._output_events = 0
        self._consumed_events = 0

    def feed(self, text: str) -> None:
        if not text:
            return
        cleaned = _ANSI_ESCAPE_PATTERN.sub("", text)
        self._tail = (self._tail + cleaned)[-_PROMPT_TAIL_CHARS:]
        self._last_output_at = _monotonic()
        self._output_events += 1

    def pending_prompt(self, now: float) -> Optional[str]:
        if self._output_events == self._consumed_events:
            return None
        if now - self._last_output_at < PROMPT_IDLE_SECONDS:
            return None
        if not self._tail or self._tail.endswith(("\n", "\r")):
            return None
        last_line = re.split(r"[\r\n]", self._tail)[-1].strip()
        if not last_line or not _PROMPT_LINE_PATTERN.search(last_line):
            return None
        return last_line

    def consume(self) -> None:
        self._consumed_events = self._output_events


def _configure_terminal(slave_fd: int) -> None:
    attrs = termios.tcgetattr(slave_fd)
    attrs[3] &= ~(termios.ECHO | termios.ECHONL)
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
    with contextlib.suppress(OSError):
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 120, 0, 0))


async def _terminate_process_group(process: Any, wait_task: "asyncio.Future[Any]") -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    done, _pending = await asyncio.wait({wait_task}, timeout=_TERMINATE_GRACE_SECONDS)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    if wait_task not in done:
        await asyncio.wait({wait_task}, timeout=_TERMINATE_GRACE_SECONDS)


_INPUT_REPLY_STOP_STATUS = {
    "canceled": "input_canceled",
    "timeout": "input_timeout",
}


async def run_shell_process(
    argv: Sequence[str],
    *,
    cwd: Optional[str],
    env: Mapping[str, str],
    timeout_seconds: float,
    input_requester: Optional[InputRequester] = None,
    on_started: Optional[Callable[[int], None]] = None,
) -> ShellRunOutcome:
    """Run ``argv`` to completion, timeout, input stop, or cancellation.

    Raises FileNotFoundError when the executable cannot be resolved, and re-raises CancelledError after killing the process group.
    """
    command = str(argv[0])
    args = [str(arg) for arg in argv[1:]]
    resolved = resolve_executable(command, cwd=cwd, env=env)

    master_fd, slave_fd = os.openpty()
    try:
        _configure_terminal(slave_fd)
        os.set_blocking(master_fd, False)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            "-c",
            PTY_HELPER_SOURCE,
            resolved,
            command,
            *args,
            cwd=cwd,
            env=dict(env),
            stdin=slave_fd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except BaseException:
        os.close(master_fd)
        raise
    finally:
        os.close(slave_fd)

    if on_started is not None:
        on_started(process.pid)

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    terminal_buffer = bytearray()
    detector = PromptDetector()
    terminal_open = True

    def _drain_terminal() -> None:
        nonlocal terminal_open
        while terminal_open:
            try:
                chunk = os.read(master_fd, _READ_CHUNK_BYTES)
            except BlockingIOError:
                return
            except OSError:
                terminal_open = False
                return
            if not chunk:
                terminal_open = False
                return
            room = _TERMINAL_CAPTURE_LIMIT_BYTES - len(terminal_buffer)
            if room > 0:
                terminal_buffer.extend(chunk[:room])
            detector.feed(chunk.decode("utf-8", errors="replace"))

    async def _pump(stream: Any, buffer: bytearray) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                return
            buffer.extend(chunk)
            detector.feed(chunk.decode("utf-8", errors="replace"))

    pump_tasks = [
        asyncio.ensure_future(_pump(process.stdout, stdout_buffer)),
        asyncio.ensure_future(_pump(process.stderr, stderr_buffer)),
    ]
    wait_task = asyncio.ensure_future(process.wait())
    started_monotonic = _monotonic()
    started_wall = _wall_clock()
    input_wait_monotonic = 0.0
    input_wait_wall = 0.0
    timed_out = False
    timeout_clock: Optional[str] = None
    input_status: Optional[str] = None
    pending_prompt: Optional[str] = None
    exchanges: List[Dict[str, Any]] = []

    try:
        while True:
            done, _pending = await asyncio.wait({wait_task}, timeout=_POLL_SECONDS)
            _drain_terminal()
            if wait_task in done:
                break
            active_monotonic = (_monotonic() - started_monotonic) - input_wait_monotonic
            active_wall = (_wall_clock() - started_wall) - input_wait_wall
            if active_monotonic >= timeout_seconds:
                timed_out, timeout_clock = True, "monotonic"
                break
            if active_wall >= timeout_seconds * WALL_CLOCK_BOUND_MULTIPLIER:
                timed_out, timeout_clock = True, "wall_clock"
                break
            prompt = detector.pending_prompt(_monotonic())
            if prompt is None:
                continue
            detector.consume()
            secret = is_secret_prompt(prompt)
            if input_requester is None:
                input_status, pending_prompt = "input_required", prompt
                break
            if len(exchanges) >= MAX_INPUT_RELAYS:
                input_status, pending_prompt = "input_limit", prompt
                break
            wait_started_monotonic = _monotonic()
            wait_started_wall = _wall_clock()
            try:
                reply = await input_requester(prompt, secret)
            finally:
                input_wait_monotonic += max(0.0, _monotonic() - wait_started_monotonic)
                input_wait_wall += max(0.0, _wall_clock() - wait_started_wall)
            exchanges.append({"prompt": prompt, "secret": secret, "status": reply.status})
            if reply.status == "answered" and reply.text is not None:
                if wait_task.done():
                    break
                with contextlib.suppress(OSError):
                    os.write(master_fd, reply.text.encode("utf-8") + b"\n")
                continue
            input_status = _INPUT_REPLY_STOP_STATUS.get(reply.status, "input_required")
            pending_prompt = prompt
            break

        if not wait_task.done():
            await _terminate_process_group(process, wait_task)
        await asyncio.wait(pump_tasks, timeout=_DRAIN_SECONDS)
        _drain_terminal()
    except asyncio.CancelledError:
        logger.info("Shell command canceled; terminating process group %s", process.pid)
        await _terminate_process_group(process, wait_task)
        raise
    finally:
        for task in (*pump_tasks, wait_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(*pump_tasks, wait_task, return_exceptions=True)
        os.close(master_fd)

    return ShellRunOutcome(
        stdout_bytes=bytes(stdout_buffer),
        stderr_bytes=bytes(stderr_buffer),
        terminal_output=bytes(terminal_buffer).decode("utf-8", errors="replace"),
        exit_code=process.returncode,
        pid=process.pid,
        duration_ms=int((_monotonic() - started_monotonic) * 1000),
        timed_out=timed_out,
        timeout_clock=timeout_clock,
        input_wait_ms=int(input_wait_monotonic * 1000),
        input_exchanges=exchanges,
        input_status=input_status,
        pending_prompt=pending_prompt,
    )


__all__ = [
    "MAX_INPUT_RELAYS",
    "NON_INTERACTIVE_ENV_DEFAULTS",
    "PTY_HELPER_SOURCE",
    "WALL_CLOCK_BOUND_MULTIPLIER",
    "CommandInputReply",
    "InputRequester",
    "PromptDetector",
    "ShellRunOutcome",
    "is_secret_prompt",
    "resolve_executable",
    "run_shell_process",
]
