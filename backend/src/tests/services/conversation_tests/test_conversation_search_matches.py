import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from api.core.knowledge.sqlite import conversation_repository as repository_module
from api.core.knowledge.sqlite.conversation_repository import ConversationRepository
from api.services.conversation.conversation_routes import get_conversation_service, router


@pytest.fixture
def repository(tmp_path):
    return ConversationRepository(tmp_path / "conversation-search-matches.db")


def seed_conversation(repository, conversation_id, messages):
    """messages is a list of (message_id, role, content, timestamp)."""
    with repository_module.get_sync_connection(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, "Title", "2026-08-02 09:00:00", "2026-08-02 09:00:00"),
        )
        for message_id, role, content, timestamp in messages:
            connection.execute(
                "INSERT INTO conversation_messages (id, conversation_id, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, timestamp),
            )


@pytest.fixture
def seeded(repository):
    seed_conversation(repository, "chat-1", [
        ("m0", "system", "You are Basil and lisbon is hidden here", "2026-08-02 09:00:00"),
        ("m1", "user", "Plan the Lisbon offsite", "2026-08-02 09:00:01"),
        ("m2", "assistant", "Sure, nothing about the city yet", "2026-08-02 09:00:02"),
        ("m3", "user", "Book LISBON hotels", "2026-08-02 09:00:03"),
        ("m4", "assistant", "Done with 100% of the lisbon list", "2026-08-02 09:00:04"),
    ])
    seed_conversation(repository, "chat-2", [
        ("other-1", "user", "lisbon in a different chat", "2026-08-02 09:00:00"),
    ])
    return repository


@pytest.mark.asyncio
async def test_returns_matching_messages_oldest_first_and_skips_system_and_other_chats(seeded):
    matches = await seeded.find_search_matches("chat-1", "lisbon")

    assert matches.tokens == ["lisbon"]
    assert matches.matched_message_ids == ["m1", "m3", "m4"]


@pytest.mark.asyncio
async def test_first_middle_and_last_message_matches(seeded):
    assert (await seeded.find_search_matches("chat-1", "Plan the")).matched_message_ids == ["m1"]
    assert (await seeded.find_search_matches("chat-1", "city yet")).matched_message_ids == ["m2"]
    assert (await seeded.find_search_matches("chat-1", "list")).matched_message_ids == ["m4"]


@pytest.mark.asyncio
async def test_no_match_returns_empty_ids_with_the_phrase(seeded):
    matches = await seeded.find_search_matches("chat-1", "zebra")

    assert matches.tokens == ["zebra"]
    assert matches.matched_message_ids == []


@pytest.mark.asyncio
async def test_blank_query_matches_nothing(seeded):
    for blank in (None, "", "   "):
        matches = await seeded.find_search_matches("chat-1", blank)
        assert matches.tokens == []
        assert matches.matched_message_ids == []


@pytest.mark.asyncio
async def test_percent_and_underscore_are_literal(seeded):
    assert (await seeded.find_search_matches("chat-1", "100%")).matched_message_ids == ["m4"]
    assert (await seeded.find_search_matches("chat-1", "%")).matched_message_ids == ["m4"]
    assert (await seeded.find_search_matches("chat-1", "_")).matched_message_ids == []
    assert (await seeded.find_search_matches("chat-1", "a\\b")).matched_message_ids == []


@pytest.mark.asyncio
async def test_unknown_conversation_returns_none(seeded):
    assert await seeded.find_search_matches("missing", "lisbon") is None


@pytest.fixture
def client(seeded):
    service = MagicMock()
    service.find_search_matches = seeded.find_search_matches
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_conversation_service] = lambda: service
    return TestClient(app)


def test_route_returns_matches(client):
    response = client.get("/api/v1/conversation/chat-1/search-matches", params={"query": "lisbon"})

    assert response.status_code == 200
    assert response.json() == {"tokens": ["lisbon"], "matched_message_ids": ["m1", "m3", "m4"]}


def test_route_returns_empty_lists_for_a_blank_query(client):
    response = client.get("/api/v1/conversation/chat-1/search-matches")

    assert response.status_code == 200
    assert response.json() == {"tokens": [], "matched_message_ids": []}


def test_route_returns_404_for_an_unknown_conversation(client):
    response = client.get("/api/v1/conversation/missing/search-matches", params={"query": "lisbon"})

    assert response.status_code == 404


def test_route_is_not_shadowed_by_the_conversation_detail_route(client):
    # The detail route has one path segment; the matches route has two and must not fall through to it.
    response = client.get("/api/v1/conversation/chat-1/search-matches", params={"query": "zebra"})

    assert response.status_code == 200
    assert response.json()["matched_message_ids"] == []
