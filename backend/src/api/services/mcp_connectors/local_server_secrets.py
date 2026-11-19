"""Secret values for a local server's environment, kept in the macOS Keychain.

A value is typed by the person into Settings and saved by the app under the account ``<connection id>.env.<NAME>``, in the same Keychain vault as connector tokens. The backend never stores one. It asks the app for the values only while it is building a launch environment, and it never logs them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .swift_token_bridge import _ask_swift_for_credentials, _push_token_delete_to_swift

logger = logging.getLogger(__name__)

SECRET_ACCOUNT_INFIX = ".env."
SECRET_REQUEST_TIMEOUT_SECONDS = 30.0


def secret_account(connection_id: str, name: str) -> str:
    """The Keychain account key for one secret of one local server."""
    return f"{connection_id}{SECRET_ACCOUNT_INFIX}{name}"


@dataclass
class SecretResolution:
    """What the Keychain returned for a list of secret names. ``values`` holds secrets and must never be logged."""

    values: Dict[str, str] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    blocked_message: Optional[str] = None

    @property
    def complete(self) -> bool:
        return not self.missing and self.blocked_message is None


def _unique(names: Iterable[str]) -> List[str]:
    seen: List[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


async def resolve_secret_env(
    connection_id: str,
    names: Iterable[str],
    *,
    wait_for_host: bool = False,
) -> SecretResolution:
    """Fetch the saved value of each named secret.

    ``wait_for_host`` makes the call wait until the native app is connected, for the launch-time start of a background program that needs secrets. Without it, no connected app is reported as ``blocked_message``.
    """
    wanted = _unique(names)
    resolution = SecretResolution()
    if not wanted:
        return resolution
    if wait_for_host:
        from api.services.host_connection_channel import wait_for_host_connection

        await wait_for_host_connection()
    for name in wanted:
        reply = await _ask_swift_for_credentials(
            connection_id=secret_account(connection_id, name),
            timeout_s=SECRET_REQUEST_TIMEOUT_SECONDS,
            agent_task_id=None,
            include_refresh_token=False,
        )
        kind = reply.get("kind")
        value = reply.get("access_token")
        if kind == "token_available" and isinstance(value, str) and value:
            resolution.values[name] = value
        elif kind in ("token_available", "token_missing"):
            resolution.missing.append(name)
        else:
            resolution.blocked_message = str(reply.get("message") or "Basil could not read the saved secrets from the Keychain.")
            break
    if resolution.missing:
        logger.info("Local server %s is missing secret values for: %s", connection_id, ", ".join(resolution.missing))
    return resolution


async def delete_secret_values(connection_id: str, names: Iterable[str]) -> None:
    """Ask the app to delete the saved value of each named secret. Safe to repeat."""
    for name in _unique(names):
        await _push_token_delete_to_swift(secret_account(connection_id, name))
