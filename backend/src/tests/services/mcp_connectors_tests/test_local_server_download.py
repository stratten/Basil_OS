"""Downloading a file for a local server: https only, redirects checked, size capped, hash reported."""

from __future__ import annotations

import hashlib
from typing import AsyncIterator, Callable, List

import httpx
import pytest

from api.services.mcp_connectors.local_server_download import DownloadError, download_file

URL = "https://example.test/files/tool.tar.gz"
BODY = b"the approved file contents" * 100


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_a_file_is_saved_private_and_its_hash_is_returned(tmp_path):
    seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=BODY)

    saved = tmp_path / "tool.download"
    digest = await download_file(URL, saved, transport=_transport(handler))

    assert digest == hashlib.sha256(BODY).hexdigest()
    assert saved.read_bytes() == BODY
    assert oct(saved.stat().st_mode & 0o777) == "0o600"
    assert seen[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_a_redirect_to_another_https_address_is_followed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.test":
            return httpx.Response(302, headers={"Location": "https://objects.example.test/blob?sig=1"})
        return httpx.Response(200, content=BODY)

    digest = await download_file(URL, tmp_path / "f", transport=_transport(handler))

    assert digest == hashlib.sha256(BODY).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    ["http://example.test/plain", "ftp://example.test/x", "https://user:pw@example.test/x", "file:///etc/passwd"],
)
async def test_a_redirect_that_is_not_plain_https_is_refused_and_nothing_is_left_behind(tmp_path, location):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": location})

    target = tmp_path / "f"
    with pytest.raises(DownloadError, match="only downloads over https"):
        await download_file(URL, target, transport=_transport(handler))

    assert not target.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["http://example.test/x", "ftp://example.test/x", "https://user:pw@example.test/x", "example.test/x", ""])
async def test_the_first_address_must_also_be_plain_https(tmp_path, address):
    with pytest.raises(DownloadError, match="only downloads over https"):
        await download_file(address, tmp_path / "f", transport=_transport(lambda request: httpx.Response(200, content=BODY)))


@pytest.mark.asyncio
async def test_a_redirect_loop_and_a_redirect_without_a_destination_are_refused(tmp_path):
    loop = lambda request: httpx.Response(302, headers={"Location": "https://example.test/again"})
    with pytest.raises(DownloadError, match="redirected more than"):
        await download_file(URL, tmp_path / "a", transport=_transport(loop))

    nowhere = lambda request: httpx.Response(302)
    with pytest.raises(DownloadError, match="without saying where"):
        await download_file(URL, tmp_path / "b", transport=_transport(nowhere))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 403, 500, 204])
async def test_a_status_other_than_ok_is_a_failure(tmp_path, status):
    with pytest.raises(DownloadError, match=str(status)):
        await download_file(URL, tmp_path / "f", transport=_transport(lambda request: httpx.Response(status, content=b"x")))


@pytest.mark.asyncio
async def test_a_file_over_the_cap_is_refused_whether_or_not_the_server_declares_its_size(tmp_path):
    declared = lambda request: httpx.Response(200, headers={"Content-Length": str(len(BODY))}, content=BODY)
    with pytest.raises(DownloadError, match="larger than"):
        await download_file(URL, tmp_path / "a", max_bytes=len(BODY) - 1, transport=_transport(declared))

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(10_000):
                yield b"x" * 1024

    undeclared = lambda request: httpx.Response(200, stream=Endless())
    target = tmp_path / "b"
    with pytest.raises(DownloadError, match="larger than"):
        await download_file(URL, target, max_bytes=100_000, transport=_transport(undeclared))

    assert not target.exists()


@pytest.mark.asyncio
async def test_an_interrupted_download_leaves_no_partial_file_and_a_retry_succeeds(tmp_path):
    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield BODY[:50]
            raise httpx.ReadError("connection reset")

    target = tmp_path / "f"
    with pytest.raises(DownloadError, match="connection reset"):
        await download_file(URL, target, transport=_transport(lambda request: httpx.Response(200, stream=Interrupted())))
    assert not target.exists()

    digest = await download_file(URL, target, transport=_transport(lambda request: httpx.Response(200, content=BODY)))
    assert digest == hashlib.sha256(BODY).hexdigest() and target.read_bytes() == BODY


@pytest.mark.asyncio
async def test_a_connection_that_ends_before_the_declared_length_is_a_failure(tmp_path):
    class Short(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield BODY[:10]

    short = lambda request: httpx.Response(200, headers={"Content-Length": str(len(BODY))}, stream=Short())
    target = tmp_path / "f"
    with pytest.raises(DownloadError):
        await download_file(URL, target, transport=_transport(short))

    assert not target.exists()
