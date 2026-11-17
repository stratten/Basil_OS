"""Server-advertised icons are fetched once, checked, and stored as a small data URL; anything doubtful ends as no icon."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Callable, List

import httpx
import pytest

from api.services.mcp_connectors import server_icon
from api.services.mcp_connectors.server_icon import (
    MAX_ICON_BYTES,
    attach_server_icon,
    decode_data_uri,
    rank_icon_candidates,
    resolve_server_icon,
    serialize_icons,
    sniff_image_mime,
)

REAL_HOST_IS_PUBLIC = server_icon._host_is_public
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><path d="M0 0h8v8z"/></svg>'


def data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


@pytest.fixture(autouse=True)
def clean_cache_and_public_hosts(monkeypatch):
    server_icon._cache.clear()

    async def public(_host: str) -> bool:
        return True

    monkeypatch.setattr(server_icon, "_host_is_public", public)
    yield
    server_icon._cache.clear()


def client_for(handler: Callable[[httpx.Request], httpx.Response], seen: List[httpx.Request] | None = None) -> httpx.AsyncClient:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(wrapped), follow_redirects=False)


# --- sniffing and data URIs ---------------------------------------------------


@pytest.mark.parametrize(
    "payload, expected",
    [
        (PNG, "image/png"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 8, "image/jpeg"),
        (b"GIF89a" + b"\x00" * 8, "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (SVG, "image/svg+xml"),
        (b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        (b"<html><body>not an image</body></html>", None),
        (b"", None),
        (b"MZ\x90\x00", None),
    ],
)
def test_sniff_judges_the_bytes_not_a_claimed_type(payload, expected):
    assert sniff_image_mime(payload) == expected


@pytest.mark.parametrize(
    "svg",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"/></svg>',
    ],
)
def test_an_svg_that_carries_script_is_rejected(svg):
    assert sniff_image_mime(svg) is None


def test_data_uri_is_accepted_normalized_and_rejected_when_wrong():
    assert decode_data_uri(data_url("image/png", PNG)) == data_url("image/png", PNG)
    # The claimed type is ignored: a PNG labeled as JPEG is stored as a PNG.
    assert decode_data_uri(data_url("image/jpeg", PNG)) == data_url("image/png", PNG)
    assert decode_data_uri("data:image/svg+xml;utf8," + SVG.decode()) == data_url("image/svg+xml", SVG)
    assert decode_data_uri(data_url("image/png", b"<html></html>")) is None
    assert decode_data_uri("data:image/png;base64,@@@not base64@@@") is None
    assert decode_data_uri("data:text/html;base64,PGI+") is None
    assert decode_data_uri("data:image/png") is None
    assert decode_data_uri(data_url("image/png", PNG + b"\x00" * MAX_ICON_BYTES)) is None


# --- candidate choice ------------------------------------------------------------


def test_serialize_icons_drops_malformed_entries_and_accepts_sdk_objects():
    sdk_icon = SimpleNamespace(src=" https://x.test/a.png ", mimeType="image/png", sizes=["32x32"], theme="light")
    assert serialize_icons([sdk_icon, {"src": ""}, {"nope": 1}, 7, {"src": "https://x.test/b.png", "theme": "purple", "sizes": [1, "any"]}]) == [
        {"src": "https://x.test/a.png", "mimeType": "image/png", "sizes": ["32x32"], "theme": "light"},
        {"src": "https://x.test/b.png", "mimeType": None, "sizes": ["any"], "theme": None},
    ]
    assert serialize_icons(None) == []
    assert serialize_icons("https://x.test/a.png") == []


def test_ranking_prefers_light_theme_then_the_size_nearest_the_chip_and_drops_unsafe_schemes():
    icons = serialize_icons(
        [
            {"src": "https://x.test/dark-32.png", "sizes": ["32x32"], "theme": "dark"},
            {"src": "https://x.test/light-512.png", "sizes": ["512x512"], "theme": "light"},
            {"src": "https://x.test/light-48.png", "sizes": ["48x48"], "theme": "light"},
            {"src": "http://x.test/insecure.png", "sizes": ["32x32"]},
            {"src": "file:///etc/passwd"},
            {"src": "javascript:alert(1)"},
            {"src": "https://x.test/vector.svg", "sizes": ["any"]},
            {"src": "https://x.test/light-48.png", "sizes": ["48x48"], "theme": "light"},
        ]
    )
    assert rank_icon_candidates(icons) == [
        "https://x.test/vector.svg",
        "https://x.test/light-48.png",
        "https://x.test/light-512.png",
        "https://x.test/dark-32.png",
    ]


# --- fetching --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_https_icon_is_fetched_and_stored_as_a_data_url():
    seen: List[httpx.Request] = []
    client = client_for(lambda request: httpx.Response(200, content=PNG, headers={"content-type": "image/png"}), seen)
    result = await resolve_server_icon([{"src": "https://icons.example.com/a.png"}], client=client)
    assert result == data_url("image/png", PNG)
    assert [str(request.url) for request in seen] == ["https://icons.example.com/a.png"]
    assert "authorization" not in {key.lower() for key in seen[0].headers.keys()}


@pytest.mark.asyncio
async def test_a_second_resolution_comes_from_the_cache_without_a_request():
    seen: List[httpx.Request] = []
    client = client_for(lambda request: httpx.Response(200, content=PNG), seen)
    icons = [{"src": "https://icons.example.com/a.png"}]
    assert await resolve_server_icon(icons, client=client) == data_url("image/png", PNG)
    assert await resolve_server_icon(icons, client=client) == data_url("image/png", PNG)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_failed_fetch_is_remembered_so_a_dead_host_is_not_retried_every_check():
    seen: List[httpx.Request] = []
    client = client_for(lambda request: httpx.Response(404), seen)
    icons = [{"src": "https://icons.example.com/gone.png"}]
    assert await resolve_server_icon(icons, client=client) is None
    assert await resolve_server_icon(icons, client=client) is None
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_better_candidate_is_skipped_when_it_fails_and_the_next_one_is_used():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500) if request.url.path == "/best.png" else httpx.Response(200, content=PNG)

    client = client_for(handler)
    icons = [
        {"src": "https://icons.example.com/best.png", "sizes": ["32x32"]},
        {"src": "https://icons.example.com/next.png", "sizes": ["64x64"]},
    ]
    assert await resolve_server_icon(icons, client=client) == data_url("image/png", PNG)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(301, headers={"location": "https://internal.example/x.png"}),
        httpx.Response(404),
        httpx.Response(200, content=b"<html>login</html>", headers={"content-type": "image/png"}),
        httpx.Response(200, content=PNG + b"\x00" * (MAX_ICON_BYTES + 1)),
        httpx.Response(200, content=PNG, headers={"content-length": str(MAX_ICON_BYTES + 1)}),
        httpx.Response(200, content=b""),
    ],
)
@pytest.mark.asyncio
async def test_redirects_bad_status_wrong_content_and_oversize_bodies_give_no_icon(response):
    client = client_for(lambda request: response)
    assert await resolve_server_icon([{"src": "https://icons.example.com/a.png"}], client=client) is None


@pytest.mark.asyncio
async def test_a_transport_error_gives_no_icon_instead_of_raising():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    assert await resolve_server_icon([{"src": "https://icons.example.com/a.png"}], client=client_for(boom)) is None


@pytest.mark.parametrize(
    "src",
    [
        "http://icons.example.com/a.png",
        "ftp://icons.example.com/a.png",
        "https://user:pass@icons.example.com/a.png",
        "https:///a.png",
    ],
)
@pytest.mark.asyncio
async def test_only_plain_https_urls_without_credentials_are_fetched(src):
    seen: List[httpx.Request] = []
    client = client_for(lambda request: httpx.Response(200, content=PNG), seen)
    assert await resolve_server_icon([{"src": src}], client=client) is None
    assert seen == []


@pytest.mark.asyncio
async def test_a_data_uri_icon_needs_no_network():
    seen: List[httpx.Request] = []
    client = client_for(lambda request: httpx.Response(500), seen)
    assert await resolve_server_icon([{"src": data_url("image/png", PNG)}], client=client) == data_url("image/png", PNG)
    assert seen == []


# --- the non-public host guard (the real function, with a stubbed resolver) -----------------


@pytest.fixture
def real_host_check():
    return REAL_HOST_IS_PUBLIC


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "10.0.0.5", "192.168.1.9", "169.254.169.254", "172.16.0.1", "0.0.0.0", "::1", "fe80::1", "fd00::1", "224.0.0.1", "localhost", "printer.local", "db.internal"],
)
@pytest.mark.asyncio
async def test_loopback_private_link_local_and_local_names_are_not_public(real_host_check, host):
    assert await real_host_check(host) is False


@pytest.mark.asyncio
async def test_public_literals_pass_and_names_must_resolve_only_to_public_addresses(real_host_check, monkeypatch):
    assert await real_host_check("93.184.216.34") is True

    class Loop:
        def __init__(self, addresses):
            self.addresses = addresses

        async def getaddrinfo(self, host, port, type=0):
            return [(2, 1, 6, "", (address, port)) for address in self.addresses]

    def resolving_to(*addresses):
        monkeypatch.setattr(server_icon, "asyncio", SimpleNamespace(get_running_loop=lambda: Loop(addresses)))

    resolving_to("93.184.216.34")
    assert await real_host_check("icons.example.com") is True
    resolving_to("93.184.216.34", "10.0.0.7")
    assert await real_host_check("rebinding.example.com") is False
    resolving_to()
    assert await real_host_check("empty.example.com") is False


@pytest.mark.asyncio
async def test_an_icon_on_a_non_public_host_is_never_requested(monkeypatch):
    async def private(_host: str) -> bool:
        return False

    monkeypatch.setattr(server_icon, "_host_is_public", private)
    seen: List[httpx.Request] = []
    client = client_for(lambda request: httpx.Response(200, content=PNG), seen)
    assert await resolve_server_icon([{"src": "https://169.254.169.254/latest/meta-data"}], client=client) is None
    assert seen == []


# --- the envelope step ----------------------------------------------------------------------


def envelope(server: dict) -> dict:
    return {"ok": True, "result": {"server": server, "tools": []}}


@pytest.mark.asyncio
async def test_attach_adds_the_icon_and_the_advertised_flag():
    client = client_for(lambda request: httpx.Response(200, content=PNG))
    result = envelope({"name": "x", "icons": [{"src": "https://icons.example.com/a.png"}]})
    await attach_server_icon(result, client=client)
    server = result["result"]["server"]
    assert server["icons_advertised"] is True
    assert server["icon_data_url"] == data_url("image/png", PNG)


@pytest.mark.asyncio
async def test_attach_marks_a_server_with_no_icons_as_advertising_none():
    result = envelope({"name": "x", "icons": []})
    await attach_server_icon(result)
    server = result["result"]["server"]
    assert server["icons_advertised"] is False
    assert server["icon_data_url"] is None


@pytest.mark.asyncio
async def test_attach_keeps_advertised_true_with_no_icon_when_every_candidate_fails():
    client = client_for(lambda request: httpx.Response(404))
    result = envelope({"icons": [{"src": "https://icons.example.com/a.png"}]})
    await attach_server_icon(result, client=client)
    server = result["result"]["server"]
    assert server["icons_advertised"] is True
    assert server["icon_data_url"] is None


@pytest.mark.parametrize(
    "value",
    [
        {"ok": False, "error": {"kind": "timeout"}},
        {"ok": True, "result": {"tools": []}},
        {"ok": True, "result": {"server": {"name": "gmail"}, "tools": []}},
        {"ok": True, "result": None},
        None,
        "not an envelope",
    ],
)
@pytest.mark.asyncio
async def test_attach_leaves_errors_and_in_process_servers_alone(value):
    before = repr(value)
    await attach_server_icon(value)
    assert repr(value) == before


# --- through the client service, the record and the DTO ----------------------------------------


@pytest.mark.asyncio
async def test_list_tools_attaches_the_icon_after_the_session_returns(monkeypatch):
    from api.services.mcp_connectors.mcp_client_service import MCPClientService

    service = MCPClientService()

    async def fake_run_in_session(**_kwargs):
        return {"ok": True, "result": {"server": {"name": "Acme", "icons": [{"src": data_url("image/png", PNG)}]}, "tools": []}}

    monkeypatch.setattr(service, "_run_in_session", fake_run_in_session)
    envelope = await service.list_tools("https://mcp.example.com/mcp", "token")
    assert envelope["result"]["server"]["icon_data_url"] == data_url("image/png", PNG)
    assert envelope["result"]["server"]["icons_advertised"] is True


@pytest.mark.asyncio
async def test_list_tools_returns_an_error_envelope_untouched(monkeypatch):
    from api.services.mcp_connectors.mcp_client_service import MCPClientService

    service = MCPClientService()
    failure = {"ok": False, "error": {"kind": "auth_expired"}}

    async def fake_run_in_session(**_kwargs):
        return failure

    monkeypatch.setattr(service, "_run_in_session", fake_run_in_session)
    assert await service.list_tools("https://mcp.example.com/mcp", "token") is failure


def test_the_stored_icon_reaches_the_connection_dto_and_defaults_to_none():
    from api.core.models.preference_models.execution_and_connections import MCPConnectionRecord
    from api.routes.connections.connection_route_helpers import connection_to_dto

    record = MCPConnectionRecord(friendly_name="Acme", server_url="https://mcp.example.com/mcp")
    assert record.server_icon_data_url is None
    assert connection_to_dto(record).server_icon_data_url is None
    record.server_icon_data_url = data_url("image/png", PNG)
    dto = connection_to_dto(record)
    assert dto.server_icon_data_url == data_url("image/png", PNG)
    assert dto.model_dump(mode="json")["server_icon_data_url"] == data_url("image/png", PNG)
