"""Bounded, streaming subprocess runner for file-search commands such as mdfind and find."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

_STDERR_TAIL_BYTES = 4_096
_TERMINATE_GRACE_SECONDS = 1.0
_DRAIN_AFTER_KILL_SECONDS = 0.5
_STREAM_LIMIT_BYTES = 1 << 20


@dataclass(frozen=True)
class SearchProcessOutcome:
    lines: List[str]
    timed_out: bool
    returncode: Optional[int]
    stderr_tail: str
    truncated: bool

    @property
    def complete(self) -> bool:
        return not self.timed_out and not self.truncated and self.returncode == 0


async def _terminate_process_group(process: Any) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        return
    except asyncio.TimeoutError:
        pass
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS)


async def run_bounded_search_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    max_lines: Optional[int] = None,
) -> SearchProcessOutcome:
    """Run a search command and keep every line it printed, even when it times out or fails.

    The child runs in its own session, so a timeout or cancellation kills the whole process group instead of orphaning it; stdin is closed so the command can never block waiting for input.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        limit=_STREAM_LIMIT_BYTES,
    )
    lines: List[str] = []
    stderr_buffer = bytearray()
    truncated = False

    async def _read_stdout() -> None:
        nonlocal truncated
        if process.stdout is None:
            return
        while True:
            try:
                raw = await process.stdout.readline()
            except ValueError:
                return
            if not raw:
                return
            text = raw.decode("utf-8", errors="replace").rstrip("\n")
            if text:
                lines.append(text)
            if max_lines is not None and len(lines) >= max_lines:
                truncated = True
                return

    async def _read_stderr() -> None:
        if process.stderr is None:
            return
        while chunk := await process.stderr.read(1_024):
            stderr_buffer.extend(chunk)
            if len(stderr_buffer) > _STDERR_TAIL_BYTES:
                del stderr_buffer[: len(stderr_buffer) - _STDERR_TAIL_BYTES]

    stdout_task = asyncio.ensure_future(_read_stdout())
    stderr_task = asyncio.ensure_future(_read_stderr())
    timed_out = False
    try:
        try:
            await asyncio.wait_for(asyncio.shield(stdout_task), timeout=float(timeout_seconds))
        except asyncio.TimeoutError:
            timed_out = True
        if timed_out or truncated:
            await _terminate_process_group(process)
            await asyncio.wait({stdout_task}, timeout=_DRAIN_AFTER_KILL_SECONDS)
        else:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS)
            if process.returncode is None:
                await _terminate_process_group(process)
        await asyncio.wait({stderr_task}, timeout=_DRAIN_AFTER_KILL_SECONDS)
    except asyncio.CancelledError:
        await _terminate_process_group(process)
        raise
    finally:
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
    return SearchProcessOutcome(
        lines=list(lines),
        timed_out=timed_out,
        returncode=process.returncode,
        stderr_tail=bytes(stderr_buffer).decode("utf-8", errors="replace"),
        truncated=truncated,
    )


__all__ = ["SearchProcessOutcome", "run_bounded_search_process"]
