"""A Gmail restoration tool may only undo a change Basil made, so the agent does not reverse the user's own mailbox edits.

The attribution lookup runs against a real SQLite ``mcp_call_log`` so the JSON-path query is exercised, not mocked.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.mcp.call_log_repository import MCPCallLogRepository
from api.services.agent_processing.tools.external_services.external_catalog import actions as external_catalog_actions
from api.services.agent_processing.tools.external_services.external_catalog.undo_attribution import check_restoration_attribution

GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"
BASE_TIME = datetime(2026, 10, 28, 12, 0, 0)


@pytest.fixture
def repo(tmp_path):
    path = str(tmp_path / "calls.db")
    connection = sqlite3.connect(path)
    for statement in get_schema_statements():
        if "mcp_call_log" in statement.lower():
            connection.execute(statement)
    connection.commit()
    connection.close()
    return MCPCallLogRepository(path)


def _record(server_url: str = GMAIL_URL):
    return SimpleNamespace(id="gmail", friendly_name="Gmail", server_url=server_url)


class _Clock:
    def __init__(self):
        self.step = 0

    def next(self) -> datetime:
        self.step += 1
        return BASE_TIME + timedelta(seconds=self.step)


def _log(repo, clock, tool_name, arguments, classification="success", agent_task_id="task-1", connection_id="gmail"):
    started = clock.next()
    asyncio.run(
        repo.record_call(
            connection_id=connection_id,
            server_url=GMAIL_URL,
            tool_name=tool_name,
            arguments=arguments,
            result_classification=classification,
            started_at=started,
            completed_at=started,
            agent_task_id=agent_task_id,
        )
    )


def _check(repo, tool_name, arguments, record=None, agent_task_id="task-1"):
    return asyncio.run(
        check_restoration_attribution(record or _record(), tool_name, arguments, agent_task_id=agent_task_id, repo=repo)
    )


def test_undoing_a_trash_basil_made_is_allowed(repo):
    clock = _Clock()
    _log(repo, clock, "trash_thread", {"threadId": "t1"})

    arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"})

    assert refusal is None
    assert arguments == {"threadId": "t1"}


def test_a_change_basil_never_made_is_refused_with_a_final_not_attributed_error(repo):
    arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"})

    assert refusal["ok"] is False
    assert refusal["error"]["kind"] == "not_attributed"
    assert refusal["error"]["retryable"] is False
    assert "userRequested" in refusal["error"]["message"]
    assert arguments == {"threadId": "t1"}


def test_a_trash_of_a_different_thread_does_not_attribute_this_one(repo):
    clock = _Clock()
    _log(repo, clock, "trash_thread", {"threadId": "other"})

    _arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"})

    assert refusal is not None


def test_a_failed_or_denied_forward_call_is_not_a_change_basil_made(repo):
    clock = _Clock()
    _log(repo, clock, "trash_thread", {"threadId": "t1"}, classification="error")
    _log(repo, clock, "trash_thread", {"threadId": "t1"}, classification="denied")

    _arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"})

    assert refusal is not None


def test_a_change_basil_already_reversed_is_not_basils_to_reverse_again(repo):
    clock = _Clock()
    _log(repo, clock, "trash_thread", {"threadId": "t1"})
    _log(repo, clock, "untrash_thread", {"threadId": "t1"})

    _arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"})

    assert refusal is not None


def test_a_second_trash_after_a_restore_is_attributed_again(repo):
    clock = _Clock()
    _log(repo, clock, "trash_thread", {"threadId": "t1"})
    _log(repo, clock, "untrash_thread", {"threadId": "t1"})
    _log(repo, clock, "trash_thread", {"threadId": "t1"})

    _arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"})

    assert refusal is None


def test_the_sensitive_label_tools_count_only_with_the_matching_label_option(repo):
    clock = _Clock()
    _log(repo, clock, "apply_sensitive_thread_label", {"threadId": "t1", "labelOption": "SPAM"})

    _arguments, trash_refusal = _check(repo, "untrash_thread", {"threadId": "t1"})
    _arguments, spam_refusal = _check(repo, "unmark_thread_spam", {"threadId": "t1"})

    assert trash_refusal is not None
    assert spam_refusal is None


def test_mark_as_spam_attributes_the_spam_restoration(repo):
    clock = _Clock()
    _log(repo, clock, "mark_message_spam", {"messageId": "m1"})

    _arguments, refusal = _check(repo, "unmark_message_spam", {"messageId": "m1"})

    assert refusal is None


def test_a_thread_level_change_by_the_same_task_attributes_a_message_level_restore(repo):
    clock = _Clock()
    _log(repo, clock, "trash_thread", {"threadId": "t1"}, agent_task_id="task-1")

    _arguments, same_task = _check(repo, "untrash_message", {"messageId": "m1"}, agent_task_id="task-1")
    _arguments, other_task = _check(repo, "untrash_message", {"messageId": "m1"}, agent_task_id="task-2")

    assert same_task is None
    assert other_task is not None


def test_another_connections_history_does_not_attribute_the_change(repo):
    clock = _Clock()
    _log(repo, clock, "trash_thread", {"threadId": "t1"}, connection_id="other-gmail")

    _arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"})

    assert refusal is not None


def test_user_requested_passes_and_is_removed_before_the_call_reaches_gmail(repo):
    arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1", "userRequested": True, "summary": "Invoice"})

    assert refusal is None
    assert arguments == {"threadId": "t1", "summary": "Invoice"}


def test_user_requested_must_be_literally_true(repo):
    arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1", "userRequested": "true"})

    assert refusal is not None
    assert "userRequested" not in arguments


def test_forward_tools_and_label_tools_are_never_guarded(repo):
    for tool_name, tool_arguments in (
        ("trash_thread", {"threadId": "t1"}),
        ("unlabel_thread", {"threadId": "t1", "labelIds": ["INBOX"]}),
        ("label_thread", {"threadId": "t1", "labelIds": ["Label_1"]}),
    ):
        arguments, refusal = _check(repo, tool_name, tool_arguments)
        assert refusal is None
        assert arguments == tool_arguments


def test_connections_that_are_not_gmail_are_not_guarded(repo):
    _arguments, refusal = _check(repo, "untrash_thread", {"threadId": "t1"}, record=_record("https://mcp.linear.app/mcp"))

    assert refusal is None


def test_a_missing_item_id_is_left_for_the_connector_to_report(repo):
    _arguments, refusal = _check(repo, "untrash_thread", {})

    assert refusal is None


def test_an_unreadable_call_log_lets_the_call_proceed(repo):
    class BrokenRepo:
        async def list_successful_calls_for_item(self, *args, **kwargs):
            raise RuntimeError("database is locked")

    arguments, refusal = asyncio.run(
        check_restoration_attribution(_record(), "untrash_thread", {"threadId": "t1"}, agent_task_id="task-1", repo=BrokenRepo())
    )

    assert refusal is None
    assert arguments == {"threadId": "t1"}


def test_item_ids_with_sql_and_json_metacharacters_are_matched_literally(repo):
    clock = _Clock()
    hostile = "t1' OR '1'='1\"; --"
    _log(repo, clock, "trash_thread", {"threadId": hostile})

    _arguments, other = _check(repo, "untrash_thread", {"threadId": "t1"})
    _arguments, same = _check(repo, "untrash_thread", {"threadId": hostile})

    assert other is not None
    assert same is None


def _install_call_tool(monkeypatch, record):
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))
    seen = {"approval": 0, "remote": [], "audit": []}

    async def fake_approval(*args, **kwargs):
        seen["approval"] += 1
        return True

    async def fake_audit(**kwargs):
        seen["audit"].append(kwargs)

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="tok")

    async def fake_schema_guard(record_arg, connection_id, tool_name):
        return None

    class FakeClient:
        async def call_tool(self, server_url, tool_name, arguments, access_token):
            seen["remote"].append((tool_name, arguments))
            return {"ok": True, "result": {}}

    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)
    monkeypatch.setattr(external_catalog_actions, "request_external_catalog_user_approval", fake_approval)
    monkeypatch.setattr(external_catalog_actions, "record_external_catalog_audit", fake_audit)
    monkeypatch.setattr(external_catalog_actions, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(external_catalog_actions, "ensure_tool_schema_surfaced", fake_schema_guard)
    monkeypatch.setattr(external_catalog_actions, "get_external_catalog_mcp_client", lambda: FakeClient())
    return seen


def _gmail_record_for_dispatch():
    return SimpleNamespace(
        id="gmail",
        friendly_name="Gmail",
        description=None,
        server_url=GMAIL_URL,
        enabled=True,
        cached_tools=[],
        tool_policies={"untrash_thread": "always_ask"},
        last_connection_status="connected",
    )


@pytest.mark.asyncio
async def test_a_refusal_skips_the_approval_prompt_and_the_remote_call_and_is_audited_as_skipped(monkeypatch):
    seen = _install_call_tool(monkeypatch, _gmail_record_for_dispatch())

    async def refuse(record, tool_name, arguments, **kwargs):
        from api.services.agent_processing.tools.external_services.external_catalog.envelopes import make_external_catalog_not_attributed

        return arguments, make_external_catalog_not_attributed(tool_name)

    monkeypatch.setattr(external_catalog_actions, "check_restoration_attribution", refuse)

    envelope = await external_catalog_actions.call_external_catalog_tool("gmail", "untrash_thread", {"threadId": "t1"})

    assert envelope["error"]["kind"] == "not_attributed"
    assert seen["approval"] == 0
    assert seen["remote"] == []
    assert [entry["classification"] for entry in seen["audit"]] == ["skipped"]


@pytest.mark.asyncio
async def test_an_allowed_restoration_still_asks_for_approval_and_sends_arguments_without_the_override(monkeypatch):
    seen = _install_call_tool(monkeypatch, _gmail_record_for_dispatch())

    async def allow(record, tool_name, arguments, **kwargs):
        return {key: value for key, value in arguments.items() if key != "userRequested"}, None

    monkeypatch.setattr(external_catalog_actions, "check_restoration_attribution", allow)

    envelope = await external_catalog_actions.call_external_catalog_tool(
        "gmail", "untrash_thread", {"threadId": "t1", "userRequested": True}
    )

    assert envelope["ok"] is True
    assert seen["approval"] == 1
    assert seen["remote"] == [("untrash_thread", {"threadId": "t1"})]
