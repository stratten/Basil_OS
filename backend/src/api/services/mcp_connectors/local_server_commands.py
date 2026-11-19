"""Run one command for a local server's preparation: no shell, a trimmed environment, a time limit, and a bounded record of what it printed.

Basil's own environment holds API keys and tokens that a downloaded build tool has no business reading, so a command gets only the variables a build or install tool needs to find its programs, its home folder and the network.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

MAX_OUTPUT_CHARS = 4000
DEFAULT_TIMEOUT_SECONDS = 1800.0
CHECK_TIMEOUT_SECONDS = 60.0

# A packaged Mac app starts with a short PATH that leaves out the places Homebrew and the Go installer put programs.
EXTRA_PATH_ENTRIES = ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/go/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
_PASSED_THROUGH = (
    "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
)

@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def search_path(environ: Optional[Mapping[str, str]] = None) -> str:
    """The PATH commands are looked up in: the current one first, then the usual install places that are missing from it."""
    source = os.environ if environ is None else environ
    entries = [entry for entry in source.get("PATH", "").split(os.pathsep) if entry]
    entries.extend(entry for entry in EXTRA_PATH_ENTRIES if entry not in entries)
    return os.pathsep.join(entries)


def scrubbed_env(environ: Optional[Mapping[str, str]] = None, extra: Optional[Mapping[str, str]] = None) -> dict:
    source = os.environ if environ is None else environ
    env = {name: source[name] for name in _PASSED_THROUGH if name in source}
    env["PATH"] = search_path(source)
    env.update(extra or {})
    return env


def resolve_program(name: str, path: str) -> Optional[str]:
    if os.sep in name:
        return name if os.access(name, os.X_OK) and Path(name).is_file() else None
    return shutil.which(name, path=path)


def _tail(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else "…" + text[-MAX_OUTPUT_CHARS:]


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def _collect(process: "asyncio.subprocess.Process") -> bytes:
    kept = b""
    assert process.stdout is not None
    while True:
        chunk = await process.stdout.read(65536)
        if not chunk:
            break
        kept = (kept + chunk)[-MAX_OUTPUT_CHARS * 4 :]
    await process.wait()
    return kept


async def run_command(
    argv: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    extra_env: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run ``argv`` without a shell. Exit code 127 means the program was not found, 124 that it ran out of time."""
    env = scrubbed_env(extra=extra_env)
    program = resolve_program(argv[0], env["PATH"])
    if program is None:
        return CommandResult(127, f"{argv[0]} was not found on this Mac.")
    try:
        process = await asyncio.create_subprocess_exec(
            program,
            *argv[1:],
            cwd=None if cwd is None else str(cwd),
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        return CommandResult(126, f"{argv[0]} could not be started: {exc}")
    try:
        raw = await asyncio.wait_for(_collect(process), timeout)
    except asyncio.TimeoutError:
        _kill_group(process.pid)
        await process.wait()
        return CommandResult(124, f"{argv[0]} did not finish within {int(timeout)} seconds and was stopped.")
    except BaseException:
        _kill_group(process.pid)
        await process.wait()
        raise
    return CommandResult(process.returncode or 0, _tail(raw.decode("utf-8", errors="replace").strip()))
