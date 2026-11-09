"""Every approval card says what the user is approving.

The shared approval service marks a card that has no explanation, connected-tool calls must carry the agent's explanation to the card without sending it to the remote tool, and the cards Basil raises itself carry Basil's own labeled sentence.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from api.routes.agent_tasks import provider_interaction_routes
from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import normalize_interaction_presentation
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app import gmail_ui_approval
from api.services.agent_processing.tools.external_services import external_catalog_tool
from api.services.agent_processing.tools.external_services.external_catalog import actions as external_catalog_actions
from api.services.agent_processing.tools.external_services.external_catalog import approval as external_catalog_approval
from api.services.agent_processing.tools.external_services.external_catalog import connect as external_catalog_connect
from api.services.agent_processing.tools.external_services.external_catalog import envelopes as external_catalog_envelopes
from api.services.agent_processing.tools.safety import execution_approval_service
from api.services.agent_processing.tools.safety.approval_presentation import approval_presentation_fields
from api.services.agent_processing.tools.safety.explanation_gate import (
    EXPLANATION_REQUIRED_STATUS,
    should_request_explanation,
)
from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome
from api.services.mcp_connectors.connection_setup_plan import ConnectionSetupPlan


# --- The shared presentation rule -------------------------------------------------------------------------------


def test_a_card_with_no_explanation_is_marked_even_when_its_caller_never_asked_for_one() -> None:
    fields = approval_presentation_fields("some-command --flag", "some-command", {"source": "future_caller"})

    assert fields["purpose_missing"] is True
    assert "purpose" not in fields
    assert "purpose_source" not in fields


def test_a_blank_explanation_counts_as_missing() -> None:
    fields = approval_presentation_fields("some-command", "some-command", {"purpose": "   \n  "})

    assert fields["purpose_missing"] is True
    assert "purpose" not in fields


def test_an_explanation_without_a_source_is_the_agents() -> None:
    fields = approval_presentation_fields("ls", "ls", {"purpose": "Lists the folder.", "purpose_required": True})

    assert fields["purpose"] == "Lists the folder."
    assert fields["purpose_source"] == "agent"
    assert "purpose_missing" not in fields


def test_an_explanation_basil_composed_is_labeled_as_basils() -> None:
    fields = approval_presentation_fields("connect-mcp-server", "connect-mcp-server", {"purpose": "Connect Example.", "purpose_source": "basil"})

    assert fields["purpose_source"] == "basil"


@pytest.mark.parametrize("claimed_source", ["system", "", None, 7, "BASIL"])
def test_an_unknown_source_falls_back_to_the_agent(claimed_source: Any) -> None:
    fields = approval_presentation_fields("ls", "ls", {"purpose": "Lists the folder.", "purpose_source": claimed_source})

    assert fields["purpose_source"] == "agent"


def test_a_source_with_no_explanation_adds_nothing_to_the_card() -> None:
    fields = approval_presentation_fields("ls", "ls", {"purpose_source": "basil"})

    assert fields["purpose_missing"] is True
    assert "purpose_source" not in fields


# --- The recorded timeline entry and the recovered pending approval ---------------------------------------------


def test_the_timeline_keeps_the_source_of_an_explanation_it_records() -> None:
    assert normalize_interaction_presentation({"purpose": " Runs it. ", "purpose_source": "basil"}) == {"purpose": "Runs it.", "purpose_source": "basil"}
    assert normalize_interaction_presentation({"purpose": "Runs it.", "purpose_source": "agent"}) == {"purpose": "Runs it.", "purpose_source": "agent"}


def test_the_timeline_drops_a_source_it_does_not_know_or_that_has_no_explanation() -> None:
    assert normalize_interaction_presentation({"purpose": "Runs it.", "purpose_source": "system"}) == {"purpose": "Runs it."}
    assert normalize_interaction_presentation({"purpose_source": "basil", "purpose_missing": True}) == {"purpose_missing": True}


def test_a_recovered_pending_approval_carries_the_source_of_its_explanation() -> None:
    assert "purpose_source" in provider_interaction_routes._APPROVAL_PRESENTATION_KEYS


# --- The explanation gate, for a connected-tool shaped approval -------------------------------------------------


def _connected_tool_context(**overrides: Any) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "source": "external_catalog",
        "tool_name": "speakeasy_create_request",
        "arguments": {"organizationId": "org-1"},
        "purpose": None,
        "purpose_required": True,
        "agent_task_id": "task-gate-1",
    }
    context.update(overrides)
    return context


def test_the_agent_is_asked_once_to_explain_a_connected_tool_call_and_then_the_card_is_shown() -> None:
    command = 'mcp:Speakeasy:speakeasy_create_request({"organizationId":"org-1"})'

    assert should_request_explanation(command, _connected_tool_context()) is True
    assert should_request_explanation(command, _connected_tool_context()) is False


def test_a_connected_tool_call_that_explains_itself_is_never_sent_back() -> None:
    command = 'mcp:Speakeasy:speakeasy_create_request({"organizationId":"org-2"})'

    assert should_request_explanation(command, _connected_tool_context(purpose="Creates a request in Speakeasy.", agent_task_id="task-gate-2")) is False


# --- The connected-tool approval ---------------------------------------------------------------------------------


class _RecordingApprovalService:
    answer = (True, False, "exact")
    seen: List[Dict[str, Any]] = []

    def __init__(self, websocket_manager: Any = None) -> None:
        self.websocket_manager = websocket_manager

    async def request_approval(self, command: str, context: Dict[str, Any] | None = None):
        _RecordingApprovalService.seen.append({"command": command, "context": dict(context or {})})
        return _RecordingApprovalService.answer


@pytest.fixture
def recording_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(execution_approval_service, "ExecutionApprovalService", _RecordingApprovalService)
    _RecordingApprovalService.seen = []
    _RecordingApprovalService.answer = (True, False, "exact")
    return _RecordingApprovalService


def _record() -> SimpleNamespace:
    return SimpleNamespace(id="conn-1", friendly_name="Speakeasy", server_url="https://speakeasy.example/mcp")


@pytest.mark.asyncio
async def test_the_agents_explanation_reaches_the_connected_tool_card_and_the_explanation_is_required(recording_service) -> None:
    approved = await external_catalog_approval.request_external_catalog_user_approval(
        _record(), "speakeasy_create_request", {"organizationId": "org-1"}, purpose="Creates the request you asked for."
    )

    context = recording_service.seen[0]["context"]
    assert approved is True
    assert context["purpose"] == "Creates the request you asked for."
    assert context["purpose_required"] is True
    assert "purpose_source" not in context


@pytest.mark.asyncio
async def test_a_connected_tool_approval_carries_the_one_tool_scope_that_remember_would_change(recording_service) -> None:
    await external_catalog_approval.request_external_catalog_user_approval(_record(), "speakeasy_delete_request", {"id": "1"}, purpose="Deletes it.")
    await external_catalog_approval.request_external_catalog_user_approval(_record(), "speakeasy_create_request", {"organizationId": "org-1"}, purpose="Creates it.")

    delete_scope, create_scope = (entry["context"]["remember_tool_policy"] for entry in recording_service.seen)
    assert delete_scope == {"connection_id": "conn-1", "connection_name": "Speakeasy", "tool_name": "speakeasy_delete_request", "destructive": True}
    assert create_scope == {"connection_id": "conn-1", "connection_name": "Speakeasy", "tool_name": "speakeasy_create_request", "destructive": False}


@pytest.mark.asyncio
async def test_a_connected_tool_approval_without_an_explanation_still_asks_for_one(recording_service) -> None:
    approved = await external_catalog_approval.request_external_catalog_user_approval(_record(), "speakeasy_create_request", {"organizationId": "org-1"})

    context = recording_service.seen[0]["context"]
    assert approved is True
    assert context["purpose"] is None
    assert context["purpose_required"] is True


@pytest.mark.asyncio
async def test_a_request_for_an_explanation_is_signaled_and_is_not_a_denial(recording_service) -> None:
    recording_service.answer = (False, False, EXPLANATION_REQUIRED_STATUS)

    with pytest.raises(external_catalog_approval.ExplanationRequired):
        await external_catalog_approval.request_external_catalog_user_approval(_record(), "speakeasy_create_request", {})


@pytest.mark.asyncio
async def test_a_denial_is_still_a_plain_false(recording_service) -> None:
    recording_service.answer = (False, False, "exact")

    assert await external_catalog_approval.request_external_catalog_user_approval(_record(), "speakeasy_create_request", {}, purpose="Creates it.") is False


@pytest.mark.asyncio
async def test_a_failing_approval_flow_is_still_a_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Raising:
        def __init__(self, websocket_manager: Any = None) -> None:
            pass

        async def request_approval(self, command: str, context: Dict[str, Any] | None = None):
            raise RuntimeError("socket closed")

    monkeypatch.setattr(execution_approval_service, "ExecutionApprovalService", _Raising)

    assert await external_catalog_approval.request_external_catalog_user_approval(_record(), "speakeasy_create_request", {}, purpose="Creates it.") is False


# --- Dispatching a connected-tool call ---------------------------------------------------------------------------


def _install_dispatch(monkeypatch: pytest.MonkeyPatch, approval) -> Dict[str, List[Any]]:
    record = SimpleNamespace(
        id="speakeasy",
        friendly_name="Speakeasy",
        description=None,
        server_url="https://speakeasy.example/mcp",
        enabled=True,
        cached_tools=[],
        tool_policies={"speakeasy_create_request": "always_ask"},
        last_connection_status="connected",
    )
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))
    seen: Dict[str, List[Any]] = {"approval": [], "remote": [], "audit": []}

    async def fake_approval(record_arg, tool_name, arguments, purpose=None):
        seen["approval"].append({"tool_name": tool_name, "arguments": dict(arguments), "purpose": purpose})
        return await approval(purpose)

    async def fake_audit(**kwargs):
        seen["audit"].append(kwargs)

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="tok")

    async def no_guard(*args, **kwargs):
        return None

    async def fake_attribution(record_arg, tool_name, arguments, **kwargs):
        return arguments, None

    class FakeClient:
        async def call_tool(self, server_url, tool_name, arguments, access_token):
            seen["remote"].append((tool_name, dict(arguments)))
            return {"ok": True, "result": {}}

    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)
    monkeypatch.setattr(external_catalog_actions, "request_external_catalog_user_approval", fake_approval)
    monkeypatch.setattr(external_catalog_actions, "record_external_catalog_audit", fake_audit)
    monkeypatch.setattr(external_catalog_actions, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(external_catalog_actions, "ensure_tool_schema_surfaced", no_guard)
    monkeypatch.setattr(external_catalog_actions, "check_restoration_attribution", fake_attribution)
    monkeypatch.setattr(external_catalog_actions, "check_voice_guidance", no_guard)
    monkeypatch.setattr(external_catalog_actions, "get_external_catalog_mcp_client", lambda: FakeClient())
    return seen


@pytest.mark.asyncio
async def test_a_call_that_needs_an_explanation_is_sent_back_to_the_agent_before_anything_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def asks_for_explanation(purpose):
        raise external_catalog_approval.ExplanationRequired()

    seen = _install_dispatch(monkeypatch, asks_for_explanation)

    envelope = await external_catalog_actions.call_external_catalog_tool("speakeasy", "speakeasy_create_request", {"organizationId": "org-1"})

    assert envelope["ok"] is False
    assert envelope["error"]["kind"] == "explanation_required"
    assert envelope["error"]["retryable"] is True
    assert "`purpose`" in envelope["error"]["message"]
    assert "nothing was denied" in envelope["error"]["message"]
    assert seen["remote"] == []
    assert seen["audit"] == []


@pytest.mark.asyncio
async def test_the_explanation_is_given_to_the_card_and_never_sent_to_the_remote_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def approves(purpose):
        return True

    seen = _install_dispatch(monkeypatch, approves)

    envelope = await external_catalog_actions.call_external_catalog_tool(
        "speakeasy", "speakeasy_create_request", {"organizationId": "org-1"}, purpose="Creates the request you asked for."
    )

    assert envelope["ok"] is True
    assert seen["approval"][0]["purpose"] == "Creates the request you asked for."
    assert seen["approval"][0]["arguments"] == {"organizationId": "org-1"}
    assert seen["remote"] == [("speakeasy_create_request", {"organizationId": "org-1"})]


@pytest.mark.asyncio
async def test_a_denied_call_is_still_refused_and_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    async def denies(purpose):
        return False

    seen = _install_dispatch(monkeypatch, denies)

    envelope = await external_catalog_actions.call_external_catalog_tool("speakeasy", "speakeasy_create_request", {}, purpose="Creates it.")

    assert envelope["error"]["kind"] == "permission_denied"
    assert seen["remote"] == []
    assert [entry["classification"] for entry in seen["audit"]] == ["denied"]


@pytest.mark.asyncio
async def test_a_tool_that_needs_no_approval_is_never_asked_to_explain(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_be_asked(purpose):
        raise AssertionError("an always_allow tool must not reach the approval card")

    seen = _install_dispatch(monkeypatch, must_not_be_asked)
    prefs = external_catalog_actions.load_external_catalog_preferences()
    prefs.connections.mcp_connections[0].tool_policies = {"speakeasy_create_request": "always_allow"}

    envelope = await external_catalog_actions.call_external_catalog_tool("speakeasy", "speakeasy_create_request", {"organizationId": "org-1"})

    assert envelope["ok"] is True
    assert seen["approval"] == []


# --- The tool the agent calls ------------------------------------------------------------------------------------


def test_the_tool_accepts_purpose_beside_arguments_and_not_inside_them() -> None:
    tool = external_catalog_tool.create_external_catalog_tool()
    field = tool.args_schema.model_fields["purpose"]

    assert field.default is None
    assert "beside arguments, never inside them" in field.description
    assert "purpose" not in tool.args_schema.model_fields["arguments"].description


@pytest.mark.asyncio
async def test_the_purpose_is_handed_to_the_dispatcher_and_is_not_added_to_the_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []

    async def fake_call_tool(connection_id, tool_name, arguments, purpose=None):
        calls.append({"connection_id": connection_id, "tool_name": tool_name, "arguments": dict(arguments), "purpose": purpose})
        return {"ok": True}

    monkeypatch.setattr(external_catalog_tool, "_call_tool", fake_call_tool)

    raw = await external_catalog_tool._external_catalog_impl(
        action="call_tool",
        connection_id="speakeasy",
        tool_name="speakeasy_create_request",
        arguments={"organizationId": "org-1"},
        purpose="Creates the request you asked for.",
    )

    assert json.loads(raw) == {"ok": True}
    assert calls == [
        {
            "connection_id": "speakeasy",
            "tool_name": "speakeasy_create_request",
            "arguments": {"organizationId": "org-1"},
            "purpose": "Creates the request you asked for.",
        }
    ]


@pytest.mark.asyncio
async def test_a_remote_tool_with_its_own_purpose_parameter_keeps_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []

    async def fake_call_tool(connection_id, tool_name, arguments, purpose=None):
        calls.append({"arguments": dict(arguments), "purpose": purpose})
        return {"ok": True}

    monkeypatch.setattr(external_catalog_tool, "_call_tool", fake_call_tool)

    await external_catalog_tool._external_catalog_impl(
        action="call_tool",
        connection_id="crm",
        tool_name="log_call",
        arguments={"purpose": "sales follow-up"},
        purpose="Logs the call you just made.",
    )

    assert calls == [{"arguments": {"purpose": "sales follow-up"}, "purpose": "Logs the call you just made."}]


def test_the_explanation_envelope_tells_the_agent_exactly_how_to_repeat_the_call() -> None:
    envelope = external_catalog_envelopes.make_external_catalog_explanation_required("speakeasy_create_request")
    message = envelope["error"]["message"]

    assert envelope["ok"] is False
    assert envelope["error"]["kind"] == "explanation_required"
    assert "'speakeasy_create_request'" in message
    assert "same connection_id, tool_name and arguments" in message
    assert "not inside arguments" in message
    assert envelope["error"]["raw"] == {"tool_name": "speakeasy_create_request"}


# --- Cards Basil raises itself -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_connect_card_carries_basils_explanation(recording_service) -> None:
    plan = ConnectionSetupPlan(server_url="https://mcp.example.com/mcp", friendly_name="Example", flow="oauth", connector_id="example")

    approved = await external_catalog_connect.request_connection_setup_approval(plan)

    context = recording_service.seen[0]["context"]
    assert approved is True
    assert context["purpose"].startswith("Connect Example at https://mcp.example.com/mcp.")
    assert context["purpose_source"] == "basil"


class _MailApprovalService:
    def __init__(self) -> None:
        self.seen: List[Dict[str, Any]] = []

    async def request_approval_with_outcome(self, command: str, context: Dict[str, Any] | None = None) -> ExecutionApprovalOutcome:
        self.seen.append({"command": command, "context": dict(context or {})})
        return ExecutionApprovalOutcome(approved=True)


def _mail_summary(count: int = 2, subjects: List[str] | None = None) -> Dict[str, Any]:
    return {
        "operation": "archive",
        "message_count": count,
        "accounts": ["me@example.com"],
        "subjects": subjects if subjects is not None else ["Quarterly report"],
        "target_mailboxes": [],
    }


@pytest.mark.asyncio
async def test_the_mail_takeover_card_carries_basils_explanation() -> None:
    service = _MailApprovalService()
    token = set_current_agent_context({"agent_task_id": "task-mail-1"})
    try:
        approved, reason = await gmail_ui_approval.request_mail_ui_approval(service, _mail_summary())
    finally:
        reset_current_agent_context(token)

    context = service.seen[0]["context"]
    assert (approved, reason) == (True, "")
    assert context["purpose_source"] == "basil"
    assert context["purpose"] == gmail_ui_approval.build_approval_purpose(_mail_summary())
    assert "archive 2 Gmail messages" in context["purpose"]
    assert "roughly 20 seconds" in context["purpose"]
    assert context["description"] == gmail_ui_approval.build_approval_description(_mail_summary())


def test_the_mail_explanation_is_singular_for_one_message_and_never_depends_on_subject_text() -> None:
    one = gmail_ui_approval.build_approval_purpose(_mail_summary(count=1))
    long_subjects = gmail_ui_approval.build_approval_purpose(_mail_summary(count=1, subjects=["x" * 5000]))

    assert "archive 1 Gmail message." in one
    assert one == long_subjects
    assert len(one) < 1000
