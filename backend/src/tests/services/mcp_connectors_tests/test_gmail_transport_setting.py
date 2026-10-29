"""The Gmail transport choice: saved setting, environment override, routing, and the Settings endpoints."""

from __future__ import annotations

import pytest

from api.core.models.preferences import Preferences
from api.routes.connections import gmail_transport_routes as routes
from api.services.mcp_connectors.gmail_local_server import transport
from api.services.mcp_connectors.mcp_client_service import MCPClientService

GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"


class SavedPreferences:
    """The preferences under test plus every transport value the routes wrote."""

    def __init__(self, prefs: Preferences, writes: list) -> None:
        self.connections = prefs.connections
        self.writes = writes


@pytest.fixture
def saved(monkeypatch):
    """An in-memory stand-in for preferences.json, shared by the transport lookup and the routes."""
    prefs = Preferences()
    monkeypatch.delenv("BASIL_GMAIL_TRANSPORT", raising=False)
    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", lambda: prefs)
    monkeypatch.setattr(routes, "load_connection_preferences", lambda: prefs)
    writes = []
    monkeypatch.setattr(routes, "save_connection_preferences", lambda value: writes.append(value.connections.gmail_transport))
    return SavedPreferences(prefs, writes)


def test_default_is_the_direct_gmail_api(saved):
    assert transport.gmail_transport() == "direct"
    assert transport.gmail_uses_direct_api() is True
    assert MCPClientService._routes_to_local_server(GMAIL_URL) is True


def test_saved_hosted_choice_sends_gmail_to_the_hosted_server(saved):
    saved.connections.gmail_transport = "mcp"
    assert transport.gmail_transport() == "mcp"
    assert MCPClientService._routes_to_local_server(GMAIL_URL) is False


def test_environment_overrides_the_saved_choice_both_ways(saved, monkeypatch):
    saved.connections.gmail_transport = "mcp"
    monkeypatch.setenv("BASIL_GMAIL_TRANSPORT", "direct")
    assert transport.gmail_transport() == "direct"
    saved.connections.gmail_transport = "direct"
    monkeypatch.setenv("BASIL_GMAIL_TRANSPORT", "mcp")
    assert transport.gmail_transport() == "mcp"


def test_unrecognized_environment_value_is_ignored(saved, monkeypatch):
    saved.connections.gmail_transport = "mcp"
    monkeypatch.setenv("BASIL_GMAIL_TRANSPORT", "carrier-pigeon")
    assert transport.gmail_transport() == "mcp"


def test_unreadable_preferences_fall_back_to_direct(monkeypatch):
    monkeypatch.delenv("BASIL_GMAIL_TRANSPORT", raising=False)

    def broken():
        raise OSError("preferences.json is unreadable")

    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", broken)
    assert transport.gmail_transport() == "direct"


@pytest.mark.asyncio
async def test_get_reports_saved_and_effective_choice(saved):
    saved.connections.gmail_transport = "mcp"
    result = await routes.get_gmail_transport_route()
    assert (result.saved, result.effective, result.pinned_by_environment) == ("mcp", "mcp", False)


@pytest.mark.asyncio
async def test_get_reports_when_the_environment_pins_the_transport(saved, monkeypatch):
    monkeypatch.setenv("BASIL_GMAIL_TRANSPORT", "mcp")
    result = await routes.get_gmail_transport_route()
    assert (result.saved, result.effective, result.pinned_by_environment) == ("direct", "mcp", True)


@pytest.mark.asyncio
async def test_put_saves_a_change_once_and_skips_an_unchanged_value(saved):
    result = await routes.set_gmail_transport_route(routes.GmailTransportUpdate(transport="mcp"))
    assert result.saved == "mcp" and saved.writes == ["mcp"]
    await routes.set_gmail_transport_route(routes.GmailTransportUpdate(transport="mcp"))
    assert saved.writes == ["mcp"]


def test_put_rejects_an_unknown_transport():
    with pytest.raises(ValueError):
        routes.GmailTransportUpdate(transport="smoke-signals")
