"""Server-advertised icons for MCP connections.

An MCP server may describe itself with ``serverInfo.icons`` in its initialize
result: a list of ``{src, mimeType, sizes, theme}`` entries whose ``src`` is an
``https`` URL or a ``data:`` URI. Basil shows that icon on the connection's chip
and falls back to its own bundled icon when the server advertises none.

The icon is untrusted input from a remote server, so it is fetched once here,
checked, and stored as a small ``data:`` URL. The UI never loads a remote URL on
the server's say-so. The checks are:

* only ``https`` URLs, never to a loopback, private, link-local or otherwise
  non-public address, and redirects are not followed;
* a hard size cap on what is read, and a short timeout;
* the bytes must really be a PNG, JPEG, GIF, WebP or a script-free SVG, judged
  by their content and not by the ``Content-Type`` the server claims.

Nothing here raises. A server with no usable icon, an unreachable icon host or a
rejected image all end the same way: no icon, so the bundled one is used.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import logging
import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote_to_bytes, urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_ICON_BYTES = 48 * 1024
"""Largest icon kept. The data URL is stored on the connection record and sent with the connection list, so it stays small."""

FETCH_TIMEOUT_SECONDS = 5.0
MAX_CANDIDATES_TRIED = 3
PREFERRED_ICON_SIZE = 32
FAILURE_RETRY_SECONDS = 600.0
CACHE_LIMIT = 64

_SVG_FORBIDDEN = re.compile(r"<script|<foreignobject|javascript:|\son[a-z]+\s*=", re.IGNORECASE)

# src -> (expires_at, data_url or None). A success is kept for the life of the process; a failure is remembered for ten minutes so a status check that runs often does not retry a dead icon host each time.
_cache: Dict[str, Tuple[float, Optional[str]]] = {}


def serialize_icons(icons: Any) -> List[Dict[str, Any]]:
    """Turn the SDK's ``Icon`` objects (or plain dicts) into JSON-safe dicts, dropping anything malformed."""
    if not isinstance(icons, (list, tuple)):
        return []
    result: List[Dict[str, Any]] = []
    for icon in icons:
        get = icon.get if isinstance(icon, dict) else (lambda key, default=None, _icon=icon: getattr(_icon, key, default))
        src = get("src")
        if not isinstance(src, str) or not src.strip():
            continue
        sizes = get("sizes")
        theme = get("theme")
        result.append(
            {
                "src": src.strip(),
                "mimeType": get("mimeType") if isinstance(get("mimeType"), str) else None,
                "sizes": [size for size in sizes if isinstance(size, str)] if isinstance(sizes, (list, tuple)) else [],
                "theme": theme if theme in ("light", "dark") else None,
            }
        )
    return result


def _size_distance(sizes: List[str]) -> int:
    """How far the closest advertised size is from the size the chip draws; ``any`` (a vector icon) counts as exact."""
    best = 10_000
    for size in sizes:
        if size.strip().lower() == "any":
            return 0
        match = re.fullmatch(r"(\d+)x(\d+)", size.strip().lower())
        if match:
            best = min(best, abs(int(match.group(1)) - PREFERRED_ICON_SIZE))
    return best


def rank_icon_candidates(icons: List[Dict[str, Any]]) -> List[str]:
    """The ``src`` values worth trying, best first: icons made for a light background (the chip's tile is light), then the nearest size to the one drawn. Non-https, non-data sources are dropped."""
    usable = [icon for icon in icons if icon["src"].lower().startswith(("https://", "data:image/"))]
    usable.sort(key=lambda icon: (1 if icon.get("theme") == "dark" else 0, _size_distance(icon.get("sizes") or [])))
    ordered: List[str] = []
    for icon in usable:
        if icon["src"] not in ordered:
            ordered.append(icon["src"])
    return ordered


def sniff_image_mime(data: bytes) -> Optional[str]:
    """The real image type from the bytes, or ``None`` when they are not an allowed image or an SVG carries script."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:512].lstrip().lower()
    if head.startswith((b"<svg", b"<?xml", b"<!doctype svg")) and b"<svg" in data[:2048].lower():
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return None if _SVG_FORBIDDEN.search(text) else "image/svg+xml"
    return None


def _to_data_url(data: bytes) -> Optional[str]:
    if not data or len(data) > MAX_ICON_BYTES:
        return None
    mime = sniff_image_mime(data)
    if mime is None:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def decode_data_uri(src: str) -> Optional[str]:
    """Check an icon that arrived as a ``data:`` URI and return it as a normalized data URL, or ``None``."""
    header, separator, payload = src.partition(",")
    if not separator or not header.lower().startswith("data:image/"):
        return None
    try:
        data = base64.b64decode(payload, validate=True) if header.lower().endswith(";base64") else unquote_to_bytes(payload)
    except (binascii.Error, ValueError):
        return None
    return _to_data_url(data)


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


async def _host_is_public(host: str) -> bool:
    """True only when every address the host resolves to is a public one."""
    try:
        ipaddress.ip_address(host)
        return _is_public_address(host)
    except ValueError:
        pass
    if host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost")):
        return False
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(_is_public_address(address) for address in addresses)


async def _fetch_https_icon(src: str, client: httpx.AsyncClient) -> Optional[str]:
    parsed = urlparse(src)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    if not await _host_is_public(parsed.hostname):
        logger.info("Skipped a server icon that points at a non-public host")
        return None
    async with client.stream("GET", src, headers={"Accept": "image/*"}) as response:
        if response.status_code != 200:
            return None
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_ICON_BYTES:
            return None
        received = bytearray()
        async for chunk in response.aiter_bytes():
            received.extend(chunk)
            if len(received) > MAX_ICON_BYTES:
                return None
    return _to_data_url(bytes(received))


async def resolve_icon_source(src: str, *, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """One advertised ``src`` as a checked data URL, or ``None``. Never raises."""
    now = time.monotonic()
    cached = _cache.get(src)
    if cached and cached[0] > now:
        return cached[1]
    result: Optional[str] = None
    try:
        if src.lower().startswith("data:"):
            result = decode_data_uri(src)
        else:
            owned = client is None
            http_client = client or httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False)
            try:
                result = await asyncio.wait_for(_fetch_https_icon(src, http_client), timeout=FETCH_TIMEOUT_SECONDS + 1)
            finally:
                if owned:
                    await http_client.aclose()
    except Exception as exc:  # an unreachable host or a malformed response must never fail the connection check
        logger.info("Could not load a server icon: %s", type(exc).__name__)
        result = None
    if len(_cache) >= CACHE_LIMIT:
        _cache.clear()
    _cache[src] = (now + (float("inf") if result else FAILURE_RETRY_SECONDS), result)
    return result


async def resolve_server_icon(icons: Any, *, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """The best usable icon among a server's advertised ``icons`` as a data URL, or ``None`` when it advertises none or none of them passes the checks."""
    for src in rank_icon_candidates(serialize_icons(icons))[:MAX_CANDIDATES_TRIED]:
        data_url = await resolve_icon_source(src, client=client)
        if data_url:
            return data_url
    return None


async def attach_server_icon(envelope: Any, *, client: Optional[httpx.AsyncClient] = None) -> None:
    """Add ``icon_data_url`` and ``icons_advertised`` to a successful ``list_tools`` envelope's ``server`` block. Does nothing for an error envelope or a block without ``icons``, which is how an in-process server (no advertised icons) leaves any stored icon alone."""
    if not isinstance(envelope, dict) or envelope.get("ok") is False:
        return
    result = envelope.get("result")
    server = result.get("server") if isinstance(result, dict) else None
    if not isinstance(server, dict) or "icons" not in server:
        return
    advertised = serialize_icons(server.get("icons"))
    server["icons"] = advertised
    server["icons_advertised"] = bool(advertised)
    server["icon_data_url"] = await resolve_server_icon(advertised, client=client) if advertised else None
