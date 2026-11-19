"""Download one file for a local server: https only (including every redirect), a size cap, and a SHA-256 of what arrived.

The caller compares the returned hash with the one the person approved. Nothing here trusts the server: a redirect to a plain-http address, an address with embedded credentials, or a body larger than the cap ends the download.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlsplit

import httpx

MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024
MAX_REDIRECTS = 5
CHUNK_BYTES = 64 * 1024
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_TIMEOUT = httpx.Timeout(connect=20.0, read=60.0, write=20.0, pool=20.0)


class DownloadError(Exception):
    """The file could not be fetched. The message is plain language for the person."""


def _checked_address(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise DownloadError(f"Basil only downloads over https, with no credentials in the address, so it stopped at {parts.scheme or 'an unknown'}://{parts.hostname or ''}.")
    return url


async def download_file(
    url: str,
    destination: Path,
    *,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> str:
    """Save the file at ``url`` to ``destination`` (created owner-only) and return its SHA-256. The partial file is removed on any failure."""
    address = _checked_address(url)
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=_TIMEOUT, transport=transport) as client:
            for _ in range(MAX_REDIRECTS + 1):
                async with client.stream("GET", address, headers={"Accept-Encoding": "identity"}) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise DownloadError("The server redirected the download without saying where.")
                        address = _checked_address(urljoin(address, location))
                        continue
                    if response.status_code != 200:
                        raise DownloadError(f"The download failed: the server answered {response.status_code}.")
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise DownloadError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB Basil allows.")
                    return await _save(response, destination, max_bytes)
            raise DownloadError(f"The download was redirected more than {MAX_REDIRECTS} times.")
    except httpx.HTTPError as exc:
        _discard(destination)
        raise DownloadError(f"The download failed: {exc or type(exc).__name__}") from exc
    except BaseException:
        _discard(destination)
        raise


async def _save(response: httpx.Response, destination: Path, max_bytes: int) -> str:
    digest = hashlib.sha256()
    total = 0
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        async for chunk in response.aiter_bytes(CHUNK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                raise DownloadError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB Basil allows.")
            digest.update(chunk)
            handle.write(chunk)
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) != total:
        raise DownloadError("The download ended early.")
    return digest.hexdigest()


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
