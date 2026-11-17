"""Runs a local MCP server that speaks over standard input and output.

A stdio connection is a command Basil launches itself, so this module owns three things: turning a stored ``MCPStdioSpec`` into a launchable process without ever involving a shell, running one MCP session against that process with a hard deadline, and making sure the process is gone afterwards.

Lifetime model: per call, the same as the remote transport in ``mcp_client_service.py``. The MCP client's ``stdio_client`` starts the process when the session opens and ends it when the session closes, including when the deadline fires. A server that must stay running between calls (for example one holding a paired session) needs a supervised long-lived process, which is not built yet; see the Package J notes in the project plan.

Nothing here reads a token. A stdio connection stores none, and ``swift_token_bridge`` answers token requests for it with a placeholder so the callers that expect a token keep working.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from api.core.models.preferences import MCPStdioSpec

from .error_normalizer import ERROR_KIND_SERVER_ERROR, ERROR_KIND_TIMEOUT, make_envelope, make_success, normalize_exception

logger = logging.getLogger(__name__)

STDIO_SENTINEL_PREFIX = "basil-stdio://"
"""``server_url`` of every stdio connection: the prefix followed by the connection id."""

STDIO_PLACEHOLDER_TOKEN = "basil-stdio-no-token"
"""Returned in place of a token. It is never sent anywhere; ``MCPClientService`` ignores the token for stdio connections."""

_STDERR_TAIL_CHARS = 1500
"""How much of the server's own error output is kept for an error message."""

_EXTRA_PATH_DIRECTORIES = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "~/.local/bin",
    "~/.cargo/bin",
    "~/.bun/bin",
    "~/.volta/bin",
)
"""Where tools people install by hand usually live. A Mac app starts with a minimal PATH that leaves these out, so a server launched with `uv`, `npx` or `node` would otherwise not be found."""


class StdioSpecError(ValueError):
    """The stored command cannot be launched. The message says why in plain words."""


def is_stdio_url(server_url: str) -> bool:
    return server_url.startswith(STDIO_SENTINEL_PREFIX)


def connection_id_from_url(server_url: str) -> str:
    return server_url[len(STDIO_SENTINEL_PREFIX):].split("/", 1)[0]


def stdio_server_url(connection_id: str) -> str:
    return f"{STDIO_SENTINEL_PREFIX}{connection_id}"


def search_path(base_path: Optional[str] = None) -> str:
    """PATH with the usual hand-install directories added after the existing entries."""
    entries = [entry for entry in (base_path if base_path is not None else os.environ.get("PATH", "")).split(os.pathsep) if entry]
    for directory in _EXTRA_PATH_DIRECTORIES:
        expanded = str(Path(directory).expanduser())
        if expanded not in entries:
            entries.append(expanded)
    return os.pathsep.join(entries)


def resolve_command(command: str, path: str) -> str:
    """The executable to launch: the absolute path as given, or the first match on ``path``."""
    command = command.strip()
    if not command:
        raise StdioSpecError("The command is empty.")
    if os.sep in command:
        candidate = Path(command).expanduser()
        if not candidate.is_absolute():
            raise StdioSpecError("A command with a slash must be an absolute path.")
        if not (candidate.is_file() and os.access(candidate, os.X_OK)):
            raise StdioSpecError(f"{candidate} is not an executable file.")
        return str(candidate)
    found = shutil.which(command, path=path)
    if not found:
        raise StdioSpecError(f"I could not find a program named '{command}' on this Mac.")
    return found


def build_parameters(spec: MCPStdioSpec, *, base_env: Optional[Dict[str, str]] = None) -> StdioServerParameters:
    """The launch parameters for ``spec``. Raises StdioSpecError when it cannot run."""
    environment = dict(base_env if base_env is not None else get_default_environment())
    environment["PATH"] = search_path(environment.get("PATH"))
    executable = resolve_command(spec.command, environment["PATH"])
    working_directory: Optional[str] = None
    if spec.cwd:
        directory = Path(spec.cwd).expanduser()
        if not directory.is_absolute() or not directory.is_dir():
            raise StdioSpecError(f"The folder {spec.cwd} does not exist.")
        working_directory = str(directory)
    environment.update(spec.env)
    return StdioServerParameters(command=executable, args=list(spec.args), env=environment, cwd=working_directory)


def _read_tail(error_log: Any) -> str:
    try:
        error_log.flush()
        error_log.seek(0)
        return error_log.read()[-_STDERR_TAIL_CHARS:].strip()
    except Exception:
        return ""


async def run_stdio_session(
    spec: MCPStdioSpec,
    op: Callable[[ClientSession], Awaitable[Any]],
    *,
    timeout_seconds: float,
    envelope_success: bool,
) -> Any:
    """Launch the server, run ``op`` in one MCP session, stop the server, and return the result or an error envelope.

    ``envelope_success`` follows ``MCPClientService._run_in_session``: True wraps the result in a success envelope, False returns it raw so ``call_tool`` can normalize it.
    """
    try:
        parameters = build_parameters(spec)
    except StdioSpecError as exc:
        return make_envelope(
            kind=ERROR_KIND_SERVER_ERROR,
            message=f"This local server cannot start: {exc}",
            retryable=False,
            user_action_required="Check the command in Settings → Connections, or ask Basil to set the server up again.",
            raw={"command": spec.command},
        )

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as error_log:

        async def _run() -> Any:
            async with stdio_client(parameters, errlog=error_log) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    return await op(session)

        try:
            value = await asyncio.wait_for(_run(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return make_envelope(
                kind=ERROR_KIND_TIMEOUT,
                message=_with_tail(f"The local server did not answer within {timeout_seconds:.0f} seconds.", _read_tail(error_log)),
                retryable=True,
                raw={"command": spec.command},
            )
        except Exception as exc:
            logger.warning("Local MCP server %s failed: %s", spec.command, exc)
            envelope = normalize_exception(exc)
            tail = _read_tail(error_log)
            if isinstance(exc, BaseExceptionGroup) and isinstance(envelope, dict) and isinstance(envelope.get("error"), dict):
                # A server that exits while starting surfaces as an opaque task-group error; say what happened instead.
                envelope["error"]["message"] = "The local server stopped before it finished starting."
            if tail and isinstance(envelope, dict) and isinstance(envelope.get("error"), dict):
                envelope["error"]["message"] = _with_tail(str(envelope["error"].get("message", "")), tail)
            return envelope

    return make_success(value) if envelope_success else value


def _with_tail(message: str, tail: str) -> str:
    return f"{message} The server said: {tail}" if tail else message


def load_stdio_spec(server_url: str) -> Optional[MCPStdioSpec]:
    """The stored launch spec for the connection a ``basil-stdio://`` address names, or None when no such connection exists."""
    from api.core.preferences.preferences_io import load_preferences

    connection_id = connection_id_from_url(server_url)
    for record in load_preferences().connections.mcp_connections:
        if record.id == connection_id:
            return record.stdio
    return None


def is_stdio_connection(connection_id: str) -> bool:
    """True when the stored connection with this id is a local stdio server."""
    from api.core.preferences.preferences_io import load_preferences

    return any(
        record.id == connection_id and record.stdio is not None and is_stdio_url(record.server_url)
        for record in load_preferences().connections.mcp_connections
    )


def spec_summary(spec: MCPStdioSpec) -> str:
    """One readable line for the command, for the Connections list and receipts."""
    return " ".join([spec.command, *spec.args]).strip()


def validate_spec_fields(command: str, args: List[str], cwd: Optional[str], env: Dict[str, str]) -> MCPStdioSpec:
    """Checks the pieces of a new local server before it is stored, without launching it."""
    cleaned_command = (command or "").strip()
    if not cleaned_command:
        raise StdioSpecError("A local server needs a command.")
    if any(character in cleaned_command for character in ("\n", "\r", "\0")):
        raise StdioSpecError("The command cannot contain line breaks.")
    if any((not isinstance(arg, str)) or "\0" in arg for arg in args):
        raise StdioSpecError("Each argument must be text without null characters.")
    for key, value in env.items():
        if not key or "=" in key or "\0" in key or "\0" in str(value):
            raise StdioSpecError("An environment variable name cannot be empty or contain an equals sign.")
    spec = MCPStdioSpec(command=cleaned_command, args=list(args), cwd=(cwd or "").strip() or None, env={str(k): str(v) for k, v in env.items()})
    build_parameters(spec)
    return spec
