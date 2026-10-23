"""ASGI guard that restricts the Basil backend to authenticated loopback callers."""

from __future__ import annotations

import ipaddress
import json
from typing import Any, Awaitable, Callable, MutableMapping, Optional

from fastapi import HTTPException, Request

from .backend_credentials import (
    WEBSOCKET_ACCEPT_PROTOCOL,
    WEBSOCKET_TOKEN_PROTOCOL_PREFIX,
    BackendCredentialStore,
    get_backend_credential_store,
)

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

CREDENTIAL_SCOPE_KEY = "basil.credential_type"
TOKEN_EXEMPT_PATHS = frozenset({"/health", "/settings/connections/oauth/callback/mcp"})
TOKEN_EXEMPT_PATH_PREFIXES = ("/validation/",)
LOOPBACK_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_TOKEN_HEADER_NAME = "x-basil-token"
_TEST_CLIENT_HOST = "testclient"
_WEBSOCKET_POLICY_VIOLATION = 1008


def _is_loopback_address(host: Optional[str]) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _parse_host_header(value: str) -> Optional[tuple[str, Optional[int]]]:
    candidate = value.strip().lower()
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing == -1:
            return None
        host = candidate[1:closing]
        remainder = candidate[closing + 1:]
        if remainder and not remainder.startswith(":"):
            return None
        port_text = remainder[1:]
    else:
        if candidate.count(":") > 1:
            return None
        host, _, port_text = candidate.partition(":")
    if not port_text:
        return host, None
    if not port_text.isdigit():
        return None
    return host, int(port_text)


def _is_allowed_host_header(value: Optional[str], server: Optional[tuple[str, Optional[int]]]) -> bool:
    if not value:
        return False
    parsed = _parse_host_header(value)
    if parsed is None:
        return False
    host, port = parsed
    if host not in LOOPBACK_HOST_NAMES:
        return False
    server_port = server[1] if server else None
    if server_port is None:
        return True
    if port is None:
        return server_port == 80
    return port == server_port


def _header_map(scope: Scope) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers") or []:
        name = raw_name.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        headers[name] = f"{headers[name]}, {value}" if name in headers else value
    return headers


def _offered_protocols(headers: dict[str, str]) -> list[str]:
    raw = headers.get("sec-websocket-protocol", "")
    return [protocol.strip() for protocol in raw.split(",") if protocol.strip()]


def _token_from_protocols(protocols: list[str]) -> Optional[str]:
    for protocol in protocols:
        if protocol.startswith(WEBSOCKET_TOKEN_PROTOCOL_PREFIX):
            return protocol[len(WEBSOCKET_TOKEN_PROTOCOL_PREFIX):]
    return None


def _is_token_exempt(path: str) -> bool:
    return path in TOKEN_EXEMPT_PATHS or path.startswith(TOKEN_EXEMPT_PATH_PREFIXES)


def _with_accept_protocol(send: Send) -> Send:
    async def send_with_protocol(message: Message) -> None:
        if message.get("type") == "websocket.accept" and not message.get("subprotocol"):
            message = {**message, "subprotocol": WEBSOCKET_ACCEPT_PROTOCOL}
        await send(message)

    return send_with_protocol


class BackendRequestGuardMiddleware:
    """Rejects non-loopback peers, foreign Host headers, and requests without a Basil credential."""

    def __init__(self, app: ASGIApp, credential_store: Optional[BackendCredentialStore] = None) -> None:
        self.app = app
        self._credential_store = credential_store

    @property
    def credential_store(self) -> BackendCredentialStore:
        return self._credential_store or get_backend_credential_store()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = _header_map(scope)
        network_rejection = self._network_rejection(scope, headers)
        if network_rejection is not None:
            await self._reject(scope, receive, send, 403, network_rejection)
            return
        if scope_type == "http" and scope.get("method") == "OPTIONS" and "access-control-request-method" in headers:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        offered_protocols = _offered_protocols(headers) if scope_type == "websocket" else []
        protocol_token = _token_from_protocols(offered_protocols)
        token = headers.get(_TOKEN_HEADER_NAME) or protocol_token
        try:
            credential_type = self.credential_store.classify(token)
        except OSError:
            if not _is_token_exempt(path):
                await self._reject(scope, receive, send, 503, "backend_credentials_unavailable")
                return
            credential_type = None
        if credential_type is None and not _is_token_exempt(path):
            await self._reject(scope, receive, send, 401, "backend_token_required")
            return
        scope[CREDENTIAL_SCOPE_KEY] = credential_type
        if (
            scope_type == "websocket"
            and credential_type is not None
            and not headers.get(_TOKEN_HEADER_NAME)
            and protocol_token is not None
            and WEBSOCKET_ACCEPT_PROTOCOL in offered_protocols
        ):
            send = _with_accept_protocol(send)
        await self.app(scope, receive, send)

    @staticmethod
    def _network_rejection(scope: Scope, headers: dict[str, str]) -> Optional[str]:
        client = scope.get("client")
        client_host = client[0] if client else None
        if client_host == _TEST_CLIENT_HOST:
            return None
        if not _is_loopback_address(client_host):
            return "loopback_required"
        if not _is_allowed_host_header(headers.get("host"), scope.get("server")):
            return "host_not_allowed"
        return None

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status_code: int, reason: str) -> None:
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": _WEBSOCKET_POLICY_VIOLATION, "reason": reason})
            return
        body = json.dumps({"detail": reason}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def request_credential_type(request: Request) -> Optional[str]:
    return request.scope.get(CREDENTIAL_SCOPE_KEY)


async def current_credential_type(request: Request) -> Optional[str]:
    return request_credential_type(request)


async def require_host_credential(request: Request) -> None:
    if request_credential_type(request) != "host":
        raise HTTPException(status_code=403, detail="host_credential_required")


def is_loopback_bind_host(host: str) -> bool:
    return _is_loopback_address(host.strip().strip("[]"))


def resolve_loopback_bind_host(host: str, *, allow_lan_bind: bool) -> str:
    if is_loopback_bind_host(host):
        return host
    if allow_lan_bind:
        raise SystemExit(
            f"Refusing to bind the Basil backend to {host!r}: LAN access is unavailable until mobile pairing ships. "
            "Unset BASIL_ALLOW_LAN_BIND and bind to 127.0.0.1."
        )
    raise SystemExit(f"Refusing to bind the Basil backend to non-loopback host {host!r}. Bind to 127.0.0.1.")
