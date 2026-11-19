"""Cleanup for a local server: stop its background program and delete what Basil kept for it."""

from __future__ import annotations

import logging
from typing import List, Optional

from api.core.models.preferences import MCPStdioSpec

from .companion_supervisor import get_companion_supervisor
from .local_server_prepare import get_local_server_preparer
from .local_server_registration import discard_local_server_record
from .local_server_secrets import delete_secret_values

logger = logging.getLogger(__name__)


def declared_secret_names(spec: Optional[MCPStdioSpec]) -> List[str]:
    """Every secret name a server or its background program declares, without repeats."""
    if spec is None:
        return []
    names = list(spec.secret_env)
    if spec.companion is not None:
        names.extend(name for name in spec.companion.secret_env if name not in names)
    return names


async def purge_local_server_resources(connection_id: str, spec: Optional[MCPStdioSpec]) -> None:
    """Stop the background program and delete its log, its pid entry and every saved secret value. Never raises."""
    if spec is None:
        return
    get_local_server_preparer().forget(connection_id)
    try:
        await get_companion_supervisor().forget(connection_id)
    except Exception:
        logger.exception("Stopping the background program of local server %s failed", connection_id)
    names = declared_secret_names(spec)
    if names:
        try:
            await delete_secret_values(connection_id, names)
        except Exception:
            logger.exception("Deleting the saved secrets of local server %s failed", connection_id)


async def discard_local_server(connection_id: str, spec: Optional[MCPStdioSpec]) -> None:
    """Remove a local server that was just registered and did not start: its resources first, then its record."""
    await purge_local_server_resources(connection_id, spec)
    discard_local_server_record(connection_id)
