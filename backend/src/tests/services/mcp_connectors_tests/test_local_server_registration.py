"""Registering a local stdio server: the service, the route, the setup receipt payload, and the setup-agent executor, against an in-memory copy of the preferences and a real fixture server."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.models.preferences import Preferences
from api.core.preferences import preferences_io
from api.core.security.backend_request_guard import require_host_credential
from api.routes.connections.routes import router
from api.routes.setup_assistant.models import SetupExecutionStatus, SetupToolCall, SetupToolApprovalState
from api.services.mcp_connectors.local_server_registration import (
    DuplicateLocalServerError,
    discard_local_server_record,
    register_local_server_record,
)
from api.services.mcp_connectors.stdio_transport import StdioSpecError
from api.services.setup_assistant.action_execution_service import SetupAssistantActionExecutionService
from api.services.setup_assistant.agent_graph.setup_agent_tooling.local_server_payload import (
    normalize_register_local_server_payload,
)

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))


@pytest.fixture
def stored_preferences(monkeypatch) -> Preferences:
    """Preferences kept in memory; every load returns a copy, as a read from disk would."""
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder  # type: ignore[return-value]


def _stored(holder) -> List[Any]:
    return holder["value"].connections.mcp_connections


@pytest.fixture
def client(stored_preferences) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_host_credential] = lambda: None
    return TestClient(app)


def _body(**overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"friendly_name": "Fixture server", "command": sys.executable, "args": [FIXTURE]}
    body.update(overrides)
    return body


def test_a_valid_server_is_stored_with_a_local_address_and_no_launch(stored_preferences):
    record = register_local_server_record(friendly_name=" Fixture ", command=sys.executable, args=[FIXTURE], source_url="https://example.com/x")

    assert record.server_url == f"basil-stdio://{record.id}"
    assert record.friendly_name == "Fixture"
    assert record.stdio and record.stdio.source_url == "https://example.com/x"
    assert [stored.id for stored in _stored(stored_preferences)] == [record.id]


def test_the_same_command_twice_is_a_duplicate_and_stores_nothing_new(stored_preferences):
    register_local_server_record(friendly_name="One", command=sys.executable, args=[FIXTURE])

    with pytest.raises(DuplicateLocalServerError):
        register_local_server_record(friendly_name="Two", command=sys.executable, args=[FIXTURE])

    assert len(_stored(stored_preferences)) == 1


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_a_missing_or_overlong_name_is_refused(stored_preferences, name):
    with pytest.raises(StdioSpecError):
        register_local_server_record(friendly_name=name, command=sys.executable, args=[FIXTURE])

    assert _stored(stored_preferences) == []


def test_discard_removes_only_the_named_local_record_and_is_safe_to_repeat(stored_preferences):
    keep = register_local_server_record(friendly_name="Keep", command=sys.executable, args=[FIXTURE, "a"])
    drop = register_local_server_record(friendly_name="Drop", command=sys.executable, args=[FIXTURE, "b"])

    discard_local_server_record(drop.id)
    discard_local_server_record(drop.id)

    assert [stored.id for stored in _stored(stored_preferences)] == [keep.id]


def test_the_route_registers_starts_the_server_and_returns_its_tools(client, stored_preferences):
    response = client.post("/settings/connections/local_server", json=_body())

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["auth_kind"] == "local"
    assert {tool["name"] for tool in data["tools"]} >= {"echo", "where_am_i"}
    stored = _stored(stored_preferences)
    assert len(stored) == 1 and stored[0].cached_tools and stored[0].last_connection_status_message == "Connected."


def test_the_route_removes_a_server_that_does_not_start(client, stored_preferences):
    response = client.post("/settings/connections/local_server", json=_body(args=["-c", "raise SystemExit(3)"]))

    assert response.status_code == 502
    assert _stored(stored_preferences) == []


def test_the_route_answers_conflict_for_a_duplicate(client, stored_preferences):
    assert client.post("/settings/connections/local_server", json=_body()).status_code == 200

    response = client.post("/settings/connections/local_server", json=_body(friendly_name="Again"))

    assert response.status_code == 409
    assert len(_stored(stored_preferences)) == 1


def test_the_route_answers_unprocessable_for_a_command_that_cannot_exist(client, stored_preferences):
    response = client.post("/settings/connections/local_server", json=_body(command="definitely-not-a-real-program-xyz", args=[]))

    assert response.status_code == 422
    assert _stored(stored_preferences) == []


def test_the_setup_payload_is_normalized_and_stray_keys_are_refused():
    payload = normalize_register_local_server_payload({"friendly_name": " Fixture ", "command": sys.executable, "args": [FIXTURE]})

    assert payload == {"friendly_name": "Fixture", "command": sys.executable, "args": [FIXTURE], "env": {}}
    with pytest.raises(ValueError, match="does not take"):
        normalize_register_local_server_payload({**payload, "shell": "rm -rf /"})
    with pytest.raises(ValueError, match="friendly_name"):
        normalize_register_local_server_payload({"command": sys.executable})
    with pytest.raises(ValueError, match="args must be a list"):
        normalize_register_local_server_payload({"friendly_name": "x", "command": sys.executable, "args": "a b"})
    with pytest.raises(ValueError, match="cannot be registered"):
        normalize_register_local_server_payload({"friendly_name": "x", "command": "definitely-not-a-real-program-xyz"})


def _tool_call(payload: Dict[str, Any]) -> SetupToolCall:
    return SetupToolCall(
        id="proposal-local",
        tool_name="register_local_mcp_server",
        payload=payload,
        approval_state=SetupToolApprovalState.approved,
        user_visible_summary="Connect a local server",
    )


async def _refresher_for(client_app: TestClient):
    async def refresh(connection_id: str) -> Dict[str, Any]:
        from api.routes.connections.routes import refresh_tools

        class _Request:  # refresh_tools only needs the argument to exist
            pass

        return (await refresh_tools(connection_id, _Request())).model_dump(mode="json")  # type: ignore[arg-type]

    return refresh


@pytest.mark.asyncio
async def test_the_setup_executor_registers_and_reports_the_tools(stored_preferences, client):
    service = SetupAssistantActionExecutionService(connection_refresher=await _refresher_for(client))

    results = await service.execute_approved_setup_actions(
        actions=[], tool_calls=[_tool_call({"friendly_name": "Fixture", "command": sys.executable, "args": [FIXTURE]})]
    )

    assert [item.status for item in results] == [SetupExecutionStatus.applied]
    assert "echo" in results[0].result_payload["tool_names"]
    assert len(_stored(stored_preferences)) == 1


@pytest.mark.asyncio
async def test_the_setup_executor_discards_a_server_that_does_not_start(stored_preferences, client):
    service = SetupAssistantActionExecutionService(connection_refresher=await _refresher_for(client))

    results = await service.execute_approved_setup_actions(
        actions=[], tool_calls=[_tool_call({"friendly_name": "Broken", "command": sys.executable, "args": ["-c", "raise SystemExit(3)"]})]
    )

    assert [item.status for item in results] == [SetupExecutionStatus.failed]
    assert "would not start" in results[0].message
    assert _stored(stored_preferences) == []


@pytest.mark.asyncio
async def test_check_status_starts_a_local_server_and_reports_it_healthy_without_a_sign_in(stored_preferences):
    from api.services.mcp_connectors.connection_status_service import STATUS_HEALTHY, STATUS_ERROR, check_connection_status

    record = register_local_server_record(friendly_name="Fixture", command=sys.executable, args=[FIXTURE])
    result = await check_connection_status(record)
    assert result.status == STATUS_HEALTHY

    broken = register_local_server_record(friendly_name="Broken", command=sys.executable, args=["-c", "raise SystemExit(3)"])
    broken_result = await check_connection_status(broken)
    assert broken_result.status == STATUS_ERROR
    assert "stopped before it finished starting" in broken_result.message
