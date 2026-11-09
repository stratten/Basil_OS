"""Tests that remembering a connected-tool approval sets that one tool's policy, never a command pattern."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.dependencies as dependencies_module
from api.core.models.preference_models.execution_and_connections import MCPCachedTool, MCPConnectionRecord
from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.routes.agent_tasks.execution_approval_routes import process_approval_decision
from api.routes.agent_tasks.execution_models import ApprovalDecisionRequest
from api.services.agent_processing.tools.safety.approval_presentation import (
    approval_presentation_fields,
    record_whitelist_eligibility,
)
from api.services.agent_processing.tools.external_services.external_catalog.approval import request_external_catalog_user_approval
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
from api.services.mcp_connectors.mcp_client_service import tool_catalog_entry
from api.services.agent_processing.tools.safety.connected_tool_remember import (
    build_tool_policy_scope,
    is_destructive_tool_name,
    normalize_tool_policy_scope,
    remember_always_allow,
    server_marks_tool_destructive,
    tool_policy_scope_of_record,
)


def _command(connection: str, tool: str, arguments: dict) -> str:
    return f"mcp:{connection}:{tool}({json.dumps(arguments, separators=(',', ':'))})"


class _Preferences:
    def __init__(self, record: MCPConnectionRecord | None) -> None:
        connections = [record] if record is not None else []
        self.preferences = SimpleNamespace(connections=SimpleNamespace(mcp_connections=connections))
        self.saves = 0

    def load(self) -> SimpleNamespace:
        return self.preferences

    def save(self, preferences: SimpleNamespace) -> None:
        self.preferences = preferences
        self.saves += 1


@pytest.fixture
def gmail() -> MCPConnectionRecord:
    return MCPConnectionRecord(
        id="conn-gmail",
        friendly_name="Gmail",
        server_url="basil-local://gmail",
        cached_tools=[MCPCachedTool(name="label_message"), MCPCachedTool(name="trash_message")],
        tool_policies={"trash_message": "always_ask"},
    )


def _install(monkeypatch: pytest.MonkeyPatch, record: MCPConnectionRecord | None) -> _Preferences:
    store = _Preferences(record)
    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", store.load)
    monkeypatch.setattr("api.core.preferences.preferences_io.save_preferences", store.save)
    return store


def _durable_record(connection_id: str = "conn-gmail", tool_name: str = "label_message", destructive: bool = False) -> dict:
    command = _command("Gmail", tool_name, {"messageId": "AAA"})
    scope = build_tool_policy_scope(connection_id, "Gmail", tool_name)
    scope["destructive"] = destructive
    return {
        "id": "approval-1",
        "command": command,
        "generalized_pattern": command,
        "execution_type": "shell",
        "status": "approved",
        "render_context": {"whitelist": {"eligible": True, "reason": "", "advice": None, "pattern": "", "broad": False, "tool_policy": scope}},
    }


class _FakeApprovalService:
    def __init__(self) -> None:
        self.whitelisted: list[dict] = []

    async def handle_approval_response(self, **kwargs) -> None:
        return None

    async def add_to_whitelist(self, **kwargs):
        self.whitelisted.append(kwargs)
        return SimpleNamespace(id="pattern-1")


def _install_durable_record(monkeypatch: pytest.MonkeyPatch, record: dict | None) -> None:
    get_approval = AsyncMock(return_value=record)
    knowledge_service = SimpleNamespace(execution_approval_repository=SimpleNamespace(get_approval=get_approval))
    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: knowledge_service)


def _decision(**overrides) -> ApprovalDecisionRequest:
    values = {
        "approval_id": "approval-1",
        "command": "client echoed text that must be ignored",
        "approved": True,
        "remember_choice": True,
        "pattern_type": "exact",
        "agent_task_id": "task-1",
    }
    values.update(overrides)
    return ApprovalDecisionRequest(**values)


@pytest.mark.parametrize(
    "tool_name",
    ["trash_thread", "trash_message", "delete_event", "remove_label", "send_message", "sendMessage", "speakeasy_delete_request", "publish_page", "post_message", "drop_table", "purge-cache"],
)
def test_tools_that_delete_or_send_are_marked_destructive(tool_name: str) -> None:
    assert is_destructive_tool_name(tool_name) is True


@pytest.mark.parametrize(
    "tool_name",
    ["label_message", "untrash_message", "untrash_thread", "speakeasy_create_request", "list_messages", "search_threads", "create_draft", "", "postscript_lookup"],
)
def test_other_tools_are_not_marked_destructive(tool_name: str) -> None:
    assert is_destructive_tool_name(tool_name) is False


def test_scope_requires_a_connection_id_and_a_tool_name() -> None:
    assert normalize_tool_policy_scope({"connection_id": "c", "tool_name": "t"}) == {
        "connection_id": "c",
        "connection_name": "",
        "tool_name": "t",
        "destructive": False,
    }
    for broken in (None, "x", {}, {"connection_id": "c"}, {"tool_name": "t"}, {"connection_id": " ", "tool_name": "t"}, {"connection_id": "c", "tool_name": ""}):
        assert normalize_tool_policy_scope(broken) is None


def test_a_connected_tool_card_offers_remember_without_a_command_pattern() -> None:
    command = _command("Gmail", "trash_message", {"messageId": "AAA"})
    scope = build_tool_policy_scope("conn-gmail", "Gmail", "trash_message")

    fields = approval_presentation_fields(command, command, {"remember_tool_policy": scope, "purpose": "Moves one message to Trash."})

    assert fields["whitelist"] == {"eligible": True, "reason": "", "advice": None, "pattern": "", "broad": False, "tool_policy": scope}
    assert fields["whitelist"]["tool_policy"]["destructive"] is True


def test_a_connected_tool_card_without_a_scope_cannot_be_remembered() -> None:
    command = _command("Gmail", "label_message", {"messageId": "AAA"})

    fields = approval_presentation_fields(command, command, {})

    assert fields["whitelist"]["eligible"] is False
    assert "tool_policy" not in fields["whitelist"]


def test_the_persisted_scope_decides_eligibility_when_the_decision_arrives() -> None:
    assert record_whitelist_eligibility(_durable_record()).eligible is True
    plain = {"command": _command("Gmail", "label_message", {}), "generalized_pattern": "mcp:Gmail", "execution_type": "shell"}
    assert record_whitelist_eligibility(plain).eligible is False
    assert tool_policy_scope_of_record(plain) is None


def test_remember_sets_only_that_tool_to_always_allow(monkeypatch: pytest.MonkeyPatch, gmail: MCPConnectionRecord) -> None:
    store = _install(monkeypatch, gmail)

    message = remember_always_allow(build_tool_policy_scope("conn-gmail", "Gmail", "label_message"))

    assert gmail.tool_policies == {"trash_message": "always_ask", "label_message": "always_allow"}
    assert store.saves == 1
    assert "label_message" in message and "Gmail" in message and "Settings → Connections" in message


def test_remember_never_overrides_never_allow(monkeypatch: pytest.MonkeyPatch, gmail: MCPConnectionRecord) -> None:
    gmail.tool_policies["label_message"] = "never_allow"
    store = _install(monkeypatch, gmail)

    with pytest.raises(ValueError, match="Never allow"):
        remember_always_allow(build_tool_policy_scope("conn-gmail", "Gmail", "label_message"))

    assert gmail.tool_policies["label_message"] == "never_allow"
    assert store.saves == 0


def test_remember_for_a_deleted_connection_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install(monkeypatch, None)

    with pytest.raises(ValueError, match="no longer exists"):
        remember_always_allow(build_tool_policy_scope("conn-gone", "Gmail", "label_message"))

    assert store.saves == 0


@pytest.mark.asyncio
async def test_the_route_sets_the_tool_policy_and_never_stores_a_pattern(monkeypatch: pytest.MonkeyPatch, gmail: MCPConnectionRecord) -> None:
    _install(monkeypatch, gmail)
    _install_durable_record(monkeypatch, _durable_record())
    service = _FakeApprovalService()

    response = await process_approval_decision(request=_decision(), approval_service=service)

    assert response.success is True
    assert response.pattern_id is None
    assert service.whitelisted == []
    assert gmail.tool_policies["label_message"] == "always_allow"
    assert gmail.tool_policies["trash_message"] == "always_ask"
    assert "Settings → Connections" in response.message


@pytest.mark.asyncio
async def test_the_route_ignores_a_remember_request_that_was_not_ticked(monkeypatch: pytest.MonkeyPatch, gmail: MCPConnectionRecord) -> None:
    store = _install(monkeypatch, gmail)
    _install_durable_record(monkeypatch, _durable_record())
    service = _FakeApprovalService()

    response = await process_approval_decision(request=_decision(remember_choice=False), approval_service=service)

    assert response.message == "Command approved for this execution"
    assert store.saves == 0
    assert "label_message" not in gmail.tool_policies


@pytest.mark.asyncio
async def test_a_denied_connected_tool_is_never_remembered(monkeypatch: pytest.MonkeyPatch, gmail: MCPConnectionRecord) -> None:
    store = _install(monkeypatch, gmail)
    _install_durable_record(monkeypatch, _durable_record())
    service = _FakeApprovalService()

    response = await process_approval_decision(request=_decision(approved=False), approval_service=service)

    assert response.message == "Command denied"
    assert store.saves == 0
    assert service.whitelisted == []


@pytest.mark.asyncio
async def test_the_route_reads_the_scope_from_the_durable_record_not_the_request(monkeypatch: pytest.MonkeyPatch, gmail: MCPConnectionRecord) -> None:
    _install(monkeypatch, gmail)
    _install_durable_record(monkeypatch, _durable_record(tool_name="label_message"))
    service = _FakeApprovalService()

    await process_approval_decision(
        request=_decision(command=_command("Gmail", "trash_message", {}), description="trash_message"),
        approval_service=service,
    )

    assert gmail.tool_policies["trash_message"] == "always_ask"
    assert gmail.tool_policies["label_message"] == "always_allow"


@pytest.mark.asyncio
async def test_a_blocked_policy_change_still_approves_this_one_call(monkeypatch: pytest.MonkeyPatch, gmail: MCPConnectionRecord) -> None:
    gmail.tool_policies["label_message"] = "never_allow"
    _install(monkeypatch, gmail)
    _install_durable_record(monkeypatch, _durable_record())
    service = _FakeApprovalService()

    response = await process_approval_decision(request=_decision(), approval_service=service)

    assert response.success is True
    assert response.message.startswith("Command approved for this execution only.")
    assert "Never allow" in response.message
    assert service.whitelisted == []
    assert gmail.tool_policies["label_message"] == "never_allow"


def _use_whitelist_only_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = ToolExecutionSettings(
        approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
        whitelisted_commands=[],
        auto_approve_read_only=False,
        safe_execution_mode=False,
    )
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.approval_override.load_preferences",
        lambda: SimpleNamespace(tool_execution=settings),
    )


@pytest.mark.asyncio
async def test_a_connected_tool_card_says_the_tool_is_set_to_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_whitelist_only_settings(monkeypatch)

    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command(_command("Gmail", "label_message", {"id": "1"}), {})

    assert decision.needs_approval is True
    assert decision.reason == "This tool is set to ask before it runs"


@pytest.mark.asyncio
async def test_an_ordinary_command_keeps_the_whitelist_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_whitelist_only_settings(monkeypatch)

    decision = await ExecutionApprovalService(websocket_manager=None).evaluate_command("cat /etc/hosts", {})

    assert decision.needs_approval is True
    assert decision.reason == "Command not in whitelist"


def _server_tool(name: str, *, annotations=None) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=None, inputSchema={}, annotations=annotations)


def test_the_catalog_keeps_a_server_declared_destructive_hint() -> None:
    declared = tool_catalog_entry(_server_tool("tidy", annotations=SimpleNamespace(readOnlyHint=False, destructiveHint=True)))
    declared_safe = tool_catalog_entry(_server_tool("tidy", annotations=SimpleNamespace(readOnlyHint=False, destructiveHint=False)))

    assert declared["is_destructive_hint"] is True
    assert declared_safe["is_destructive_hint"] is False


def test_the_catalog_records_no_hint_as_unknown_not_false() -> None:
    no_annotations = tool_catalog_entry(_server_tool("tidy"))
    no_destructive_field = tool_catalog_entry(_server_tool("tidy", annotations=SimpleNamespace(readOnlyHint=True)))
    not_a_boolean = tool_catalog_entry(_server_tool("tidy", annotations=SimpleNamespace(destructiveHint="yes")))

    assert no_annotations["is_destructive_hint"] is None
    assert no_destructive_field["is_destructive_hint"] is None
    assert no_destructive_field["is_read_only_hint"] is True
    assert not_a_boolean["is_destructive_hint"] is None


def _connection_with(*tools: MCPCachedTool) -> MCPConnectionRecord:
    return MCPConnectionRecord(friendly_name="Notes", server_url="https://notes.example/mcp", cached_tools=list(tools))


def test_a_server_declared_destructive_tool_is_marked_whatever_its_name() -> None:
    record = _connection_with(MCPCachedTool(name="tidy_up", is_destructive_hint=True))

    assert server_marks_tool_destructive(record, "tidy_up") is True
    assert build_tool_policy_scope(record.id, "Notes", "tidy_up", server_marked_destructive=True)["destructive"] is True


def test_a_missing_false_or_contradicted_hint_does_not_mark_a_tool() -> None:
    record = _connection_with(
        MCPCachedTool(name="undeclared"),
        MCPCachedTool(name="declared_safe", is_destructive_hint=False),
        MCPCachedTool(name="contradicted", is_destructive_hint=True, is_read_only_hint=True),
    )

    assert server_marks_tool_destructive(record, "undeclared") is False
    assert server_marks_tool_destructive(record, "declared_safe") is False
    assert server_marks_tool_destructive(record, "contradicted") is False
    assert server_marks_tool_destructive(record, "not_in_the_catalog") is False


def test_the_name_rule_still_applies_when_the_server_declares_nothing() -> None:
    record = _connection_with(MCPCachedTool(name="trash_thread"))

    assert build_tool_policy_scope(record.id, "Notes", "trash_thread", server_marked_destructive=False)["destructive"] is True
    assert build_tool_policy_scope(record.id, "Notes", "label_thread")["destructive"] is False


class _CapturingApprovalService:
    contexts: list = []

    def __init__(self, websocket_manager=None) -> None:
        pass

    async def request_approval(self, command, context=None):
        type(self).contexts.append(context)
        return True, False, "none"


@pytest.mark.asyncio
async def test_the_approval_call_carries_the_server_destructive_marking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.execution_approval_service.ExecutionApprovalService",
        _CapturingApprovalService,
    )
    _CapturingApprovalService.contexts = []
    record = _connection_with(MCPCachedTool(name="tidy_up", is_destructive_hint=True), MCPCachedTool(name="peek"))

    await request_external_catalog_user_approval(record, "tidy_up", {"folder": "a"}, purpose="Clean up")
    await request_external_catalog_user_approval(record, "peek", {"folder": "a"}, purpose="Look")

    flagged, plain = (context["remember_tool_policy"] for context in _CapturingApprovalService.contexts)
    assert flagged["destructive"] is True
    assert plain["destructive"] is False
