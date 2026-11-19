"""The placeholders a local server's command line may contain.

``{port}`` is replaced, wherever it appears in an argument or an environment value, with the free port Basil allocated for the background program on this run. ``{run_secret}`` is replaced with a fresh random token Basil generates each time the background program starts, so the program and its server can share a credential nobody typed and nothing stored. ``{install_dir}`` is the folder Basil puts downloaded and built files in, and ``{data_dir}`` is a folder the program may keep its own sessions and databases in; both belong to one connection and are removed with it.
"""

from __future__ import annotations

from typing import Iterable, Optional

PORT_PLACEHOLDER = "{port}"
RUN_SECRET_PLACEHOLDER = "{run_secret}"
DATA_DIR_PLACEHOLDER = "{data_dir}"
INSTALL_DIR_PLACEHOLDER = "{install_dir}"
PATH_PLACEHOLDERS = (DATA_DIR_PLACEHOLDER, INSTALL_DIR_PLACEHOLDER)
PROBE_PORT = 1
"""Stands in for the real port while a spec is only being checked, so a spec that uses ``{port}`` can still be validated before anything runs."""
PROBE_RUN_SECRET = "validation-only-run-secret"
"""Stands in for the real token while a spec is only being checked."""
PROBE_DIRECTORY = "/validation-only"
"""Stands in for a connection folder while a spec is only being checked."""


class PlaceholderError(ValueError):
    """A placeholder cannot be filled in."""


def contains_port_placeholder(values: Iterable[str]) -> bool:
    return any(PORT_PLACEHOLDER in value for value in values)


def contains_run_secret_placeholder(values: Iterable[str]) -> bool:
    return any(RUN_SECRET_PLACEHOLDER in value for value in values)


def contains_path_placeholder(values: Iterable[str]) -> bool:
    return any(placeholder in value for value in values for placeholder in PATH_PLACEHOLDERS)


def substitute_placeholders(
    value: str,
    *,
    port: Optional[int] = None,
    run_secret: Optional[str] = None,
    data_dir: Optional[str] = None,
    install_dir: Optional[str] = None,
) -> str:
    """``value`` with every placeholder replaced. Raises PlaceholderError naming the one that has nothing to fill it."""
    if PORT_PLACEHOLDER in value:
        if port is None:
            raise PlaceholderError("This server needs the port of its background program, but that program is not running.")
        value = value.replace(PORT_PLACEHOLDER, str(port))
    if RUN_SECRET_PLACEHOLDER in value:
        if run_secret is None:
            raise PlaceholderError("This server needs the token of its background program, but that program is not running.")
        value = value.replace(RUN_SECRET_PLACEHOLDER, run_secret)
    if DATA_DIR_PLACEHOLDER in value:
        if data_dir is None:
            raise PlaceholderError("This server uses its data folder, which is not available here.")
        value = value.replace(DATA_DIR_PLACEHOLDER, data_dir)
    if INSTALL_DIR_PLACEHOLDER in value:
        if install_dir is None:
            raise PlaceholderError("This server uses its install folder, which is not available here.")
        value = value.replace(INSTALL_DIR_PLACEHOLDER, install_dir)
    return value


def substitute_port(value: str, port: Optional[int]) -> str:
    """``value`` with every ``{port}`` replaced. Raises PlaceholderError when it needs a port and none is available."""
    if PORT_PLACEHOLDER not in value:
        return value
    if port is None:
        raise PlaceholderError("This server needs the port of its background program, but that program is not running.")
    return value.replace(PORT_PLACEHOLDER, str(port))
