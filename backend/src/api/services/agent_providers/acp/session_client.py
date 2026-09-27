"""Public ACP session client façade over the subprocess session transport."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from .protocol import (
    ACP_PROTOCOL_VERSION,
    AcpAuthMethod,
    AcpClientClosedError,
    AcpClientError,
    AcpClientProtocolError,
    AcpClientTimeoutError,
    AcpInitializeResult,
    AcpRemoteRequestError,
    AcpRequestError,
    AcpSessionHandle,
    NotificationHandler,
    RequestHandler,
    build_acp_initialize_params,
    parse_acp_initialize_result,
)
from .session_transport import AcpSessionTransport


class AcpSessionClient:
    """Own one persistent bidirectional ACP connection over stdio."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        start_new_session: bool = False,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        if not argv or not all(isinstance(argument, str) and argument for argument in argv):
            raise ValueError("argv must contain at least one non-empty string")
        if not 0 < request_timeout_seconds < float("inf"):
            raise ValueError("request_timeout_seconds must be greater than zero")
        self._transport = AcpSessionTransport(
            argv,
            cwd=cwd,
            env=env,
            start_new_session=start_new_session,
            request_timeout_seconds=request_timeout_seconds,
        )
        self._has_initialized = False
        self._is_initialized = False

    async def __aenter__(self) -> "AcpSessionClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    @property
    def stderr_text(self) -> str:
        """Return bounded peer stderr for diagnostic use only."""

        return self._transport.stderr_text

    @property
    def pid(self) -> int | None:
        """Return the child process id, or its last known id after close."""

        return self._transport.pid

    @property
    def exit_code(self) -> int | None:
        """Return the child exit code, or None while it remains running."""

        return self._transport.exit_code

    @property
    def has_exited(self) -> bool:
        """Return True once the child process has exited."""

        return self._transport.has_exited

    @property
    def _process(self) -> asyncio.subprocess.Process | None:
        """Retain the established diagnostic test seam without exposing transport internals."""

        return self._transport.process

    async def wait_for_exit(self) -> int:
        """Wait for process exit and drain ordered notification handling."""

        return await self._transport.wait_for_exit()

    async def wait_for_exit_within(self, timeout: float) -> bool:
        """Return whether the process exits within the supplied timeout."""

        return await self._transport.wait_for_exit_within(timeout)

    def register_request_handler(self, method: str, handler: RequestHandler) -> None:
        """Register the async handler that answers an incoming agent request."""

        self._transport.register_request_handler(method, handler)

    def register_notification_handler(self, method: str, handler: NotificationHandler) -> None:
        """Register the async handler invoked, in arrival order, for a notification."""

        self._transport.register_notification_handler(method, handler)

    async def start(self) -> None:
        """Start the connection subprocess and transport readers once."""

        await self._transport.start()

    async def initialize(
        self,
        *,
        client_capabilities: Mapping[str, Any],
        client_info: Mapping[str, str],
    ) -> AcpInitializeResult:
        """Negotiate ACP v2 first and retain a supported v1 fallback connection."""
        if self._transport.reader_error is not None:
            raise self._transport.reader_error
        if self._transport.process is None:
            raise AcpClientClosedError("ACP session client is not started or has been closed")
        if self._has_initialized:
            raise AcpClientError("ACP session client is already initialized")
        self._has_initialized = True
        response = await self._transport.send_request(
            "initialize",
            build_acp_initialize_params(
                client_capabilities=client_capabilities,
                client_info=client_info,
            ),
        )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise AcpClientProtocolError("initialize response result must be an object")
        initialize_result = parse_acp_initialize_result(result)
        self._is_initialized = True
        return initialize_result

    async def authenticate(
        self,
        *,
        method_id: str,
        advertised_methods: Sequence[AcpAuthMethod],
    ) -> None:
        """Select an already-advertised non-secret ACP authentication method."""

        self._require_initialized()
        if not isinstance(method_id, str) or not method_id.strip():
            raise AcpClientProtocolError(
                "configured ACP authentication method must be a nonblank string"
            )
        if method_id not in {
            advertised_method.method_id for advertised_method in advertised_methods
        }:
            raise AcpClientProtocolError(
                "configured ACP authentication method was not advertised by the agent"
            )
        response = await self._transport.send_request(
            "authenticate",
            {"methodId": method_id},
        )
        if not isinstance(response.get("result"), Mapping):
            raise AcpClientProtocolError(
                "authenticate response result must be an object"
            )

    async def create_session(
        self,
        *,
        cwd: str,
        mcp_servers: Sequence[Mapping[str, Any]] = (),
    ) -> AcpSessionHandle:
        """Create a new ACP session and return its agent-issued session id."""

        self._require_initialized()
        response = await self._transport.send_request(
            "session/new",
            {"cwd": cwd, "mcpServers": [dict(server) for server in mcp_servers]},
        )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise AcpClientProtocolError("session/new response result must be an object")
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise AcpClientProtocolError("session/new response sessionId must be a nonblank string")
        return AcpSessionHandle(session_id=session_id)

    async def send_prompt(
        self,
        *,
        session_id: str,
        prompt: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Send a prompt turn and return the agent's acceptance result."""

        self._require_initialized()
        response = await self._transport.send_request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [dict(block) for block in prompt]},
        )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise AcpClientProtocolError("session/prompt response result must be an object")
        return dict(result)

    async def cancel_session(self, *, session_id: str) -> None:
        """Send the session/cancel notification. No response is expected."""

        self._require_initialized()
        await self._transport.send_notification("session/cancel", {"sessionId": session_id})

    async def close(self) -> None:
        """Terminate the subprocess and await all background work."""

        await self._transport.close()

    def _require_initialized(self) -> None:
        if not self._is_initialized:
            raise AcpClientError("ACP session client must be initialized before session operations")


__all__ = [
    "ACP_PROTOCOL_VERSION",
    "AcpAuthMethod",
    "AcpClientClosedError",
    "AcpClientError",
    "AcpClientProtocolError",
    "AcpClientTimeoutError",
    "AcpInitializeResult",
    "AcpRemoteRequestError",
    "AcpRequestError",
    "AcpSessionClient",
    "AcpSessionHandle",
]
