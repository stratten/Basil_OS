from __future__ import annotations

import pytest

from api.services.mcp_connectors.slack_local_server import handlers


class FakeSlackClient:
    def __init__(self):
        self.calls = []
        self.responses = {
            "conversations_history": {"messages": []},
            "conversations_info": {"channel": {}},
            "users_conversations": {"channels": []},
            "users_info": {"user": {"profile": {}}},
            "users_profile_get": {"profile": {}},
            "team_info": {"team": {}},
            "emoji_list": {"emoji": {}},
            "reactions_get": {"message": {}},
            "conversations_open": {"channel": {"id": "D1"}},
        }

    def _record(self, name, kwargs):
        self.calls.append((name, kwargs))
        return self.responses[name]

    async def conversations_history(self, **kwargs):
        return self._record("conversations_history", kwargs)

    async def conversations_info(self, **kwargs):
        self.calls.append(("conversations_info", kwargs))
        channel_id = kwargs["channel"]
        response = self.responses["conversations_info"]
        if isinstance(response, dict) and channel_id in response:
            return response[channel_id]
        return response

    async def users_conversations(self, **kwargs):
        return self._record("users_conversations", kwargs)

    async def users_info(self, **kwargs):
        return self._record("users_info", kwargs)

    async def users_profile_get(self, **kwargs):
        return self._record("users_profile_get", kwargs)

    async def team_info(self, **kwargs):
        return self._record("team_info", kwargs)

    async def emoji_list(self, **kwargs):
        return self._record("emoji_list", kwargs)

    async def reactions_get(self, **kwargs):
        return self._record("reactions_get", kwargs)

    async def conversations_open(self, **kwargs):
        return self._record("conversations_open", kwargs)


@pytest.mark.asyncio
async def test_unread_detects_channel_history_when_unread_count_is_missing():
    fake = FakeSlackClient()
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C1", "name": "general", "is_channel": True}]
    }
    fake.responses["conversations_info"] = {
        "C1": {
            "channel": {
                "id": "C1",
                "name": "general",
                "last_read": "1.000000",
                "unread_count": None,
            }
        }
    }
    fake.responses["conversations_history"] = {
        "messages": [{"ts": "2.000000", "user": "U1", "text": "new"}],
        "has_more": False,
    }

    result = await handlers.handle_list_unread_messages(fake, {})

    assert result["structured"]["total_unread"] == 1
    assert result["structured"]["unread_buckets"][0]["channel"]["label"] == "#general"
    assert result["structured"]["diagnostics"][0]["scan_method"] == "history_after_last_read"
    assert ("conversations_history", {
        "channel": "C1",
        "oldest": "1.000000",
        "inclusive": False,
        "limit": 50,
    }) in fake.calls


@pytest.mark.asyncio
async def test_unread_records_zero_last_read_as_unknown_without_history_call():
    fake = FakeSlackClient()
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C1", "name": "general", "is_channel": True}]
    }
    fake.responses["conversations_info"] = {
        "C1": {
            "channel": {
                "id": "C1",
                "name": "general",
                "last_read": "0000000000.000000",
                "unread_count": None,
            }
        }
    }

    result = await handlers.handle_list_unread_messages(fake, {})

    assert result["structured"]["total_unread"] == 0
    assert result["structured"]["unread_state_unknown_count"] == 1
    assert result["structured"]["diagnostics"][0]["skip_reason"] == "unread_state_unknown"
    assert "conversations_history" not in [name for name, _kwargs in fake.calls]


@pytest.mark.asyncio
async def test_unread_no_result_text_is_bounded_to_scanned_conversations():
    fake = FakeSlackClient()
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C1", "name": "general", "is_channel": True}]
    }
    fake.responses["conversations_info"] = {
        "C1": {
            "channel": {
                "id": "C1",
                "name": "general",
                "last_read": "1.000000",
                "unread_count": None,
            }
        }
    }
    fake.responses["conversations_history"] = {"messages": [], "has_more": False}

    result = await handlers.handle_list_unread_messages(fake, {"max_conversations_to_check": 1})

    assert "No unread messages found in the scanned conversations" in result["text"]
    assert "completely caught up" not in result["text"]


@pytest.mark.asyncio
async def test_profile_uses_users_info_with_supported_fields_and_label_flag():
    fake = FakeSlackClient()
    fake.responses["users_info"] = {
        "user": {
            "id": "U1",
            "name": "alice",
            "profile": {
                "real_name": "Alice Example",
                "email": "alice@example.com",
                "title": "Founder",
                "status_text": "In focus mode",
            },
        }
    }

    result = await handlers.handle_get_user_profile(
        fake,
        {"user": "U1", "include_labels": True},
    )

    assert fake.calls[0] == ("users_info", {"user": "U1"})
    assert "users_profile_get" not in [name for name, _kwargs in fake.calls]
    assert result["structured"]["profile"]["email"] == "alice@example.com"
    assert result["structured"]["labels_supported"] is False


@pytest.mark.asyncio
async def test_workspace_info_uses_team_info_with_optional_team_id():
    fake = FakeSlackClient()
    fake.responses["team_info"] = {"team": {"id": "T1", "name": "Acme", "domain": "acme"}}

    result = await handlers.handle_get_workspace_info(fake, {"team_id": "T1"})

    assert fake.calls[0] == ("team_info", {"team": "T1"})
    assert result["structured"]["team"]["domain"] == "acme"
    assert "Workspace Acme" in result["text"]


@pytest.mark.asyncio
async def test_list_emoji_marks_aliases_and_truncation():
    fake = FakeSlackClient()
    fake.responses["emoji_list"] = {
        "emoji": {
            "party": "https://emoji.example/party.png",
            "rocket_alias": "alias:rocket",
        }
    }

    result = await handlers.handle_list_emoji(fake, {"limit": 1})

    assert fake.calls[0] == ("emoji_list", {})
    assert result["structured"]["returned_count"] == 1
    assert result["structured"]["total_count"] == 2
    assert result["structured"]["truncated"] is True


@pytest.mark.asyncio
async def test_get_message_reactions_uses_reactions_get_and_counts_reactions():
    fake = FakeSlackClient()
    fake.responses["reactions_get"] = {
        "message": {
            "text": "done",
            "reactions": [
                {"name": "white_check_mark", "count": 2},
                {"name": "eyes", "count": 1},
            ],
        }
    }

    result = await handlers.handle_get_message_reactions(
        fake,
        {"channel": "C1", "timestamp": "1.000000", "full": True},
    )

    assert fake.calls[0] == (
        "reactions_get",
        {"channel": "C1", "timestamp": "1.000000", "full": True},
    )
    assert result["structured"]["total_reaction_count"] == 3
    assert ":white_check_mark:" in result["text"]


@pytest.mark.asyncio
async def test_open_dm_uses_conversations_open_with_single_user():
    fake = FakeSlackClient()

    result = await handlers.handle_open_dm(fake, {"user": "U1"})

    assert fake.calls[0] == ("conversations_open", {"users": "U1"})
    assert result["structured"]["channel"]["id"] == "D1"
    assert result["structured"]["users"] == ["U1"]


@pytest.mark.asyncio
async def test_open_group_dm_uses_conversations_open_with_comma_joined_users():
    fake = FakeSlackClient()
    fake.responses["conversations_open"] = {"channel": {"id": "G1"}}

    result = await handlers.handle_open_group_dm(fake, {"users": ["U1", "U2"]})

    assert fake.calls[0] == ("conversations_open", {"users": "U1,U2"})
    assert result["structured"]["channel"]["id"] == "G1"
    assert result["structured"]["users"] == ["U1", "U2"]


@pytest.mark.asyncio
async def test_scan_unread_messages_returns_next_cursor_and_partial_wording():
    fake = FakeSlackClient()
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C1", "name": "general", "is_channel": True}],
        "response_metadata": {"next_cursor": "cursor-2"},
    }
    fake.responses["conversations_info"] = {
        "C1": {
            "channel": {
                "id": "C1",
                "name": "general",
                "last_read": "1.000000",
                "unread_count": 1,
            }
        }
    }
    fake.responses["conversations_history"] = {
        "messages": [{"ts": "2.000000", "user": "U1", "text": "new"}],
        "has_more": False,
    }

    result = await handlers.handle_scan_unread_messages(fake, {"max_conversations_to_check": 1})

    assert "Partial unread scan" in result["text"]
    assert "Continue with next_cursor" in result["text"]
    assert result["structured"]["next_cursor"] == "cursor-2"
    assert result["structured"]["is_complete"] is False
    assert ("users_conversations", {
        "types": "public_channel,private_channel,im,mpim",
        "limit": 1,
        "exclude_archived": True,
    }) in fake.calls


@pytest.mark.asyncio
async def test_scan_unread_messages_uses_supplied_cursor_for_continuation():
    fake = FakeSlackClient()
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C2", "name": "random", "is_channel": True}],
        "response_metadata": {"next_cursor": ""},
    }
    fake.responses["conversations_info"] = {
        "C2": {
            "channel": {
                "id": "C2",
                "name": "random",
                "last_read": "1.000000",
                "unread_count": 0,
            }
        }
    }
    fake.responses["conversations_history"] = {"messages": [], "has_more": False}

    result = await handlers.handle_scan_unread_messages(fake, {"cursor": "cursor-1", "max_conversations_to_check": 1})

    assert result["structured"]["is_complete"] is True
    assert result["structured"]["scanned"]["cursor"] == "cursor-1"
    assert "completed staged scan" in result["text"]
    assert ("users_conversations", {
        "types": "public_channel,private_channel,im,mpim",
        "limit": 1,
        "exclude_archived": True,
        "cursor": "cursor-1",
    }) in fake.calls


@pytest.mark.asyncio
async def test_scan_unread_messages_does_not_claim_caught_up_with_unknown_cursor():
    fake = FakeSlackClient()
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C1", "name": "general", "is_channel": True}],
        "response_metadata": {"next_cursor": ""},
    }
    fake.responses["conversations_info"] = {
        "C1": {
            "channel": {
                "id": "C1",
                "name": "general",
                "last_read": "0000000000.000000",
                "unread_count": None,
            }
        }
    }

    result = await handlers.handle_scan_unread_messages(fake, {"max_conversations_to_check": 1})

    assert "No unread messages found in this partial staged scan page" in result["text"]
    assert "caught up" not in result["text"]
    assert result["structured"]["is_complete"] is True
    assert result["structured"]["unread_state_unknown_count"] == 1


@pytest.mark.asyncio
async def test_scan_unread_messages_records_history_errors_as_diagnostics():
    fake = FakeSlackClient()
    fake.responses["users_conversations"] = {
        "channels": [{"id": "C1", "name": "general", "is_channel": True}],
        "response_metadata": {"next_cursor": ""},
    }
    fake.responses["conversations_info"] = {
        "C1": {
            "channel": {
                "id": "C1",
                "name": "general",
                "last_read": "1.000000",
                "unread_count": 1,
            }
        }
    }

    async def raise_history(**_kwargs):
        raise RuntimeError("rate limited")

    fake.conversations_history = raise_history

    result = await handlers.handle_scan_unread_messages(fake, {"max_conversations_to_check": 1})

    assert result["structured"]["history_error_count"] == 1
    assert result["structured"]["diagnostics"][0]["skip_reason"] == "history_error"
    assert "History checks failed" in result["text"]


@pytest.mark.asyncio
async def test_read_channel_history_resolves_user_ids_to_display_names_with_one_lookup_per_user():
    """Per-message authors should be human-readable, and a single tool call
    should hit users.info at most once per distinct user id."""
    fake = FakeSlackClient()
    fake.responses["conversations_history"] = {
        "messages": [
            {"ts": "1.000000", "user": "U01F4U6RENA", "text": "first"},
            {"ts": "2.000000", "user": "U01F4U6RENA", "text": "second"},
            {"ts": "3.000000", "user": "UCG02RYD6", "text": "third"},
        ]
    }
    fake.responses["users_info"] = {
        "U01F4U6RENA": {
            "user": {
                "id": "U01F4U6RENA",
                "name": "alice",
                "profile": {"display_name": "Alice", "real_name": "Alice Example"},
            }
        },
        "UCG02RYD6": {
            "user": {
                "id": "UCG02RYD6",
                "name": "bob",
                "profile": {"display_name": "Bob", "real_name": "Bob Example"},
            }
        },
    }

    original_users_info = fake.users_info

    async def per_user_users_info(**kwargs):
        user_id = kwargs.get("user")
        result = await original_users_info(**kwargs)
        if isinstance(fake.responses["users_info"], dict) and user_id in fake.responses["users_info"]:
            return fake.responses["users_info"][user_id]
        return result

    fake.users_info = per_user_users_info

    result = await handlers.handle_read_channel_history(fake, {"channel": "C1", "limit": 5})

    text = result["text"]
    assert "Alice" in text
    assert "Bob" in text
    assert "U01F4U6RENA" not in text
    assert "UCG02RYD6" not in text
    users_info_calls = [kwargs.get("user") for name, kwargs in fake.calls if name == "users_info"]
    assert sorted(users_info_calls) == ["U01F4U6RENA", "UCG02RYD6"]
    assert result["structured"]["messages"][0]["user"] == "U01F4U6RENA"


@pytest.mark.asyncio
async def test_search_messages_prefers_username_when_slack_supplies_it():
    """search.messages results often pre-populate ``username`` with the
    resolved display name; using it avoids an unnecessary users.info call."""
    fake = FakeSlackClient()

    async def search_messages_stub(**kwargs):
        fake.calls.append(("search_messages", kwargs))
        return {
            "messages": {
                "matches": [
                    {
                        "text": "deploy is green",
                        "username": "Alice",
                        "user": "U01F4U6RENA",
                        "channel": {"name": "deploys"},
                    }
                ]
            }
        }

    fake.search_messages = search_messages_stub

    result = await handlers.handle_search_messages(fake, {"query": "deploy", "count": 5})

    assert "Alice" in result["text"]
    assert "U01F4U6RENA" not in result["text"]
    assert "users_info" not in [name for name, _ in fake.calls]


@pytest.mark.asyncio
async def test_search_messages_resolves_raw_user_id_when_username_missing():
    """When Slack omits ``username``, the handler should resolve the raw id."""
    fake = FakeSlackClient()
    fake.responses["users_info"] = {
        "user": {"id": "UCG02RYD6", "profile": {"display_name": "Bob"}}
    }

    async def search_messages_stub(**kwargs):
        fake.calls.append(("search_messages", kwargs))
        return {
            "messages": {
                "matches": [
                    {
                        "text": "ping",
                        "user": "UCG02RYD6",
                        "channel": {"name": "general"},
                    }
                ]
            }
        }

    fake.search_messages = search_messages_stub

    result = await handlers.handle_search_messages(fake, {"query": "ping", "count": 5})

    assert "Bob" in result["text"]
    assert "UCG02RYD6" not in result["text"]
    assert ("users_info", {"user": "UCG02RYD6"}) in fake.calls


@pytest.mark.asyncio
async def test_message_author_resolution_falls_back_to_raw_id_when_users_info_errors():
    """If users.info raises (missing scope, transient error), the formatter
    must keep going with the raw id rather than aborting the whole tool."""
    fake = FakeSlackClient()
    fake.responses["conversations_history"] = {
        "messages": [{"ts": "1.000000", "user": "U_RAW", "text": "stuck"}]
    }

    async def raise_users_info(**_kwargs):
        raise RuntimeError("missing users:read scope")

    fake.users_info = raise_users_info

    result = await handlers.handle_read_channel_history(fake, {"channel": "C1", "limit": 1})

    assert "U_RAW" in result["text"]
    assert result["structured"]["messages"][0]["user"] == "U_RAW"
