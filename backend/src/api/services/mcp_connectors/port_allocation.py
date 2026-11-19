"""Free-port allocation and readiness polling for a local server's background program."""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Callable

LOOPBACK_HOST = "127.0.0.1"


def allocate_loopback_port() -> int:
    """A free TCP port on 127.0.0.1, chosen by the operating system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK_HOST, 0))
        return int(probe.getsockname()[1])


async def port_accepts_connections(port: int, *, timeout_seconds: float = 0.5) -> bool:
    """True when something is accepting connections on 127.0.0.1:``port`` right now."""
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(LOOPBACK_HOST, port), timeout=timeout_seconds)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def wait_until_port_accepts(
    port: int,
    *,
    timeout_seconds: float,
    is_alive: Callable[[], bool],
    poll_seconds: float = 0.25,
) -> bool:
    """Wait until the port accepts connections. Returns False as soon as ``is_alive`` says the program exited, or when the time runs out."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_alive():
            return False
        if await port_accepts_connections(port):
            return True
        await asyncio.sleep(poll_seconds)
    return False
