"""A pasted MCP server address is validated and classified deterministically before any agent proposes or starts a connection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.mcp_connectors.connection_setup_plan import (
    ConnectionSetupError,
    derive_friendly_name,
    normalize_server_url,
    plan_connection_setup,
)


def _record(record_id: str, url: str, name: str = "Existing"):
    return SimpleNamespace(id=record_id, server_url=url, friendly_name=name)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "http://mcp.example.com/mcp",
        "ftp://mcp.example.com/mcp",
        "javascript:alert(1)",
        "https://user:secret@mcp.example.com/mcp",
        "https://localhost/mcp",
        "https://127.0.0.1/mcp",
        "https://192.168.1.20/mcp",
        "https://10.0.0.5/mcp",
        "https://[::1]/mcp",
        "https://printer.local/mcp",
        "https://intranet/mcp",
        "https://mcp.example.com/a b",
        "https://mcp.example.com:notaport/mcp",
        "https://mcp.example.com/" + "a" * 2100,
    ],
)
def test_unsafe_or_malformed_addresses_are_rejected(raw: str) -> None:
    with pytest.raises(ConnectionSetupError):
        normalize_server_url(raw)


def test_bare_host_gets_https_and_the_fragment_and_default_port_are_dropped() -> None:
    assert normalize_server_url("MCP.Example.com:443/mcp#section") == "https://mcp.example.com/mcp"
    assert normalize_server_url("mcp.example.com") == "https://mcp.example.com/"
    assert normalize_server_url("https://mcp.example.com:8443/mcp?x=1") == "https://mcp.example.com:8443/mcp?x=1"


def test_github_address_uses_the_device_flow_and_the_canonical_url() -> None:
    plan = plan_connection_setup("https://api.githubcopilot.com/mcp", registered_connections=[])

    assert plan.flow == "github_device"
    assert plan.connector_id == "github"
    assert plan.server_url == "https://api.githubcopilot.com/mcp/"
    assert plan.friendly_name == "GitHub"
    assert plan.already_connected is False


def test_slack_address_uses_pkce_and_linear_uses_generic_oauth_as_a_starter() -> None:
    slack = plan_connection_setup("https://mcp.slack.com/mcp", registered_connections=[])
    linear = plan_connection_setup("https://mcp.linear.app/mcp/", registered_connections=[])

    assert (slack.flow, slack.connector_id) == ("slack_pkce", "slack")
    assert (linear.flow, linear.connector_id) == ("oauth", "linear")


def test_unknown_address_uses_generic_oauth_with_a_derived_name() -> None:
    plan = plan_connection_setup("https://mcp.notion.com/mcp", registered_connections=[])

    assert plan.flow == "oauth"
    assert plan.connector_id == "custom"
    assert plan.friendly_name == "Notion"
    assert plan.server_url == "https://mcp.notion.com/mcp"


def test_supplied_name_is_cleaned_and_a_blank_one_falls_back_to_the_host() -> None:
    named = plan_connection_setup("https://mcp.notion.com/mcp", "  My\n Notion\x00  ", registered_connections=[])
    blank = plan_connection_setup("https://mcp.notion.com/mcp", "   ", registered_connections=[])

    assert named.friendly_name == "My Notion"
    assert blank.friendly_name == "Notion"
    assert derive_friendly_name("https://api.example-tools.io/mcp") == "Example Tools"


def test_an_already_registered_server_is_reported_even_with_a_trailing_slash_difference() -> None:
    plan = plan_connection_setup(
        "https://mcp.notion.com/mcp/",
        registered_connections=[_record("abc", "https://MCP.notion.com/mcp", "Notion")],
    )

    assert plan.already_connected is True
    assert plan.existing_connection_id == "abc"
    assert plan.existing_friendly_name == "Notion"


def test_a_connected_slack_that_uses_the_local_sentinel_url_counts_as_connected() -> None:
    plan = plan_connection_setup(
        "https://mcp.slack.com/mcp",
        registered_connections=[_record("slack-1", "basil-local://slack", "Slack")],
    )

    assert plan.already_connected is True
    assert plan.existing_connection_id == "slack-1"
