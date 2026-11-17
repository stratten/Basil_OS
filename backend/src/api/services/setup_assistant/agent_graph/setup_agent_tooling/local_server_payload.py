"""Deterministic payload for the setup agent's `register_local_mcp_server` receipt.

The agent supplies the command it has already set up and checked, as separate pieces: the program, its arguments, the folder, and optional non-secret environment variables. The pieces are validated here before the person ever sees the receipt, so a command that cannot run is refused to the agent in words it can act on. Nothing is joined into a shell string, because Basil never runs the command through a shell.
"""

from __future__ import annotations

from typing import Any, Dict, List

from api.services.mcp_connectors.stdio_transport import StdioSpecError, validate_spec_fields

REGISTER_LOCAL_MCP_SERVER_TOOL_NAME = "register_local_mcp_server"

_ALLOWED_KEYS = ("friendly_name", "command", "args", "cwd", "env", "description", "source_url")


def normalize_register_local_server_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the safe payload for a `register_local_mcp_server` receipt, or raise ValueError the agent can act on."""
    unknown = sorted(set(payload) - set(_ALLOWED_KEYS))
    if unknown:
        raise ValueError(
            f"register_local_mcp_server does not take {', '.join(unknown)}. Use only friendly_name, command, args, cwd, env, description, and source_url."
        )
    friendly_name = payload.get("friendly_name")
    if not isinstance(friendly_name, str) or not friendly_name.strip():
        raise ValueError("register_local_mcp_server receipts must include friendly_name, the name the person will see in Connections.")
    command = payload.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(
            "register_local_mcp_server receipts must include command, the program that starts the server (for example an absolute path, or a name such as uv or node). "
            "Put each argument in args as its own item; never put a whole shell line in command."
        )
    args = payload.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError("args must be a list of text items, one per argument.")
    cwd = payload.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("cwd must be the absolute path of the folder the server starts in.")
    env = payload.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise ValueError("env must map variable names to text values. Put only non-secret values there; Basil never stores a secret for a local server.")

    try:
        spec = validate_spec_fields(command, list(args), cwd, dict(env))
    except StdioSpecError as exc:
        raise ValueError(
            f"That local server cannot be registered: {exc} Finish setting it up with the person first, check that the command runs, and propose again."
        ) from exc

    normalized: Dict[str, Any] = {
        "friendly_name": friendly_name.strip(),
        "command": spec.command,
        "args": list(spec.args),
        "env": dict(spec.env),
    }
    if spec.cwd:
        normalized["cwd"] = spec.cwd
    for optional_key in ("description", "source_url"):
        value = payload.get(optional_key)
        if isinstance(value, str) and value.strip():
            # The address is kept exactly as the person gave it.
            normalized[optional_key] = value if optional_key == "source_url" else value.strip()
    return normalized


def describe_local_server_command(payload: Dict[str, Any]) -> str:
    """One readable line for the command in a receipt or a result message."""
    args: List[str] = list(payload.get("args") or [])
    return " ".join([str(payload.get("command", "")), *args]).strip()
