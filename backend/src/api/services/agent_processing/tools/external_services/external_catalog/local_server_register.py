"""The `register_local_server` action: lets the core agent set up a local MCP server the user asked for.

The agent supplies the program to run (and, when the server needs one, a background program that must be running first). The definition is validated by the same code the Settings route uses, a server that is already set up is reported before the user is asked anything, and the user always approves through the execution approval card, which cannot be skipped by "always approve", read-only auto-approval, or a remembered pattern. The card is written by Basil and shows the exact command.

The agent never supplies a secret value. Credentials are declared by name in ``secret_env`` and the user types the values into Settings, where they go straight to the Keychain. Registration does not launch anything: a server that needs secrets is reported as ``awaiting_secrets``, and a server that needs none is started, its tools are read, and everything is removed again if that fails.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Any, Dict, List, Mapping, Optional, Tuple

from fastapi import HTTPException

from api.core.models.preferences import MCPConnectionRecord, MCPStdioSpec
from api.services.mcp_connectors.companion_supervisor import CompanionError, get_companion_supervisor
from api.services.mcp_connectors.local_server_lifecycle import declared_secret_names, discard_local_server
from api.services.mcp_connectors.local_server_registration import (
    MAX_DESCRIPTION_LENGTH,
    MAX_FRIENDLY_NAME_LENGTH,
    MAX_SOURCE_URL_LENGTH,
    DuplicateLocalServerError,
    find_existing_local_server,
    register_local_server_record,
)
from api.services.mcp_connectors.local_server_spec import build_local_server_spec
from api.services.mcp_connectors.stdio_transport import StdioSpecError

from api.services.mcp_connectors.local_server_prepare import artifacts_ready, get_local_server_preparer

from .envelopes import make_external_catalog_invalid_arguments, make_external_catalog_permission_denied
from .local_server_recipe_actions import RECIPE_SCHEMA, ask_user_approval, recipe_card_lines, recipe_card_sentences, start_preparation

logger = logging.getLogger(__name__)

REGISTER_APPROVAL_SOURCE = "external_catalog_register_local_server"
# The execution-approvals table only accepts a fixed list of execution types, so this card reuses the connection-setup type and is told apart by its source.
REGISTER_EXECUTION_TYPE = "mcp_connection_setup"

ALLOWED_ARGUMENT_KEYS = frozenset({"command", "args", "cwd", "env", "secret_env", "source_url", "companion", "install", "replace"})
MAX_LISTED_TOOLS = 25
MAX_SHOWN_SETTING_VALUE = 80

_CREDENTIAL_NAMES = frozenset({"KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD"})
_CREDENTIAL_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD", "_CREDENTIAL", "_CREDENTIALS", "APIKEY")

_USAGE = (
    "register_local_server needs friendly_name and arguments. arguments is an object with command (the program), args (a list, one item per argument), "
    "and optionally cwd (an absolute folder), env (non-secret settings), secret_env (a list of credential variable names, never values), "
    "source_url (where the instructions came from), companion (a background program the server needs running first), install (a recipe for programs to install and files to download or build first) and replace (the connection_id of a local server to rewrite). "
    "Ask the user for the exact command if you do not know it; never guess one. " + RECIPE_SCHEMA
)


def _looks_like_credential(name: str) -> bool:
    upper = name.upper()
    return upper in _CREDENTIAL_NAMES or upper.endswith(_CREDENTIAL_SUFFIXES)


def _credential_like_names(env: Any) -> List[str]:
    if not isinstance(env, Mapping):
        return []
    return [name for name in env if isinstance(name, str) and _looks_like_credential(name)]


def _argument_problem(arguments: Dict[str, Any], name: str, description: str) -> Optional[str]:
    """The reason these arguments cannot be used at all, or None. Checked before the user is asked anything."""
    unknown = sorted(set(arguments) - ALLOWED_ARGUMENT_KEYS)
    if unknown:
        if {"friendly_name", "description"} & set(unknown):
            return "friendly_name and description go beside arguments, not inside it. " + _USAGE
        return f"arguments does not take {', '.join(unknown)}. " + _USAGE
    if not name:
        return "register_local_server needs friendly_name: a short name for the server, such as 'WhatsApp'."
    if len(name) > MAX_FRIENDLY_NAME_LENGTH:
        return f"friendly_name is longer than {MAX_FRIENDLY_NAME_LENGTH} characters."
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return f"description is longer than {MAX_DESCRIPTION_LENGTH} characters."
    if arguments.get("replace") is not None and not isinstance(arguments.get("replace"), str):
        return "arguments.replace must be the connection_id of the local server to rewrite, as text."
    flagged = _credential_like_names(arguments.get("env"))
    companion = arguments.get("companion")
    if isinstance(companion, Mapping):
        flagged += _credential_like_names(companion.get("env"))
    if flagged:
        return (
            f"{', '.join(sorted(set(flagged)))} look like credentials, and env values are visible in this conversation. "
            "List each one by name in secret_env instead: the user types the value into Basil's Settings and you never see it. "
            "Remove them from env, then call register_local_server again."
        )
    return None


def _text_list(value: Any, label: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StdioSpecError(f"{label} must be a list of text items, one per argument.")
    return list(value)


def _read_server_fields(arguments: Dict[str, Any]) -> Tuple[str, List[str], Optional[str], Dict[str, str], Optional[str]]:
    """The server's command, args, cwd, env and source address with their types checked. Raises StdioSpecError."""
    command = arguments.get("command")
    if not isinstance(command, str):
        raise StdioSpecError("arguments.command is required: the program to run, with each argument as its own item in args.")
    args = _text_list(arguments.get("args"), "arguments.args")
    cwd = arguments.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise StdioSpecError("arguments.cwd must be the absolute path of a folder.")
    env = arguments.get("env")
    if env is None:
        env = {}
    if not isinstance(env, Mapping) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise StdioSpecError("arguments.env must map variable names to text values. Put secrets in secret_env instead.")
    source_url = arguments.get("source_url")
    if source_url is not None:
        if not isinstance(source_url, str):
            raise StdioSpecError("arguments.source_url must be text.")
        if len(source_url.strip()) > MAX_SOURCE_URL_LENGTH:
            raise StdioSpecError(f"arguments.source_url is longer than {MAX_SOURCE_URL_LENGTH} characters.")
    return command, args, cwd, dict(env), source_url


def _command_line(command: str, args: List[str]) -> str:
    return shlex.join([command, *args])


def _shown_settings(env: Mapping[str, str]) -> str:
    parts = []
    for key, value in env.items():
        shown = value if len(value) <= MAX_SHOWN_SETTING_VALUE else f"{value[:MAX_SHOWN_SETTING_VALUE]}…"
        parts.append(f"{key}={shown}")
    return ", ".join(parts)


def describe_local_server_approval(name: str, spec: MCPStdioSpec, replacing: Optional[MCPConnectionRecord] = None) -> str:
    """The paragraph on the approval card: what will run, where, with which settings, and when."""
    parts = [
        f"Add the local server {name}. It is a program on this Mac that Basil starts, and it runs with your account's full access to your files and network, so approve it only if you trust where it came from.",
        f"It runs: {_command_line(spec.command, spec.args)}" + (f", in the folder {spec.cwd}." if spec.cwd else "."),
    ]
    if replacing is not None and replacing.stdio is not None:
        old = replacing.stdio
        parts.insert(0, f"This replaces the existing server {replacing.friendly_name}, which currently runs {_command_line(old.command, old.args)}. Its saved secret values are kept, and it will be stopped now.")
    if spec.env:
        parts.append(f"It is given these settings: {_shown_settings(spec.env)}.")
    if spec.secret_env:
        parts.append(f"You will type these secret values yourself in Settings, and Basil keeps them in the Keychain: {', '.join(spec.secret_env)}.")
    companion = spec.companion
    if companion is not None:
        when = "whenever Basil is open" if companion.start_with_basil else "the first time the server is used"
        where = f"on port {companion.fixed_port}" if companion.fixed_port else "on a port Basil picks each time"
        parts.append(f"It also keeps a background program running, started {when}, {where}: {_command_line(companion.command, companion.args)}" + (f", in the folder {companion.cwd}." if companion.cwd else "."))
        if companion.env:
            parts.append(f"The background program is given these settings: {_shown_settings(companion.env)}.")
        if companion.secret_env:
            parts.append(f"The background program also needs these secret values from you: {', '.join(companion.secret_env)}.")
    parts.extend(recipe_card_sentences(spec))
    parts.append("Nothing starts until you approve.")
    return " ".join(parts)


def _approval_command(name: str, spec: MCPStdioSpec, replacing: Optional[MCPConnectionRecord] = None) -> str:
    """The exact definition as a block of lines, shown in the card's command area."""
    lines = [f'register-local-mcp-server "{name}"' + (f" (replaces {replacing.friendly_name})" if replacing is not None else ""), f"program: {_command_line(spec.command, spec.args)}", f"folder: {spec.cwd or '(none)'}"]
    if spec.env:
        lines.append(f"settings: {_shown_settings(spec.env)}")
    if spec.secret_env:
        lines.append(f"secrets you type: {', '.join(spec.secret_env)}")
    if spec.companion is not None:
        lines.append(f"background program: {_command_line(spec.companion.command, spec.companion.args)}")
        lines.append(f"background folder: {spec.companion.cwd or '(none)'}")
    lines.extend(recipe_card_lines(spec))
    return "\n".join(lines)


async def request_local_server_approval(name: str, spec: MCPStdioSpec, replacing: Optional[MCPConnectionRecord] = None) -> bool:
    """Ask the user to approve adding this local server; any failure to ask counts as a denial."""
    return await ask_user_approval(
        _approval_command(name, spec, replacing),
        {
            "source": REGISTER_APPROVAL_SOURCE,
            "execution_type": REGISTER_EXECUTION_TYPE,
            "purpose": describe_local_server_approval(name, spec, replacing),
            "description": "Adding a local server needs your explicit approval every time",
            "friendly_name": name,
        },
    )


def _already_registered(record: MCPConnectionRecord) -> Dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "status": "already_connected",
            "connection_id": record.id,
            "service": record.friendly_name,
            "message": "This local server is already set up. Use action='describe_server' with this connection_id.",
        },
    }


def _awaiting_secrets(record: MCPConnectionRecord, names: List[str]) -> Dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "status": "awaiting_secrets",
            "connection_id": record.id,
            "service": record.friendly_name,
            "secret_names": names,
            "message": (
                f"{record.friendly_name} is saved but has not started, because it needs {', '.join(names)}. "
                f"Tell the user to open Settings → Connections, find {record.friendly_name}, and type the values there: Basil keeps them in the Keychain and starts the server once they are saved. "
                "You never see the values. When the user says they are done, confirm with action='describe_server' using this connection_id."
            ),
        },
    }


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("kind") or "The server did not respond.")
        return str(detail)
    return str(exc) or type(exc).__name__


_LOCAL_ADDRESS = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::(?:\d+|\{port\}))?[^\s\"']*", re.IGNORECASE)

_UNMANAGED_PROGRAM_ADVICE = (
    "This server is set up to talk to a program on this Mac at {address}, but no background program is registered with it, so Basil will not start that program and the connection stops working whenever it is not running. "
    "If that address belongs to a program Basil should keep running (for example a bridge that was started by hand in Terminal), register it as the companion instead of leaving it unmanaged. "
    "Stop the hand-started copy first, because two copies cannot share one saved session or linked account. Then call register_local_server again with arguments.replace set to this connection_id, the same command, and a companion with command, args and cwd. "
    "Use the folder the program already runs from as the companion's cwd, so what it has saved there, such as a linked phone, is reused and nothing has to be linked again. "
    "Write {{port}} in the companion's env and in this server's address so Basil picks a free port, and {{run_secret}} wherever both need one shared token. "
    "Add companion.probe when the program serves a status page, so Settings can show when it is ready or waiting for the user. "
    "Do not set up a login item or a launch agent: the companion already starts with Basil and stops with it. "
    "If the address belongs to a service the user runs separately and Basil should not manage, ignore this."
)


def unmanaged_background_program_advice(spec: Optional[MCPStdioSpec]) -> Optional[str]:
    """Advice for the agent when a server points at a localhost address but has no companion to run, else None."""
    if spec is None or spec.companion is not None:
        return None
    haystack = " ".join([*spec.args, *spec.env.values()])
    found = _LOCAL_ADDRESS.search(haystack)
    if found is None:
        return None
    return _UNMANAGED_PROGRAM_ADVICE.format(address=found.group(0))


async def _refresh_connection(connection_id: str):
    """Read the server's tools through the same route the Settings screen uses, which launches it."""
    from api.routes.connections.routes import refresh_tools

    return await refresh_tools(connection_id, None)  # type: ignore[arg-type]


async def _start_and_discover(record: MCPConnectionRecord, *, replaced: bool = False) -> Dict[str, Any]:
    """Start the background program (if any), launch the server, and read its tools. A new server is removed again on failure; a replaced one is kept so the agent can correct it."""
    spec = record.stdio
    try:
        if spec is not None and spec.companion is not None:
            snapshot = await get_companion_supervisor().start(record.id)
            if not snapshot.running:
                raise CompanionError(snapshot.last_error or "The background program did not start.")
        connection = await _refresh_connection(record.id)
    except asyncio.CancelledError:
        if not replaced:
            await discard_local_server(record.id, spec)
        raise
    except Exception as exc:
        if replaced:
            logger.warning("Replaced local server %s did not start: %s", record.id, exc)
            await get_companion_supervisor().stop(record.id)
            return {
                "ok": False,
                "error": {
                    "kind": "connection_setup_failed",
                    "message": f"{record.friendly_name} was updated but did not start: {_failure_reason(exc)}",
                    "retryable": False,
                    "user_action_required": "Correct the definition with the user and call register_local_server again with arguments.replace set to this connection_id.",
                    "raw": {},
                },
            }
        logger.warning("Local server %s did not start; removing it: %s", record.id, exc)
        await discard_local_server(record.id, spec)
        return {
            "ok": False,
            "error": {
                "kind": "connection_setup_failed",
                "message": f"{record.friendly_name} was not added, because it did not start: {_failure_reason(exc)} Nothing was kept.",
                "retryable": False,
                "user_action_required": "Check that the command runs on its own, or add the server in Settings → Connections.",
                "raw": {},
            },
        }
    tool_names = [tool.name for tool in connection.tools]
    result: Dict[str, Any] = {
        "status": "connected",
        "connection_id": record.id,
        "service": record.friendly_name,
        "tool_count": len(tool_names),
        "tool_names": tool_names[:MAX_LISTED_TOOLS],
        "message": f"{record.friendly_name} is running and exposes {len(tool_names)} tools. Use action='describe_server' with this connection_id to see them.",
    }
    advice = unmanaged_background_program_advice(spec)
    if advice is not None:
        result["advice"] = advice
    return {"ok": True, "result": result}


def _preparing(record: MCPConnectionRecord, secret_names: List[str]) -> Dict[str, Any]:
    secrets = f" It also needs {', '.join(secret_names)}: tell the user to type those values in Settings → Connections; you never see them." if secret_names else ""
    return {
        "ok": True,
        "result": {
            "status": "preparing",
            "connection_id": record.id,
            "service": record.friendly_name,
            "secret_names": secret_names,
            "message": (
                f"{record.friendly_name} is saved and Basil is preparing it in the background: it will ask the user to approve each program it has to install, then download or build the files the user approved, and start the background program.{secrets} "
                "Follow it with action='local_server_status' using this connection_id. If the status says the user has to act (for example to scan a code in Settings → Connections), tell them exactly that. "
                "When the status says everything is in place, confirm with action='describe_server'."
            ),
        },
    }


def _find_replaced(arguments: Dict[str, Any]) -> Tuple[Optional[MCPConnectionRecord], Optional[str]]:
    """The local server named by arguments.replace, or a message saying why there is none."""
    target = arguments.get("replace")
    if target is None:
        return None, None
    from api.core.preferences.preferences_io import load_preferences

    for record in load_preferences().connections.mcp_connections:
        if record.id == target and record.stdio is not None:
            return record, None
    return None, "arguments.replace does not name a local server that is set up. Use action='list_servers' to find its connection_id, or leave replace out to add a new server."


async def _stop_before_replacing(connection_id: str) -> None:
    try:
        await get_local_server_preparer().cancel(connection_id)
        await get_companion_supervisor().stop(connection_id)
    except Exception:
        logger.exception("Stopping local server %s before replacing it failed", connection_id)


async def register_external_catalog_local_server(
    arguments: Optional[Dict[str, Any]],
    friendly_name: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate the definition, get the user's approval, register the server, and prepare or start it unless it needs secrets."""
    if not isinstance(arguments, dict) or not arguments:
        return make_external_catalog_invalid_arguments(_USAGE)
    name = " ".join((friendly_name or "").split())
    note = (description or "").strip()
    problem = _argument_problem(arguments, name, note)
    if problem:
        return make_external_catalog_invalid_arguments(problem)
    replacing, missing = _find_replaced(arguments)
    if missing:
        return make_external_catalog_invalid_arguments(missing)
    try:
        command, args, cwd, env, source_url = _read_server_fields(arguments)
        spec = build_local_server_spec(
            command=command,
            args=args,
            cwd=cwd,
            env=env,
            secret_env=arguments.get("secret_env"),
            companion=arguments.get("companion"),
            install=arguments.get("install"),
        )
    except StdioSpecError as exc:
        return make_external_catalog_invalid_arguments(f"That local server cannot be registered: {exc} Fix it with the user, then call register_local_server again.")

    existing = find_existing_local_server(spec)
    if existing is not None and (replacing is None or existing.id != replacing.id):
        return _already_registered(existing)

    if not await request_local_server_approval(name, spec, replacing):
        return make_external_catalog_permission_denied("register_local_server", "the user did not approve adding this local server")

    if replacing is not None:
        await _stop_before_replacing(replacing.id)
    try:
        record = register_local_server_record(
            friendly_name=name,
            command=command,
            args=args,
            cwd=cwd,
            env=env,
            description=note or None,
            source_url=source_url,
            secret_env=arguments.get("secret_env"),
            companion=arguments.get("companion"),
            install=arguments.get("install"),
            replace_id=replacing.id if replacing is not None else None,
        )
    except DuplicateLocalServerError:
        existing = find_existing_local_server(spec)
        if existing is not None:
            return _already_registered(existing)
        return make_external_catalog_invalid_arguments("That local server is already set up.")
    except StdioSpecError as exc:
        return make_external_catalog_invalid_arguments(f"That local server cannot be registered: {exc}")

    names = declared_secret_names(record.stdio)
    if record.stdio is not None and not artifacts_ready(record.stdio.install, get_companion_supervisor().folders(record.id)):
        get_local_server_preparer().forget(record.id)
        start_preparation(record)
        return _preparing(record, names)
    if names:
        return _awaiting_secrets(record, names)
    return await _start_and_discover(record, replaced=replacing is not None)
