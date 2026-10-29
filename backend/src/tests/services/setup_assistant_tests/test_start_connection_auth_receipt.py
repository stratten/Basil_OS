"""The setup agent's connection sign-in receipt is built from the pasted address, never from model-chosen routing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routes.setup_assistant.models import SetupAgentEvent, SetupPrivacyImpact
from api.services.setup_assistant.agent_graph.setup_agent_tooling.connection_auth_payload import (
    normalize_start_connection_auth_payload,
)
from api.services.setup_assistant.agent_graph.setup_agent_tools import (
    SetupAgentToolFactory,
    SetupPendingProposalStore,
)


@pytest.fixture(autouse=True)
def no_registered_connections(monkeypatch):
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )


def test_pasted_address_decides_the_connector_and_ignores_a_model_supplied_one() -> None:
    payload = normalize_start_connection_auth_payload(
        {"connector_id": "github", "server_url": "https://mcp.notion.com/mcp", "friendly_name": "Notion"}
    )

    assert payload == {
        "connector_id": "custom",
        "server_url": "https://mcp.notion.com/mcp",
        "friendly_name": "Notion",
    }


def test_catalog_address_is_canonicalized_to_its_connector() -> None:
    payload = normalize_start_connection_auth_payload({"serverUrl": "https://api.githubcopilot.com/mcp"})

    assert payload["connector_id"] == "github"
    assert payload["server_url"] == "https://api.githubcopilot.com/mcp/"
    assert payload["friendly_name"] == "GitHub"


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({}, "server_url"),
        ({"server_url": "   "}, "server_url"),
        ({"server_url": "http://mcp.example.com/mcp"}, "https"),
        ({"server_url": "https://localhost:3000/mcp"}, "private network"),
    ],
)
def test_unusable_addresses_come_back_as_corrective_errors(payload, expected) -> None:
    with pytest.raises(ValueError) as error:
        normalize_start_connection_auth_payload(payload)

    assert expected in str(error.value)


def test_an_already_connected_server_is_not_proposed_again(monkeypatch) -> None:
    existing = SimpleNamespace(id="n1", server_url="https://mcp.notion.com/mcp", friendly_name="Notion")
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[existing])),
    )

    with pytest.raises(ValueError) as error:
        normalize_start_connection_auth_payload({"server_url": "https://mcp.notion.com/mcp/"})

    assert "already connected" in str(error.value)


@pytest.mark.asyncio
async def test_the_proposed_receipt_carries_the_derived_payload_and_the_authentication_flags() -> None:
    events: list[SetupAgentEvent] = []

    async def emit_event(event: SetupAgentEvent) -> None:
        events.append(event)

    factory = SetupAgentToolFactory(event_emitter=emit_event, proposal_store=SetupPendingProposalStore())
    propose = next(tool for tool in factory.create_setup_agent_tools() if tool.name == "propose_consent_receipt")

    await propose.arun(
        {
            "title": "Connect Notion",
            "rationale": "Sign in to Notion in your browser at https://mcp.notion.com/mcp.",
            "mutation_tool_name": "start_connection_auth",
            "mutation_payload": {"connector_id": "github", "server_url": "https://mcp.notion.com/mcp"},
        }
    )

    receipt = events[-1].payload["receipt"]
    assert receipt["tool_call"]["tool_name"] == "start_connection_auth"
    assert receipt["tool_call"]["payload"] == {
        "connector_id": "custom",
        "server_url": "https://mcp.notion.com/mcp",
        "friendly_name": "Notion",
    }
    assert receipt["tool_call"]["privacy_impact"] == SetupPrivacyImpact.authenticates_service.value
    assert receipt["tool_call"]["mutates_external_state"] is True


@pytest.mark.asyncio
async def test_a_bad_address_never_becomes_a_receipt() -> None:
    events: list[SetupAgentEvent] = []

    async def emit_event(event: SetupAgentEvent) -> None:
        events.append(event)

    factory = SetupAgentToolFactory(event_emitter=emit_event, proposal_store=SetupPendingProposalStore())
    propose = next(tool for tool in factory.create_setup_agent_tools() if tool.name == "propose_consent_receipt")

    result = await propose.arun(
        {
            "title": "Connect it",
            "rationale": "Sign in.",
            "mutation_tool_name": "start_connection_auth",
            "mutation_payload": {"server_url": "http://192.168.1.4/mcp"},
        }
    )

    assert "cannot be connected" in result
    assert all(event.payload.get("receipt") is None for event in events)
