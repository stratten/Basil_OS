from __future__ import annotations

from typing import Any

import pytest

from api.services.mcp_connectors.slack_local_server import handlers, server


EXPECTED_READ_ONLY = {
    "slack_search_messages": True,
    "slack_search_files": True,
    "slack_list_channels": True,
    "slack_read_channel_history": True,
    "slack_read_thread": True,
    "slack_create_channel": False,
    "slack_send_message": False,
    "slack_open_dm": False,
    "slack_open_group_dm": False,
    "slack_add_reaction": False,
    "slack_create_canvas": False,
    "slack_read_canvas": True,
    "slack_list_users": True,
    "slack_get_workspace_info": True,
    "slack_list_emoji": True,
    "slack_get_message_reactions": True,
    "slack_get_user_profile": True,
    "slack_list_unread_messages": True,
    "slack_scan_unread_messages": True,
}


class FakeSlackClient:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: dict[str, Any] = {
            "search_messages": {
                "messages": {
                    "matches": [{"text": "hello", "channel": {"name": "general"}}]
                }
            },
            "search_files": {
                "files": {"matches": [{"name": "plan.pdf", "filetype": "pdf", "size": 10}]}
            },
            "conversations_list": {"channels": [{"id": "C1", "name": "general"}]},
            "conversations_history": {
                "messages": [
                    {"ts": "1.000000", "user": "U1", "text": "already read"},
                    {"ts": "2.000000", "user": "U1", "text": "new"},
                ]
            },
            "conversations_replies": {
                "messages": [{"ts": "1.000000", "user": "U1", "text": "parent"}]
            },
            "conversations_create": {"channel": {"id": "CNEW", "name": "new-channel"}},
            "chat_postMessage": {
                "channel": "C1",
                "ts": "3.000000",
                "message": {"text": "posted"},
            },
            "conversations_open": {"channel": {"id": "D1"}},
            "canvases_create": {"canvas_id": "F1"},
            "conversations_canvases_create": {"canvas_id": "F2"},
            "files_info": {"file": {"id": "F1", "title": "Canvas", "plain_text": "Body"}},
            "users_list": {
                "members": [{"id": "U1", "name": "alice", "profile": {"real_name": "Alice"}}]
            },
            "users_profile_get": {
                "profile": {"real_name": "Alice", "email": "alice@example.com"}
            },
            "users_info": {"user": {"name": "alice", "profile": {"display_name": "Alice"}}},
            "team_info": {"team": {"id": "T1", "name": "Acme", "domain": "acme"}},
            "emoji_list": {"emoji": {"party": "https://emoji.example/party.png", "ship": "alias:rocket"}},
            "reactions_get": {"message": {"reactions": [{"name": "white_check_mark", "count": 2}]}},
            "users_conversations": {"channels": []},
            "conversations_info": {"channel": {}},
        }

    def _record(self, name: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((name, kwargs))
        return self.responses[name]

    async def search_messages(self, **kwargs):
        return self._record("search_messages", kwargs)

    async def search_files(self, **kwargs):
        return self._record("search_files", kwargs)

    async def conversations_list(self, **kwargs):
        return self._record("conversations_list", kwargs)

    async def conversations_history(self, **kwargs):
        return self._record("conversations_history", kwargs)

    async def conversations_replies(self, **kwargs):
        return self._record("conversations_replies", kwargs)

    async def conversations_create(self, **kwargs):
        return self._record("conversations_create", kwargs)

    async def chat_postMessage(self, **kwargs):
        return self._record("chat_postMessage", kwargs)

    async def conversations_open(self, **kwargs):
        return self._record("conversations_open", kwargs)

    async def reactions_add(self, **kwargs):
        self.calls.append(("reactions_add", kwargs))
        return {"ok": True}

    async def canvases_create(self, **kwargs):
        return self._record("canvases_create", kwargs)

    async def conversations_canvases_create(self, **kwargs):
        return self._record("conversations_canvases_create", kwargs)

    async def files_info(self, **kwargs):
        return self._record("files_info", kwargs)

    async def users_list(self, **kwargs):
        return self._record("users_list", kwargs)

    async def users_profile_get(self, **kwargs):
        return self._record("users_profile_get", kwargs)

    async def users_info(self, **kwargs):
        return self._record("users_info", kwargs)

    async def team_info(self, **kwargs):
        return self._record("team_info", kwargs)

    async def emoji_list(self, **kwargs):
        return self._record("emoji_list", kwargs)

    async def reactions_get(self, **kwargs):
        return self._record("reactions_get", kwargs)

    async def users_conversations(self, **kwargs):
        return self._record("users_conversations", kwargs)

    async def conversations_info(self, **kwargs):
        self.calls.append(("conversations_info", kwargs))
        channel_id = kwargs["channel"]
        response = self.responses["conversations_info"]
        if isinstance(response, dict) and channel_id in response:
            return response[channel_id]
        return response


@pytest.mark.asyncio
async def test_registry_exposes_current_tool_contracts():
    catalog = await server.list_tools(access_token="ignored")
    tools = catalog["tools"]

    assert len(tools) == 19
    assert {tool["name"] for tool in tools} == set(EXPECTED_READ_ONLY)
    for tool in tools:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
        assert tool["is_read_only_hint"] is EXPECTED_READ_ONLY[tool["name"]]

    send_message = next(tool for tool in tools if tool["name"] == "slack_send_message")
    description = send_message["description"].lower()
    assert "draft" in description
    assert "approval" in description


@pytest.mark.asyncio
async def test_call_tool_current_envelope_contracts(monkeypatch):
    fake = FakeSlackClient()
    monkeypatch.setattr(server, "AsyncWebClient", lambda token, timeout: fake)

    success = await server.call_tool(
        tool_name="slack_search_messages",
        arguments={"query": "hello"},
        access_token="xoxp-test",
    )
    assert success["ok"] is True
    assert set(success["result"]) == {"text", "structured"}

    invalid = await server.call_tool(
        tool_name="slack_search_messages",
        arguments={},
        access_token="xoxp-test",
    )
    assert invalid["ok"] is False
    assert invalid["error"]["kind"] == "invalid_arguments"

    missing = await server.call_tool(
        tool_name="missing",
        arguments={},
        access_token="xoxp-test",
    )
    assert missing["ok"] is False
    assert missing["error"]["kind"] == "not_found"

    no_token = await server.call_tool(
        tool_name="slack_search_messages",
        arguments={"query": "hello"},
        access_token=None,
    )
    assert no_token["ok"] is False
    assert no_token["error"]["kind"] == "auth_expired"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "args", "expected_call", "expected_kwargs"),
    [
        (
            handlers.handle_search_messages,
            {"query": "from:@alice", "count": 5},
            "search_messages",
            {"query": "from:@alice", "count": 5},
        ),
        (
            handlers.handle_search_files,
            {"query": "type:pdf", "count": 6},
            "search_files",
            {"query": "type:pdf", "count": 6},
        ),
        (
            handlers.handle_list_channels,
            {"types": "public_channel", "limit": 7, "exclude_archived": False},
            "conversations_list",
            {"types": "public_channel", "limit": 7, "exclude_archived": False},
        ),
        (
            handlers.handle_read_channel_history,
            {"channel": "C1", "limit": 8, "oldest": "1.000000", "latest": "9.000000"},
            "conversations_history",
            {"channel": "C1", "limit": 8, "oldest": "1.000000", "latest": "9.000000"},
        ),
        (
            handlers.handle_read_thread,
            {"channel": "C1", "thread_ts": "1.000000", "limit": 9},
            "conversations_replies",
            {"channel": "C1", "ts": "1.000000", "limit": 9},
        ),
        (
            handlers.handle_create_channel,
            {"name": "test-channel", "is_private": True},
            "conversations_create",
            {"name": "test-channel", "is_private": True},
        ),
        (
            handlers.handle_send_message,
            {"channel": "C1", "text": "hello", "thread_ts": "1.000000"},
            "chat_postMessage",
            {"channel": "C1", "text": "hello", "thread_ts": "1.000000"},
        ),
        (
            handlers.handle_add_reaction,
            {"channel": "C1", "timestamp": "1.000000", "name": "thumbsup"},
            "reactions_add",
            {"channel": "C1", "timestamp": "1.000000", "name": "thumbsup"},
        ),
        (
            handlers.handle_open_dm,
            {"user": "U1"},
            "conversations_open",
            {"users": "U1"},
        ),
        (
            handlers.handle_open_group_dm,
            {"users": ["U1", "U2"]},
            "conversations_open",
            {"users": "U1,U2"},
        ),
        (handlers.handle_read_canvas, {"canvas_id": "F1"}, "files_info", {"file": "F1"}),
        (
            handlers.handle_list_users,
            {"limit": 10, "include_locale": True},
            "users_list",
            {"limit": 10, "include_locale": True},
        ),
        (
            handlers.handle_get_user_profile,
            {"user": "U1", "include_labels": True},
            "users_info",
            {"user": "U1"},
        ),
        (
            handlers.handle_get_workspace_info,
            {"team_id": "T1"},
            "team_info",
            {"team": "T1"},
        ),
        (
            handlers.handle_list_emoji,
            {"limit": 1},
            "emoji_list",
            {},
        ),
        (
            handlers.handle_get_message_reactions,
            {"channel": "C1", "timestamp": "1.000000", "full": False},
            "reactions_get",
            {"channel": "C1", "timestamp": "1.000000", "full": False},
        ),
        (
            handlers.handle_scan_unread_messages,
            {"max_conversations_to_check": 7, "message_limit_per_channel": 8},
            "users_conversations",
            {
                "types": "public_channel,private_channel,im,mpim",
                "limit": 7,
                "exclude_archived": True,
            },
        ),
    ],
)
async def test_handlers_call_current_slack_sdk_methods(
    handler,
    args,
    expected_call,
    expected_kwargs,
):
    fake = FakeSlackClient()

    result = await handler(fake, args)

    assert fake.calls[0] == (expected_call, expected_kwargs)
    assert set(result) == {"text", "structured"}


@pytest.mark.asyncio
async def test_create_canvas_current_routes_to_standalone_or_channel_method():
    fake = FakeSlackClient()

    await handlers.handle_create_canvas(fake, {"title": "Standalone", "markdown": "Body"})
    await handlers.handle_create_canvas(
        fake,
        {"title": "Attached", "markdown": "Body", "channel_id": "C1"},
    )

    assert fake.calls[0][0] == "canvases_create"
    assert fake.calls[1][0] == "conversations_canvases_create"
    assert fake.calls[1][1]["channel_id"] == "C1"


@pytest.mark.asyncio
async def test_unread_current_scans_history_when_info_reports_zero_unread():
    fake = FakeSlackClient()
    fake.responses["conversations_history"] = {
        "messages": [{"ts": "2.000000", "user": "U1", "text": "new"}]
    }
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C1", "name": "general", "is_channel": True}]
    }
    fake.responses["conversations_info"] = {
        "C1": {
            "channel": {
                "id": "C1",
                "name": "general",
                "last_read": "1.000000",
                "unread_count": 0,
            }
        }
    }

    result = await handlers.handle_list_unread_messages(fake, {})

    assert result["structured"]["total_unread"] == 1
    assert result["structured"]["unread_buckets"][0]["channel"]["label"] == "#general"
    assert (
        "conversations_history",
        {"channel": "C1", "oldest": "1.000000", "inclusive": False, "limit": 50},
    ) in fake.calls


@pytest.mark.asyncio
async def test_unread_current_uses_exclusive_history_when_info_reports_unread():
    fake = FakeSlackClient()
    fake.responses["conversations_history"] = {
        "messages": [{"ts": "2.000000", "user": "U1", "text": "new"}]
    }
    fake.responses["users_conversations"] = {
        "channels": [{"id": "D1", "is_im": True, "user": "U1"}]
    }
    fake.responses["conversations_info"] = {
        "D1": {
            "channel": {
                "id": "D1",
                "is_im": True,
                "user": "U1",
                "last_read": "1.000000",
                "unread_count": 1,
            }
        }
    }

    result = await handlers.handle_list_unread_messages(fake, {})

    assert result["structured"]["total_unread"] == 1
    assert (
        "conversations_history",
        {"channel": "D1", "oldest": "1.000000", "inclusive": False, "limit": 50},
    ) in fake.calls
    assert result["structured"]["unread_buckets"][0]["channel"]["label"] == "DM @Alice"
