"""Agent-started connection sign-ins use the same flows as Settings and hand the browser step to the client."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.services.mcp_connectors import connection_setup_runner as runner
from api.services.mcp_connectors.backend_origin import (
    get_backend_origin,
    remember_backend_origin,
    reset_backend_origin,
)
from api.services.mcp_connectors.connection_setup_plan import ConnectionSetupError, plan_connection_setup
from api.services.mcp_connectors.external_url_bridge import is_openable_https_url


@pytest.fixture(autouse=True)
def clean_origin():
    reset_backend_origin()
    yield
    reset_backend_origin()


def _plan(url: str, name: str | None = None):
    return plan_connection_setup(url, name, registered_connections=[])


@pytest.fixture
def opened_urls(monkeypatch):
    opened: list[tuple[str, str]] = []

    async def fake_open(url: str, *, purpose: str) -> bool:
        opened.append((url, purpose))
        return True

    monkeypatch.setattr(runner, "open_external_url_in_client", fake_open)
    return opened


def test_only_loopback_origins_are_remembered() -> None:
    remember_backend_origin("https://evil.example.com/")
    assert get_backend_origin() is None

    remember_backend_origin("http://127.0.0.1:8123/")
    assert get_backend_origin() == "http://127.0.0.1:8123"

    remember_backend_origin("http://attacker.test:1/")
    assert get_backend_origin() == "http://127.0.0.1:8123"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://accounts.example.com/authorize?x=1", True),
        ("http://accounts.example.com/authorize", False),
        ("basil://mcp/connection_complete", False),
        ("https://user:pw@accounts.example.com/", False),
        ("javascript:alert(1)", False),
        ("", False),
    ],
)
def test_client_is_only_ever_asked_to_open_plain_https_addresses(url: str, expected: bool) -> None:
    assert is_openable_https_url(url) is expected


@pytest.mark.asyncio
async def test_generic_oauth_needs_the_backend_origin() -> None:
    with pytest.raises(ConnectionSetupError):
        await runner.run_connection_setup(_plan("https://mcp.notion.com/mcp"))


@pytest.mark.asyncio
async def test_generic_oauth_opens_the_authorization_page_with_the_local_redirect(monkeypatch, opened_urls) -> None:
    remember_backend_origin("http://127.0.0.1:8123")
    seen = {}

    async def fake_begin(payload, redirect_uri):
        seen["payload"] = payload
        seen["redirect_uri"] = redirect_uri
        return SimpleNamespace(state="s", authorization_url="https://auth.notion.com/authorize?state=s")

    monkeypatch.setattr("api.routes.connections.routes.begin_oauth_sign_in", fake_begin)

    result = await runner.run_connection_setup(_plan("https://mcp.notion.com/mcp"))

    assert seen["redirect_uri"] == "http://127.0.0.1:8123/settings/connections/oauth/callback/mcp"
    assert seen["payload"].server_url == "https://mcp.notion.com/mcp"
    assert opened_urls == [("https://auth.notion.com/authorize?state=s", "connection_sign_in")]
    assert result["status"] == "sign_in_started"
    assert result["browser_opened"] is True
    assert "authorization_url" not in result


@pytest.mark.asyncio
async def test_the_link_is_returned_only_when_the_browser_could_not_be_opened(monkeypatch) -> None:
    remember_backend_origin("http://127.0.0.1:8123")

    async def fake_begin(payload, redirect_uri):
        return SimpleNamespace(state="s", authorization_url="https://auth.notion.com/authorize?state=s")

    async def fake_open(url: str, *, purpose: str) -> bool:
        return False

    monkeypatch.setattr("api.routes.connections.routes.begin_oauth_sign_in", fake_begin)
    monkeypatch.setattr(runner, "open_external_url_in_client", fake_open)

    result = await runner.run_connection_setup(_plan("https://mcp.notion.com/mcp"))

    assert result["browser_opened"] is False
    assert result["authorization_url"] == "https://auth.notion.com/authorize?state=s"


@pytest.mark.asyncio
async def test_a_server_without_oauth_support_falls_back_to_a_manual_token_instruction(monkeypatch, opened_urls) -> None:
    remember_backend_origin("http://127.0.0.1:8123")

    async def fake_begin(payload, redirect_uri):
        raise HTTPException(status_code=400, detail="No OAuth metadata found")

    monkeypatch.setattr("api.routes.connections.routes.begin_oauth_sign_in", fake_begin)

    result = await runner.run_connection_setup(_plan("https://mcp.example.org/mcp"))

    assert result["status"] == "needs_manual_token"
    assert "Manual Bearer Token Server" in result["message"]
    assert "never into the chat" in result["message"]
    assert opened_urls == []


@pytest.mark.asyncio
async def test_an_upstream_failure_surfaces_as_a_setup_error_not_a_manual_token(monkeypatch, opened_urls) -> None:
    remember_backend_origin("http://127.0.0.1:8123")

    async def fake_begin(payload, redirect_uri):
        raise HTTPException(status_code=500, detail="OAuth start failed: boom")

    monkeypatch.setattr("api.routes.connections.routes.begin_oauth_sign_in", fake_begin)

    with pytest.raises(ConnectionSetupError, match="boom"):
        await runner.run_connection_setup(_plan("https://mcp.example.org/mcp"))


@pytest.mark.asyncio
async def test_slack_uses_the_pkce_route(monkeypatch, opened_urls) -> None:
    async def fake_slack(payload):
        assert payload.server_url == "https://mcp.slack.com/mcp"
        return SimpleNamespace(state="s", authorization_url="https://slack.com/oauth/v2_user/authorize?x=1", requested_scopes=[])

    monkeypatch.setattr("api.routes.connections.slack_routes.slack_start_oauth", fake_slack)

    result = await runner.run_connection_setup(_plan("https://mcp.slack.com/mcp"))

    assert result["flow"] == "slack_pkce"
    assert opened_urls[0][0].startswith("https://slack.com/")


@pytest.mark.asyncio
async def test_github_shows_the_code_opens_the_device_page_and_finishes_in_the_background(monkeypatch, opened_urls) -> None:
    monkeypatch.setattr(runner, "_MIN_POLL_INTERVAL_SECONDS", 0)
    polls = {"count": 0}

    async def fake_start(payload):
        assert payload.server_url == "https://api.githubcopilot.com/mcp/"
        return SimpleNamespace(
            device_code="dev-code-123456",
            user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
            expires_in=30,
            interval=0,
            requested_scopes=[],
        )

    async def fake_poll(payload):
        polls["count"] += 1
        assert payload.device_code == "dev-code-123456"
        if polls["count"] < 2:
            return SimpleNamespace(status="pending", interval=0, connection=None, message="authorization_pending")
        return SimpleNamespace(status="ok", interval=None, connection=SimpleNamespace(id="gh"), message=None)

    monkeypatch.setattr("api.routes.connections.routes.start_github_device_flow", fake_start)
    monkeypatch.setattr("api.routes.connections.routes.poll_github_device_flow", fake_poll)

    result = await runner.run_connection_setup(_plan("https://api.githubcopilot.com/mcp/"))

    assert result["user_code"] == "ABCD-1234"
    assert "ABCD-1234" in result["message"]
    assert opened_urls == [("https://github.com/login/device", "connection_sign_in")]
    for _ in range(100):
        if runner.pending_background_poll_count() == 0:
            break
        await asyncio.sleep(0.01)
    assert runner.pending_background_poll_count() == 0
    assert polls["count"] == 2


@pytest.mark.asyncio
async def test_a_rejected_github_approval_stops_polling(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_MIN_POLL_INTERVAL_SECONDS", 0)
    polls = {"count": 0}

    async def fake_poll(payload):
        polls["count"] += 1
        raise HTTPException(status_code=400, detail="access_denied")

    monkeypatch.setattr("api.routes.connections.routes.poll_github_device_flow", fake_poll)

    await runner._poll_github_device_flow("dev", 0, 30)

    assert polls["count"] == 1


@pytest.mark.asyncio
async def test_an_already_connected_server_is_never_started_again() -> None:
    plan = plan_connection_setup(
        "https://mcp.notion.com/mcp",
        registered_connections=[SimpleNamespace(id="n", server_url="https://mcp.notion.com/mcp", friendly_name="Notion")],
    )

    with pytest.raises(ConnectionSetupError, match="already connected"):
        await runner.run_connection_setup(plan)
