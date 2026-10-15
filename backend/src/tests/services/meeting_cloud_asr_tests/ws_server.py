"""A local WebSocket server standing in for a vendor streaming endpoint."""

import contextlib
from http import HTTPStatus
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from websockets.asyncio.server import serve


@contextlib.asynccontextmanager
async def vendor_server(
    handler: Callable[[Any], Awaitable[None]], *, reject_status: Optional[HTTPStatus] = None
) -> AsyncIterator[str]:
    """Yield the ``ws://`` base URL of a server running ``handler`` for each connection."""

    def process_request(connection: Any, request: Any) -> Any:
        if reject_status is not None:
            return connection.respond(reject_status, "rejected\n")
        return None

    async with serve(handler, "127.0.0.1", 0, process_request=process_request) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}/listen"
