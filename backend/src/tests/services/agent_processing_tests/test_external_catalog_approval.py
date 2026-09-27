"""Tests for external catalog approval routing."""

from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.external_services import external_catalog_tool
from api.services.agent_processing.tools.external_services import external_connection_inventory
from api.services.agent_processing.tools.external_services.external_catalog import (
    actions as external_catalog_actions,
)
from api.services.agent_processing.tools.external_services.external_catalog import (
    approval as external_catalog_approval,
)
from api.services.agent_processing.tools.external_services.external_catalog import (
    descriptions as external_catalog_descriptions,
)
from api.services.agent_processing.tools.external_services.external_catalog import (
    envelopes as external_catalog_envelopes,
)
from api.services.agent_processing.tools.external_services.external_catalog import (
    rate_limits as external_catalog_rate_limits,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)


class _FakeWebSocketManager:
    async def broadcast(self, _event):
        return None


def _record():
    return SimpleNamespace(
        id="conn-123",
        friendly_name="Linear",
        server_url="https://linear.example/mcp",
    )


def test_external_catalog_auth_unavailable_preserves_keychain_action():
    outcome = SimpleNamespace(
        kind="token_missing",
        message="Basil could not read an access token for this connection from Keychain.",
        user_action_required="Grant Keychain access or reconnect this service in Settings -> Connections.",
    )

    envelope = external_catalog_envelopes.make_external_catalog_auth_unavailable(outcome)

    assert envelope["ok"] is False
    assert envelope["error"]["kind"] == "auth_unavailable"
    assert envelope["error"]["message"] == "Basil could not read an access token for this connection from Keychain."
    assert envelope["error"]["user_action_required"] == "Grant Keychain access or reconnect this service in Settings -> Connections."
    assert envelope["error"]["raw"]["token_outcome"] == "token_missing"


def test_external_catalog_connection_inventory_description_delegates_to_shared_helper(monkeypatch):
    fake_preferences = SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    cached_tools=[SimpleNamespace(name="speakeasy_list_requests")],
                ),
            ]
        )
    )
    monkeypatch.setattr(external_connection_inventory, "_load_preferences", lambda: fake_preferences)

    description = external_catalog_descriptions.format_connection_inventory_for_description()

    assert description.startswith("**CURRENT CONNECTIONS:**")
    assert "Speakeasy - Custom (connection_id=speakeasy-id, cached_tools=1)" in description
    assert "speakeasy_list_requests" in description


def test_external_catalog_tool_contract_is_preserved():
    tool = external_catalog_tool.create_external_catalog_tool()

    assert tool.name == "external_catalog"
    assert tool.args_schema.model_fields["action"].annotation.__args__ == (
        "list_servers",
        "describe_server",
        "call_tool",
    )
    assert "Discover and invoke tools on remote services" in tool.description


@pytest.mark.asyncio
async def test_external_catalog_list_servers_surfaces_connection_context(monkeypatch):
    prefs = SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="linear-prod",
                    friendly_name="Linear",
                    description="Engineering workspace.",
                    server_url="https://mcp.linear.app/mcp",
                    server_name="linear-mcp",
                    server_instructions="Use for Linear issues.",
                    enabled=True,
                    cached_tools=[SimpleNamespace(name="linear_search")],
                )
            ]
        )
    )
    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)

    envelope = await external_catalog_actions.list_external_catalog_servers()

    assert envelope["ok"] is True
    server = envelope["result"]["servers"][0]
    assert server["description"] == "Engineering workspace."
    assert server["server_name"] == "linear-mcp"
    assert server["server_instructions"] == "Use for Linear issues."


@pytest.mark.asyncio
async def test_external_catalog_describe_server_surfaces_connection_description(monkeypatch):
    record = SimpleNamespace(
        id="linear-prod",
        friendly_name="Linear",
        description="Engineering workspace.",
        server_url="https://mcp.linear.app/mcp",
        enabled=True,
        cached_tools=[],
    )
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))

    class FakeClient:
        async def list_tools(self, server_url, access_token):
            return {"ok": True, "result": {"server": {}, "tools": []}}

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="tok")

    async def fake_audit(**kwargs):
        return None

    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)
    monkeypatch.setattr(external_catalog_actions, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(external_catalog_actions, "get_external_catalog_mcp_client", lambda: FakeClient())
    monkeypatch.setattr(external_catalog_actions, "record_external_catalog_audit", fake_audit)

    envelope = await external_catalog_actions.describe_external_catalog_server(record.id)

    assert envelope["ok"] is True
    assert envelope["result"]["connection_id"] == "linear-prod"
    assert envelope["result"]["friendly_name"] == "Linear"
    assert envelope["result"]["description"] == "Engineering workspace."


@pytest.mark.asyncio
async def test_call_tool_recovers_from_a_stale_generic_oauth_token_via_silent_refresh(monkeypatch):
    """A stale (non-Slack) access token is refreshed and the call retried once,
    invisibly to the caller - the auth_expired envelope never reaches the model."""

    record = SimpleNamespace(
        id="linear-prod",
        friendly_name="Linear",
        server_url="https://mcp.linear.app/mcp",
        oauth_client_id="client-abc",
        oauth_token_endpoint="https://linear.app/oauth/token",
        enabled=True,
        cached_tools=[],
        tool_policies={"getIssue": "always_allow"},
    )
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))

    class FakeClient:
        def __init__(self):
            self.tokens_seen = []

        async def call_tool(self, server_url, tool_name, arguments, access_token):
            self.tokens_seen.append(access_token)
            if access_token == "stale-token":
                return {"ok": False, "error": {"kind": "auth_expired", "message": "expired"}}
            return {"ok": True, "result": {"issue": "BAS-1"}}

    client = FakeClient()

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="stale-token")

    async def fake_audit(**kwargs):
        return None

    async def fake_generic_refresh(record_arg, **kwargs):
        assert record_arg.id == "linear-prod"
        return "refreshed-token"

    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)
    monkeypatch.setattr(external_catalog_actions, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(external_catalog_actions, "get_external_catalog_mcp_client", lambda: client)
    monkeypatch.setattr(external_catalog_actions, "record_external_catalog_audit", fake_audit)
    monkeypatch.setattr(
        "api.services.mcp_connectors.generic_oauth_token_refresh.refresh_generic_oauth_access_token",
        fake_generic_refresh,
    )

    from api.services.agent_processing.tools.external_services.external_catalog.schema_guard import (
        mark_tools_surfaced,
    )

    token = set_current_agent_context({})
    try:
        mark_tools_surfaced("linear-prod", ["getIssue"])
        envelope = await external_catalog_actions.call_external_catalog_tool(
            "linear-prod", "getIssue", {"id": "BAS-1"}
        )
    finally:
        reset_current_agent_context(token)

    assert envelope["ok"] is True
    assert envelope["result"]["issue"] == "BAS-1"
    assert client.tokens_seen == ["stale-token", "refreshed-token"]


@pytest.mark.asyncio
async def test_external_catalog_rate_limit_waits_notifies_and_retries(monkeypatch):
    sleeps = []
    progress = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    class FakeNotifier:
        async def send_agent_progress_update(self, message, details=None):
            progress.append({"message": message, "details": details})

    retry_result = {"ok": True, "result": {"text": "done"}}

    async def redo():
        return retry_result

    monkeypatch.setattr(external_catalog_rate_limits.asyncio, "sleep", fake_sleep)
    token = set_current_agent_context({"status_notifier": FakeNotifier()})
    try:
        result = await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
            record=_record(),
            envelope={
                "ok": False,
                "error": {
                    "kind": "rate_limited",
                    "retryable": True,
                    "raw": {"retry_after": "2"},
                },
            },
            redo=redo,
        )
    finally:
        reset_current_agent_context(token)

    assert result is retry_result
    assert sleeps == [3]
    assert progress and "Waiting 3 second(s)" in progress[0]["message"]
    assert retry_result["result"]["rate_limit_retry"]["wait_seconds"] == 3
    assert retry_result["result"]["rate_limit_retry"]["exhausted"] is False


@pytest.mark.asyncio
async def test_external_catalog_rate_limit_uses_provider_fallbacks(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def redo():
        return {"ok": True, "result": {"text": "done"}}

    monkeypatch.setattr(external_catalog_rate_limits.asyncio, "sleep", fake_sleep)

    await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
        record=SimpleNamespace(friendly_name="Slack", server_url="basil-local://slack"),
        envelope={"ok": False, "error": {"kind": "rate_limited", "retryable": True, "raw": {}}},
        redo=redo,
    )
    await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
        record=SimpleNamespace(friendly_name="Other", server_url="https://example.test/mcp"),
        envelope={"ok": False, "error": {"kind": "rate_limited", "retryable": True, "raw": {}}},
        redo=redo,
    )

    assert sleeps == [60, 30]


@pytest.mark.asyncio
async def test_external_catalog_rate_limit_exhaustion_records_metadata(monkeypatch):
    async def fake_sleep(_seconds):
        return None

    async def redo():
        return {
            "ok": False,
            "error": {
                "kind": "rate_limited",
                "retryable": True,
                "message": "Still limited.",
                "raw": {},
            },
        }

    monkeypatch.setattr(external_catalog_rate_limits.asyncio, "sleep", fake_sleep)

    result = await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
        record=SimpleNamespace(friendly_name="Slack", server_url="basil-local://slack"),
        envelope={"ok": False, "error": {"kind": "rate_limited", "retryable": True, "raw": {"retry_after": "1"}}},
        redo=redo,
    )

    retry = result["error"]["raw"]["rate_limit_retry"]
    assert retry["wait_seconds"] == 2
    assert retry["exhausted"] is True
    assert "retried once" in result["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["auth_expired", "permission_denied", "invalid_arguments", "not_found"])
async def test_external_catalog_rate_limit_helper_ignores_non_rate_limit_errors(kind):
    async def redo():
        raise AssertionError("redo should not run")

    result = await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
        record=_record(),
        envelope={"ok": False, "error": {"kind": kind, "retryable": True, "raw": {}}},
        redo=redo,
    )

    assert result is None


@pytest.mark.asyncio
async def test_external_catalog_rate_limit_coalesces_duplicate_progress_updates(monkeypatch):
    """Identical rate-limited retries in the same run emit one user-visible notice."""

    sleeps = []
    progress = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    class FakeNotifier:
        async def send_agent_progress_update(self, message, details=None):
            progress.append(message)

    async def redo():
        return {"ok": True, "result": {"text": "done"}}

    monkeypatch.setattr(external_catalog_rate_limits.asyncio, "sleep", fake_sleep)
    token = set_current_agent_context({"status_notifier": FakeNotifier()})
    try:
        record = _record()
        envelope = {
            "ok": False,
            "error": {
                "kind": "rate_limited",
                "retryable": True,
                "raw": {"retry_after": "30"},
            },
        }
        first = await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
            record=record,
            envelope=envelope,
            redo=redo,
            tool_name="search_messages",
        )
        second = await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
            record=record,
            envelope=envelope,
            redo=redo,
            tool_name="search_messages",
        )
    finally:
        reset_current_agent_context(token)

    assert first is not None and first.get("ok") is True
    assert second is not None and second.get("ok") is True
    assert sleeps == [31, 31]
    assert len(progress) == 1
    assert "Waiting 31 second(s)" in progress[0]


@pytest.mark.asyncio
async def test_external_catalog_rate_limit_emits_separate_progress_per_tool_and_provider(monkeypatch):
    """Different tool names or providers each get their own progress notice."""

    progress = []

    async def fake_sleep(_seconds):
        return None

    class FakeNotifier:
        async def send_agent_progress_update(self, message, details=None):
            progress.append(message)

    async def redo():
        return {"ok": True, "result": {"text": "done"}}

    monkeypatch.setattr(external_catalog_rate_limits.asyncio, "sleep", fake_sleep)
    token = set_current_agent_context({"status_notifier": FakeNotifier()})
    try:
        slack_record = SimpleNamespace(
            id="conn-slack",
            friendly_name="Slack",
            server_url="basil-local://slack",
        )
        linear_record = _record()
        envelope = {
            "ok": False,
            "error": {
                "kind": "rate_limited",
                "retryable": True,
                "raw": {"retry_after": "10"},
            },
        }

        await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
            record=slack_record,
            envelope=envelope,
            redo=redo,
            tool_name="slack_search_messages",
        )
        await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
            record=slack_record,
            envelope=envelope,
            redo=redo,
            tool_name="slack_list_channels",
        )
        await external_catalog_rate_limits.try_rate_limit_wait_and_retry(
            record=linear_record,
            envelope=envelope,
            redo=redo,
            tool_name="slack_search_messages",
        )
    finally:
        reset_current_agent_context(token)

    assert len(progress) == 3
    assert sum(1 for message in progress if message.startswith("Slack ")) == 2
    assert sum(1 for message in progress if message.startswith("Linear ")) == 1


@pytest.mark.asyncio
async def test_external_catalog_approval_uses_runtime_websocket_and_agent_task_id(monkeypatch):
    """Always-ask external tools should prompt through the active agent runtime."""

    calls = []

    class FakeExecutionApprovalService:
        def __init__(self, websocket_manager=None):
            self.websocket_manager = websocket_manager

        async def request_approval(self, command, context=None):
            calls.append(
                {
                    "websocket_manager": self.websocket_manager,
                    "command": command,
                    "context": context or {},
                }
            )
            return True, False, "exact"

    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.execution_approval_service.ExecutionApprovalService",
        FakeExecutionApprovalService,
    )

    websocket_manager = _FakeWebSocketManager()
    token = set_current_agent_context(
        {
            "websocket_manager": websocket_manager,
            "agent_task_id": "agent-task-123",
        }
    )
    try:
        approved = await external_catalog_approval.request_external_catalog_user_approval(
            _record(),
            "createIssue",
            {"title": "Fix approval routing"},
        )
    finally:
        reset_current_agent_context(token)

    assert approved is True
    assert len(calls) == 1
    assert calls[0]["websocket_manager"] is websocket_manager
    assert calls[0]["command"].startswith("mcp:Linear:createIssue(")
    assert calls[0]["context"]["source"] == "external_catalog"
    assert calls[0]["context"]["connection_id"] == "conn-123"
    assert calls[0]["context"]["friendly_name"] == "Linear"
    assert calls[0]["context"]["server_url"] == "https://linear.example/mcp"
    assert calls[0]["context"]["tool_name"] == "createIssue"
    assert calls[0]["context"]["arguments"] == {"title": "Fix approval routing"}
    assert calls[0]["context"]["agent_task_id"] == "agent-task-123"


@pytest.mark.asyncio
async def test_external_catalog_approval_fails_closed_without_websocket(monkeypatch):
    """Without an interactive runtime, approval-required external tools remain denied."""

    calls = []

    class FakeExecutionApprovalService:
        def __init__(self, websocket_manager=None):
            self.websocket_manager = websocket_manager

        async def request_approval(self, command, context=None):
            calls.append(
                {
                    "websocket_manager": self.websocket_manager,
                    "command": command,
                    "context": context or {},
                }
            )
            return bool(self.websocket_manager), False, "exact"

    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.execution_approval_service.ExecutionApprovalService",
        FakeExecutionApprovalService,
    )

    token = set_current_agent_context({"agent_task_id": "agent-task-456"})
    try:
        approved = await external_catalog_approval.request_external_catalog_user_approval(
            _record(),
            "deleteIssue",
            {"id": "ISSUE-1"},
        )
    finally:
        reset_current_agent_context(token)

    assert approved is False
    assert len(calls) == 1
    assert calls[0]["websocket_manager"] is None
    assert calls[0]["context"]["agent_task_id"] == "agent-task-456"
