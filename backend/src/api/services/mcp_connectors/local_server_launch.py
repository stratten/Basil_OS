"""Builds the launch parameters for a local stdio server that has a background program or secrets.

A plain local server is launched straight from its stored command and never comes through here. When the server declares a background program, that program is made sure to be running first (it is started the first time when it is not set to start with Basil), and its recorded port is filled in wherever ``{port}`` appears. Secret values are read from the Keychain at this moment and only placed in the launch environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from mcp import StdioServerParameters

from api.core.models.preferences import MCPStdioSpec

from .companion_supervisor import CompanionError, CompanionSnapshot, get_companion_supervisor
from .error_normalizer import ERROR_KIND_SERVER_ERROR, make_envelope
from .local_server_placeholders import contains_path_placeholder, contains_run_secret_placeholder
from .local_server_prepare import NOT_PREPARED_MESSAGE, artifacts_ready
from .local_server_secrets import resolve_secret_env
from .stdio_transport import build_parameters

SETTINGS_ACTION = "Open Settings → Connections to check this server."
HEALTH_WAIT_SECONDS = 20.0
"""How long a first use waits for a program that is still connecting before reporting that it is not ready."""


@dataclass
class PreparedLaunch:
    """Either the parameters to launch with, or an error envelope to return to the caller instead."""

    parameters: Optional[StdioServerParameters] = None
    error: Optional[Dict[str, Any]] = None


def _failure(message: str, user_action_required: str) -> PreparedLaunch:
    return PreparedLaunch(
        error=make_envelope(
            kind=ERROR_KIND_SERVER_ERROR,
            message=message,
            retryable=False,
            user_action_required=user_action_required,
            raw={},
        )
    )


def needs_prepared_launch(spec: MCPStdioSpec) -> bool:
    """True when launching this server involves more than its plain command: a background program, secrets, an install recipe, or a placeholder that needs filling."""
    strings = [spec.command, spec.cwd or "", *spec.args, *spec.env.values()]
    return (
        spec.companion is not None
        or bool(spec.secret_env)
        or spec.install is not None
        or contains_path_placeholder(strings)
        or contains_run_secret_placeholder(strings)
    )


def _health_failure(snapshot: CompanionSnapshot) -> Optional[PreparedLaunch]:
    """An error to return instead of launching when the program's own status page says it is not usable yet, or None when it is."""
    health = snapshot.health
    if health is None or health.phase == "ready":
        return None
    detail = f" {health.message}" if health.message else ""
    if health.phase == "needs_action":
        return _failure(f"This local server is waiting for you.{detail}", "Open Settings → Connections and finish the step shown on this server, then try again.")
    if health.phase == "failed":
        return _failure(f"This local server's background program reports a problem.{detail}", SETTINGS_ACTION)
    return _failure(f"This local server's background program is still starting.{detail}", "Try again in a moment.")


async def prepare_stdio_launch(spec: MCPStdioSpec, connection_id: str) -> PreparedLaunch:
    """Make the background program ready, read the secrets, and build the launch parameters. Raises StdioSpecError when the command itself cannot run."""
    port: Optional[int] = None
    if spec.install is not None and not artifacts_ready(spec.install, get_companion_supervisor().folders(connection_id)):
        return _failure(NOT_PREPARED_MESSAGE, "Open Settings → Connections, find this server, and choose Prepare.")
    if spec.companion is not None:
        supervisor = get_companion_supervisor()
        try:
            snapshot = await supervisor.ensure_running(connection_id)
        except CompanionError as exc:
            return _failure(f"This local server's background program cannot start: {exc}", SETTINGS_ACTION)
        if not snapshot.running:
            if snapshot.status == "needs_secrets":
                return _failure(
                    snapshot.last_error or "The background program needs secret values that have not been entered.",
                    "Enter the values in Settings → Connections, then try again.",
                )
            return _failure(snapshot.last_error or "The background program is not running.", SETTINGS_ACTION)
        port = snapshot.port
        if spec.companion.probe is not None:
            snapshot = await supervisor.wait_until_ready(connection_id, HEALTH_WAIT_SECONDS)
            blocked = _health_failure(snapshot)
            if blocked is not None:
                return blocked

    secrets = await resolve_secret_env(connection_id, spec.secret_env)
    if secrets.missing:
        return _failure(
            f"This local server needs values for {', '.join(secrets.missing)}, and they have not been entered.",
            "Enter the values in Settings → Connections, then try again.",
        )
    if secrets.blocked_message:
        return _failure(secrets.blocked_message, "Open Basil and try again.")
    supervisor = get_companion_supervisor()
    uses_folders = contains_path_placeholder([spec.command, spec.cwd or "", *spec.args, *spec.env.values()])
    folders = supervisor.folders(connection_id) if uses_folders else None
    return PreparedLaunch(
        parameters=build_parameters(
            spec,
            port=port,
            extra_env=secrets.values,
            run_secret=supervisor.run_secret_for(connection_id),
            data_dir=str(folders.data) if folders else None,
            install_dir=str(folders.install) if folders else None,
        )
    )
