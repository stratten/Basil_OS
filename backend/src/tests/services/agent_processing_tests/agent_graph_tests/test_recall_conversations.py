"""Tests for recall_conversations tool (Conversation current-thread/history/detail recall)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.core.knowledge.sqlite.conversation_repository import ConversationRepository
from api.services.agent_processing.tools.internal_basil_tools.recall.conversation_recall_tools import (
    create_recall_conversations_tools,
)


@pytest.fixture
def repository(tmp_path):
    return ConversationRepository(tmp_path / "recall-conversations.db")


def _fake_knowledge_service(repository: ConversationRepository):
    return SimpleNamespace(db_path=repository.db_path)


@pytest.mark.asyncio
async def test_current_thread_returns_bounded_recent_messages(repository):
    conversation_id = await repository.create_conversation()
    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="What's the status of the Q3 report?",
        user_metadata=None,
        assistant_metadata={},
    )
    tools = create_recall_conversations_tools(current_conversation_id=conversation_id)
    assert len(tools) == 1
    assert tools[0].name == "recall_conversations"

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "current_thread"
    assert payload["conversation_id"] == conversation_id
    assert payload["count"] >= 1
    assert any("Q3 report" in message["content"] for message in payload["results"])


@pytest.mark.asyncio
async def test_current_thread_without_captured_id_falls_back_to_param(repository):
    conversation_id = await repository.create_conversation()
    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Follow-up question",
        user_metadata=None,
        assistant_metadata={},
    )
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"conversation_id": conversation_id})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["conversation_id"] == conversation_id


@pytest.mark.asyncio
async def test_current_thread_without_any_id_returns_error(repository):
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "current_thread"
    assert "No delegating Conversation id" in payload["error"]


@pytest.mark.asyncio
async def test_current_thread_captured_id_takes_precedence_over_param(repository):
    captured_id = await repository.create_conversation()
    await repository.create_message_pair(
        conversation_id=captured_id,
        user_content="Captured thread message",
        user_metadata=None,
        assistant_metadata={},
    )
    tools = create_recall_conversations_tools(current_conversation_id=captured_id)

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"conversation_id": "conv-thread-other"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["conversation_id"] == captured_id


@pytest.mark.asyncio
async def test_history_search_finds_conversation_by_title(repository):
    conversation_id = await repository.create_conversation()
    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Discuss the client proposal",
        user_metadata=None,
        assistant_metadata={},
    )
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"scope": "history", "query": "proposal"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "history"
    assert payload["count"] == 1
    assert payload["results"][0]["id"] == conversation_id


@pytest.mark.asyncio
async def test_history_search_with_no_matches_returns_empty_list(repository):
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"scope": "history", "query": "nonexistent-topic-xyz"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["count"] == 0
    assert payload["results"] == []


@pytest.mark.asyncio
async def test_limit_clamped_to_50_on_history(repository):
    for i in range(3):
        conversation_id = await repository.create_conversation()
        await repository.create_message_pair(
            conversation_id=conversation_id,
            user_content="Shared search text",
            user_metadata=None,
            assistant_metadata={},
        )
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"scope": "history", "query": "Shared search text", "limit": 500})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["count"] <= 50


@pytest.mark.asyncio
async def test_detail_scope_returns_bounded_messages_for_named_conversation(repository):
    conversation_id = await repository.create_conversation()
    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Named conversation detail request",
        user_metadata=None,
        assistant_metadata={},
    )
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"scope": "detail", "conversation_id": conversation_id})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "detail"
    assert payload["conversation"]["id"] == conversation_id
    assert any(
        "Named conversation detail request" in message["content"]
        for message in payload["conversation"]["messages"]
    )
    assert payload["conversation"]["messages_truncated"] is False


@pytest.mark.asyncio
async def test_detail_scope_without_conversation_id_returns_error(repository):
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"scope": "detail"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "detail"
    assert "conversation_id" in payload["error"]


@pytest.mark.asyncio
async def test_detail_scope_unknown_conversation_id_returns_error(repository):
    tools = create_recall_conversations_tools()

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({"scope": "detail", "conversation_id": "missing-conv"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "detail"
    assert "missing-conv" in payload["error"]


@pytest.mark.asyncio
async def test_current_thread_content_is_bounded_for_very_long_conversation(repository):
    conversation_id = await repository.create_conversation()
    long_content = "x" * 10000
    for i in range(5):
        await repository.create_message_pair(
            conversation_id=conversation_id,
            user_content=f"{long_content}-{i}",
            user_metadata=None,
            assistant_metadata={},
        )
    tools = create_recall_conversations_tools(current_conversation_id=conversation_id)

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=_fake_knowledge_service(repository)):
        raw = await tools[0].ainvoke({})
    payload = json.loads(raw)

    total_chars = sum(len(message["content"]) for message in payload["results"])
    assert total_chars <= 6000
    assert any(
        message["role"] == "user" and message["content_truncated"]
        for message in payload["results"]
    )


@pytest.mark.asyncio
async def test_tool_returns_json_error_payload_on_unexpected_exception():
    tools = create_recall_conversations_tools(current_conversation_id="conv-broken")

    with patch(
        "api.dependencies.get_sqlite_knowledge_service",
        side_effect=RuntimeError("database unavailable"),
    ):
        raw = await tools[0].ainvoke({})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert "database unavailable" in payload["error"]
