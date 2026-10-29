"""Spawn helpers that prefer ``posix_spawn`` over fork/exec.

``asyncio.create_subprocess_exec`` runs ``subprocess.Popen`` synchronously on the event-loop thread.
With the default ``close_fds=True`` Popen takes the fork path, which in a large multi-threaded macOS process can stall the whole process.
Python switches to ``posix_spawn`` only when ``close_fds=False`` and no feature that needs fork is requested, so these helpers set ``close_fds=False`` for eligible calls.
Python creates its own descriptors non-inheritable (PEP 446), so descriptors owned by other threads do not leak into the child.
Calls that need ``cwd``, a new session, ``preexec_fn`` and similar keep the default path and are logged once at DEBUG.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Sequence

from api.core.logging.api_logger import api_logger

logger = api_logger.getChild("safe_spawn")

SLOW_SPAWN_WARNING_SECONDS = 2.0

# Popen options that force the fork path when set
_FORK_ONLY_KEYS = ("cwd", "start_new_session", "preexec_fn", "pass_fds", "user", "group", "extra_groups", "process_group")

_ineligible_logged: set[str] = set()


def resolve_executable(program: str) -> str:
    """Return an absolute path for ``program`` when it can be found; posix_spawn needs a path with a directory part."""
    if os.path.dirname(program):
        return program
    return shutil.which(program) or program


def posix_spawn_eligible(kwargs: Dict[str, Any]) -> bool:
    """True when none of the options that require fork/exec are present."""
    if kwargs.get("shell"):
        return False
    for key in _FORK_ONLY_KEYS:
        value = kwargs.get(key)
        if value is None or value is False:
            continue
        if isinstance(value, (tuple, list)) and not value:
            continue
        if key == "process_group" and value == -1:
            continue
        return False
    umask = kwargs.get("umask")
    if isinstance(umask, int) and umask >= 0:
        return False
    return True


def _prepare(program: str, kwargs: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    prepared = dict(kwargs)
    resolved = resolve_executable(program)
    if posix_spawn_eligible(prepared) and os.path.dirname(resolved):
        prepared.setdefault("close_fds", False)
    else:
        key = os.path.basename(program)
        if key not in _ineligible_logged:
            _ineligible_logged.add(key)
            logger.debug("Spawn of %s keeps the default fork path (ineligible for posix_spawn)", key)
    return resolved, prepared


def _log_if_slow(program: str, started: float) -> None:
    elapsed = time.monotonic() - started
    if elapsed > SLOW_SPAWN_WARNING_SECONDS:
        logger.warning("Spawning %s took %.1fs; the spawn runs on the calling thread", os.path.basename(program), elapsed)


async def create_subprocess_exec(program: str, *args: str, **kwargs: Any) -> asyncio.subprocess.Process:
    """Drop-in for ``asyncio.create_subprocess_exec`` that uses posix_spawn when eligible and reports slow spawns."""
    resolved, prepared = _prepare(program, kwargs)
    started = time.monotonic()
    try:
        return await asyncio.create_subprocess_exec(resolved, *args, **prepared)
    finally:
        _log_if_slow(resolved, started)


def run(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Drop-in for ``subprocess.run`` with a list of arguments, using posix_spawn when eligible.

    The spawn is not timed separately because ``subprocess.run`` also waits for the process to finish.
    """
    command = list(args)
    resolved, prepared = _prepare(str(command[0]), kwargs)
    command[0] = resolved
    return subprocess.run(command, **prepared)
