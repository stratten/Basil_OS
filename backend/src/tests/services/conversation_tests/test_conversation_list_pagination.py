import sqlite3

import pytest

from api.core.knowledge.sqlite import conversation_repository as repository_module
from api.core.knowledge.sqlite.conversation_repository import ConversationRepository
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import SchemaManager


@pytest.fixture
def repository(tmp_path):
    return ConversationRepository(tmp_path / "conversation-pagination.db")


def seed_conversation(
    repository: ConversationRepository,
    *,
    conversation_id: str,
    title: str,
    updated_at: str,
    messages: list[tuple[str, str]],
) -> None:
    with repository_module.get_sync_connection(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, title, updated_at, updated_at),
        )
        for index, (role, content) in enumerate(messages):
            connection.execute(
                "INSERT INTO conversation_messages "
                "(id, conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (f"{conversation_id}-message-{index}", conversation_id, role, content, updated_at),
            )


@pytest.mark.asyncio
async def test_cursor_pages_are_stable_and_compute_summary_fields(repository):
    seed_conversation(
        repository,
        conversation_id="conversation-1",
        title="Oldest",
        updated_at="2026-08-02 09:00:00",
        messages=[("system", "hidden"), ("user", "old visible")],
    )
    seed_conversation(
        repository,
        conversation_id="conversation-2",
        title="Tie lower id",
        updated_at="2026-08-02 10:00:00",
        messages=[("assistant", "lower tie")],
    )
    seed_conversation(
        repository,
        conversation_id="conversation-3",
        title="Tie higher id",
        updated_at="2026-08-02 10:00:00",
        messages=[("user", "higher tie")],
    )
    seed_conversation(
        repository,
        conversation_id="conversation-4",
        title="Newest",
        updated_at="2026-08-02 11:00:00",
        messages=[("system", "hidden"), ("assistant", "x" * 101)],
    )

    first_page = await repository.list_conversation_page(query=None, limit=2)
    second_page = await repository.list_conversation_page(
        query=None,
        limit=2,
        cursor=first_page["next_cursor"],
    )

    assert [item["id"] for item in first_page["conversations"]] == [
        "conversation-4",
        "conversation-3",
    ]
    assert first_page["conversations"][0]["message_count"] == 1
    assert first_page["conversations"][0]["last_message_preview"] == f"{'x' * 100}..."
    assert first_page["has_more"] is True
    assert first_page["next_cursor"]
    assert [item["id"] for item in second_page["conversations"]] == [
        "conversation-2",
        "conversation-1",
    ]
    assert second_page["conversations"][1]["message_count"] == 1
    assert second_page["has_more"] is False
    assert second_page["next_cursor"] is None


@pytest.mark.asyncio
async def test_search_treats_like_metacharacters_as_literal_text(repository):
    seed_conversation(
        repository,
        conversation_id="literal-match",
        title="Budget 100%_\\ approved",
        updated_at="2026-08-02 11:00:00",
        messages=[],
    )
    seed_conversation(
        repository,
        conversation_id="wildcard-only",
        title="Budget 100aa approved",
        updated_at="2026-08-02 10:00:00",
        messages=[],
    )

    page = await repository.list_conversation_page(
        query="100%_\\",
        limit=30,
    )

    assert [item["id"] for item in page["conversations"]] == ["literal-match"]


@pytest.mark.asyncio
async def test_rejects_malformed_cursor(repository):
    with pytest.raises(ValueError, match="Invalid conversation page cursor"):
        await repository.list_conversation_page(
            query=None,
            limit=30,
            cursor="not-a-cursor",
        )


@pytest.mark.asyncio
async def test_page_summary_uses_one_select_statement(repository, monkeypatch):
    seed_conversation(
        repository,
        conversation_id="conversation-1",
        title="One",
        updated_at="2026-08-02 11:00:00",
        messages=[("user", "first")],
    )
    seed_conversation(
        repository,
        conversation_id="conversation-2",
        title="Two",
        updated_at="2026-08-02 10:00:00",
        messages=[("assistant", "second")],
    )
    statements: list[str] = []
    original_connection_factory = repository_module.get_sync_connection

    def traced_connection_factory(db_path: str):
        connection = original_connection_factory(db_path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repository_module, "get_sync_connection", traced_connection_factory)

    await repository.list_conversation_page(query=None, limit=30)

    selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 1


def test_schema_manager_adds_cursor_page_index_to_existing_database(tmp_path):
    database_path = tmp_path / "existing.db"
    SchemaManager(str(database_path)).initialize_db()
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX idx_conversations_updated_at_id")
        connection.commit()

    SchemaManager(str(database_path)).initialize_db()

    with sqlite3.connect(database_path) as connection:
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("idx_conversations_updated_at_id",),
        ).fetchone()
    assert index == ("idx_conversations_updated_at_id",)


def test_schema_manager_skips_conversation_index_when_legacy_database_has_no_conversations(tmp_path):
    database_path = tmp_path / "legacy-without-conversations.db"
    SchemaManager(str(database_path)).initialize_db()
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE conversation_messages")
        connection.execute("DROP TABLE conversations")
        connection.commit()

    SchemaManager(str(database_path)).initialize_db()

    with sqlite3.connect(database_path) as connection:
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("idx_conversations_updated_at_id",),
        ).fetchone()
    assert index is None


@pytest.mark.asyncio
async def test_get_latest_conversation_turn_metadata_returns_the_most_recent_placeholder(tmp_path):
    database_path = tmp_path / "conversation-turn-metadata.db"
    SchemaManager(str(database_path)).initialize_db()
    repository = ConversationRepository(str(database_path))
    conversation_id = await repository.create_conversation(system_message="You are Basil.")

    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="First",
        user_metadata=None,
        assistant_metadata={"conversation_turn": {"route": "direct", "lifecycle": "completed"}},
        assistant_model_id=None,
    )
    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Second",
        user_metadata=None,
        assistant_metadata={"conversation_turn": {"route": "direct", "lifecycle": "running"}},
        assistant_model_id=None,
    )

    latest = await repository.get_latest_conversation_turn_metadata(conversation_id)

    assert latest["conversation_turn"]["lifecycle"] == "running"


@pytest.mark.asyncio
async def test_get_latest_conversation_turn_metadata_returns_none_when_absent(tmp_path):
    database_path = tmp_path / "conversation-turn-metadata-empty.db"
    SchemaManager(str(database_path)).initialize_db()
    repository = ConversationRepository(str(database_path))
    conversation_id = await repository.create_conversation(system_message="You are Basil.")

    latest = await repository.get_latest_conversation_turn_metadata(conversation_id)

    assert latest is None
