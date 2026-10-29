"""Remembers the origin (scheme, host, port) this backend is being reached on.

The dynamic-port launcher means the backend does not know its own address until a request arrives. OAuth needs that address for its redirect URI, and agent-initiated connection setup has no HTTP request of its own, so a middleware records the origin of every HTTP request here.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_backend_origin: Optional[str] = None


def remember_backend_origin(base_url: str) -> None:
    """Record the origin of an incoming request, ignoring anything that is not a loopback http(s) origin.

    OAuth redirect URIs are built from this value, so a request that claims some other host never changes it.
    """
    global _backend_origin
    candidate = str(base_url or "").strip().rstrip("/")
    if not candidate.startswith(("http://", "https://")):
        return
    try:
        host = urlsplit(candidate).hostname
    except ValueError:
        return
    if host in _LOOPBACK_HOSTS:
        _backend_origin = candidate


def get_backend_origin() -> Optional[str]:
    """The most recently seen origin, or None before the first HTTP request."""
    return _backend_origin


def reset_backend_origin() -> None:
    """Forget the origin (tests only)."""
    global _backend_origin
    _backend_origin = None


class BackendOriginMiddleware(BaseHTTPMiddleware):
    """Records the origin of every request. Register it inside the request guard so only authorized requests reach it."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        remember_backend_origin(str(request.base_url))
        return await call_next(request)
