"""Gmail MCP uses a pre-registered Google client (no dynamic registration)."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from api.routes.connections.models import STARTER_SERVERS
from api.services.mcp_connectors import oauth_coordinator as oc

GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"


def test_gmail_is_a_starter_server():
    gmail = next(s for s in STARTER_SERVERS if s.id == "gmail")
    assert gmail.server_url == GMAIL_URL
    assert gmail.friendly_name == "Gmail"


def test_is_google_gmail_mcp_url():
    assert oc.is_google_gmail_mcp_url(GMAIL_URL)
    assert not oc.is_google_gmail_mcp_url("https://mcp.linear.app/mcp")


def test_load_client_handles_installed_wrapper(tmp_path, monkeypatch):
    f = tmp_path / "client.json"
    f.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
    monkeypatch.setenv("BASIL_GMAIL_OAUTH_CLIENT_FILE", str(f))
    assert oc.load_google_oauth_client() == {"client_id": "cid", "client_secret": "sec"}


@pytest.mark.asyncio
async def test_begin_registration_builds_google_url_without_network(tmp_path, monkeypatch):
    f = tmp_path / "client.json"
    f.write_text(json.dumps({"client_id": "cid", "client_secret": "sec"}))
    monkeypatch.setenv("BASIL_GMAIL_OAUTH_CLIENT_FILE", str(f))
    coordinator = oc.OAuthCoordinator()
    result = await coordinator.begin_registration(
        server_url=GMAIL_URL,
        friendly_name="Gmail",
        redirect_uri="http://127.0.0.1:8123/callback",
    )
    url = urlparse(result["authorization_url"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert q["client_id"] == ["cid"]
    assert q["access_type"] == ["offline"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["scope"] == ["https://www.googleapis.com/auth/gmail.modify"]

@pytest.mark.asyncio
async def test_hosted_mcp_transport_requests_the_same_modify_scope(tmp_path, monkeypatch):
    f = tmp_path / "client.json"
    f.write_text(json.dumps({"client_id": "cid", "client_secret": "sec"}))
    monkeypatch.setenv("BASIL_GMAIL_OAUTH_CLIENT_FILE", str(f))
    monkeypatch.setenv("BASIL_GMAIL_TRANSPORT", "mcp")
    result = await oc.OAuthCoordinator().begin_registration(
        server_url=GMAIL_URL,
        friendly_name="Gmail",
        redirect_uri="http://127.0.0.1:8123/callback",
    )
    scopes = parse_qs(urlparse(result["authorization_url"]).query)["scope"][0].split()
    assert scopes == ["https://www.googleapis.com/auth/gmail.modify"]
