"""Checks everything said about a local server before it is stored: the command, the optional background program, and the names of the secrets it needs.

Secret values never pass through here. A secret is declared by name, the person types its value into Settings, and it is kept in the macOS Keychain. A name that both the server and its background program declare is one saved value, so a shared token is entered once.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Mapping, Optional

from api.core.models.preferences import MCPCompanionSpec, MCPStdioSpec

from .local_server_placeholders import PORT_PLACEHOLDER, RUN_SECRET_PLACEHOLDER, contains_port_placeholder, contains_run_secret_placeholder
from .local_server_recipe import build_install_recipe, build_probe_spec
from .stdio_transport import StdioSpecError, validate_spec_fields

MAX_SECRET_NAMES = 16
MAX_ENV_NAME_LENGTH = 64
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMPANION_KEYS = frozenset({"command", "args", "cwd", "env", "secret_env", "start_with_basil", "fixed_port", "probe"})


def clean_secret_names(names: Any, *, taken: Iterable[str], label: str) -> List[str]:
    """The secret variable names as a clean list. Raises StdioSpecError for anything that is not a list of valid, distinct names."""
    if names is None:
        return []
    if isinstance(names, (str, bytes)) or not isinstance(names, (list, tuple)):
        raise StdioSpecError(f"The {label} names must be a list of variable names, one per item.")
    cleaned: List[str] = []
    for raw in names:
        if not isinstance(raw, str):
            raise StdioSpecError(f"Each {label} name must be text.")
        name = raw.strip()
        if not name or len(name) > MAX_ENV_NAME_LENGTH or not _ENV_NAME.match(name):
            raise StdioSpecError(
                f"'{raw}' is not a valid variable name for a {label}. Use letters, digits and underscores, starting with a letter or underscore."
            )
        if name in cleaned:
            raise StdioSpecError(f"The {label} name {name} is listed twice.")
        cleaned.append(name)
    if len(cleaned) > MAX_SECRET_NAMES:
        raise StdioSpecError(f"A server can declare at most {MAX_SECRET_NAMES} secrets.")
    clash = sorted(set(cleaned) & set(taken))
    if clash:
        raise StdioSpecError(f"{', '.join(clash)} is listed both as a plain environment variable and as a secret. Keep it only as a secret.")
    return cleaned


def build_companion_spec(raw: Any) -> Optional[MCPCompanionSpec]:
    """The validated background program, or None when ``raw`` is None. Raises StdioSpecError with a message the agent can act on."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise StdioSpecError("companion must be an object with command, args, cwd, env, secret_env, start_with_basil, fixed_port, and probe.")
    unknown = sorted(set(raw) - _COMPANION_KEYS)
    if unknown:
        raise StdioSpecError(
            f"companion does not take {', '.join(unknown)}. Use only command, args, cwd, env, secret_env, start_with_basil, fixed_port, and probe."
        )
    command = raw.get("command")
    if not isinstance(command, str):
        raise StdioSpecError("companion needs a command: the program to keep running, with each argument as its own item in args.")
    args = raw.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise StdioSpecError("companion args must be a list of text items, one per argument.")
    cwd = raw.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise StdioSpecError("companion cwd must be the absolute path of a folder.")
    env = raw.get("env", {})
    if not isinstance(env, Mapping) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise StdioSpecError("companion env must map variable names to text values. Put secrets in secret_env instead.")
    start_with_basil = raw.get("start_with_basil", True)
    if not isinstance(start_with_basil, bool):
        raise StdioSpecError("companion start_with_basil must be true or false.")
    fixed_port = raw.get("fixed_port")
    if fixed_port is not None and (isinstance(fixed_port, bool) or not isinstance(fixed_port, int) or not 1 <= fixed_port <= 65535):
        raise StdioSpecError("companion fixed_port must be a whole number from 1 to 65535.")

    checked = validate_spec_fields(command, list(args), cwd, dict(env))
    secret_env = clean_secret_names(raw.get("secret_env"), taken=checked.env.keys(), label="companion secret")
    if fixed_port is not None and contains_port_placeholder([*checked.args, *checked.env.values()]):
        raise StdioSpecError(f"Use either fixed_port or {PORT_PLACEHOLDER} for the background program, not both.")
    companion_strings = [*checked.args, *checked.env.values()]
    probe = build_probe_spec(
        raw.get("probe"),
        secret_names=secret_env,
        companion_has_port=fixed_port is not None or contains_port_placeholder(companion_strings),
        companion_uses_run_secret=contains_run_secret_placeholder(companion_strings),
    )
    return MCPCompanionSpec(
        command=checked.command,
        args=list(checked.args),
        cwd=checked.cwd,
        env=dict(checked.env),
        secret_env=secret_env,
        start_with_basil=start_with_basil,
        fixed_port=fixed_port,
        probe=probe,
    )


def build_local_server_spec(
    *,
    command: str,
    args: List[str],
    cwd: Optional[str],
    env: Mapping[str, str],
    secret_env: Any = None,
    companion: Any = None,
    install: Any = None,
) -> MCPStdioSpec:
    """The validated spec for a new local server. Nothing is launched. Raises StdioSpecError for anything that cannot work."""
    spec = validate_spec_fields(command, list(args), cwd, dict(env))
    spec.secret_env = clean_secret_names(secret_env, taken=spec.env.keys(), label="secret")
    spec.companion = build_companion_spec(companion)
    spec.install = build_install_recipe(install)

    server_strings = [*spec.args, *spec.env.values()]
    companion_strings = [] if spec.companion is None else [*spec.companion.args, *spec.companion.env.values()]
    if spec.companion is None and contains_run_secret_placeholder(server_strings):
        raise StdioSpecError(
            f"The server's command uses {RUN_SECRET_PLACEHOLDER}, but no background program is set up, so there is nothing for the token to be shared with. "
            f"Add a companion that is also given {RUN_SECRET_PLACEHOLDER}, or remove it."
        )
    if contains_port_placeholder(server_strings) and not contains_port_placeholder(companion_strings):
        raise StdioSpecError(
            f"The server's command uses {PORT_PLACEHOLDER}, but no background program is set up that is also given {PORT_PLACEHOLDER}, so nothing would be listening there. "
            f"Add a companion that listens on {PORT_PLACEHOLDER}, or remove {PORT_PLACEHOLDER}."
        )
    return spec
