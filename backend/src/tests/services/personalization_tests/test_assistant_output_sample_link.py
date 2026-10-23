from __future__ import annotations

import hashlib
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.knowledge.personalization.session_sample_context import (
    map_session_context_type,
    resolve_session_recipient,
)
from api.core.knowledge.personalization.writing_samples_manager import WritingSamplesManager
from api.core.knowledge.personalization_models import ContextType, SourceType, WritingSample
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.core_migrations import (
    migrate_assistant_outputs_table,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.personalization_migrations import (
    migrate_writing_samples_table,
)
from api.services.assistant_output_history import assistant_output_history_router as history_router_module
from api.services.assistant_output_history.assistant_output_history_service import AssistantOutputHistoryService


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "knowledge.db")
    SchemaManager(path).initialize_db()
    return path


@pytest.mark.parametrize(
    ("session_context_type", "expected"),
    [
        ("email_reply", ContextType.EMAIL_REPLY),
        ("email_generic", ContextType.EMAIL_REPLY),
        ("email_compose", ContextType.EMAIL_COMPOSE),
        ("social_media_twitter", ContextType.SOCIAL_MEDIA),
        ("document_business", ContextType.DOCUMENT),
        ("code_python", ContextType.DOCUMENT),
        ("generic", ContextType.DOCUMENT),
        ("", None),
        (None, None),
    ],
)
def test_map_session_context_type(session_context_type, expected) -> None:
    assert map_session_context_type(session_context_type) == expected


def test_resolve_session_recipient_only_for_email_contexts() -> None:
    metadata = {"primary_participant_email": "miriam@example.com", "primary_participant_name": "Miriam"}

    assert resolve_session_recipient("email_reply", metadata) == ("miriam@example.com", "Miriam")
    assert resolve_session_recipient("document_generic", metadata) == (None, None)
    assert resolve_session_recipient("email_compose", None) == (None, None)


def test_migrations_add_link_and_context_columns_to_existing_tables(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.row_factory = sqlite3.Row
    try:
        migrate_writing_samples_table(conn)
        conn.execute(
            "CREATE TABLE assistant_outputs (id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id TEXT, "
            "output_text TEXT NOT NULL, output_type TEXT DEFAULT 'regular')"
        )
        conn.execute(
            "CREATE TABLE writing_samples (id TEXT PRIMARY KEY, user_id TEXT DEFAULT 'default', "
            "source_type TEXT NOT NULL, context_type TEXT NOT NULL, content TEXT NOT NULL, "
            "content_hash TEXT NOT NULL, created_at TIMESTAMP)"
        )
        migrate_assistant_outputs_table(conn)
        migrate_writing_samples_table(conn)
        migrate_writing_samples_table(conn)

        output_columns = {row["name"] for row in conn.execute("PRAGMA table_info(assistant_outputs)")}
        sample_columns = {row["name"] for row in conn.execute("PRAGMA table_info(writing_samples)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(writing_samples)")}
    finally:
        conn.close()

    assert {"context_type", "recipient"} <= output_columns
    assert "assistant_output_id" in sample_columns
    assert "idx_writing_samples_assistant_output" in indexes


@pytest.mark.asyncio
async def test_history_rows_round_trip_context_and_recipient(db_path: str) -> None:
    service = AssistantOutputHistoryService(SimpleNamespace(db_path=db_path))

    row_id = await service.persist_assistant_output(
        output_text="Hi Miriam",
        output_type="assistant_session",
        context_type="email_reply",
        recipient="miriam@example.com",
    )
    legacy_id = await service.persist_assistant_output(output_text="Older row", output_type="assistant_session")

    detail = await service.get_assistant_output_detail(row_id)
    legacy = await service.get_assistant_output_detail(legacy_id)

    assert detail["context_type"] == "email_reply"
    assert detail["recipient"] == "miriam@example.com"
    assert legacy["context_type"] is None
    assert legacy["recipient"] is None


@pytest.mark.asyncio
async def test_samples_link_to_history_rows_with_hash_fallback(db_path: str) -> None:
    manager = WritingSamplesManager(db_path)
    unlinked = await manager.add_writing_sample(
        content="Same text",
        source_type=SourceType.ASSISTANT_SESSION_ACCEPTED,
        context_type=ContextType.EMAIL_REPLY,
    )

    assert await manager.find_sample_for_assistant_output(41, []) is None
    by_hash = await manager.find_sample_for_assistant_output(41, ["Same text"])
    assert by_hash is not None and by_hash.id == unlinked.id

    duplicate = await manager.add_writing_sample(
        content="Same text",
        source_type=SourceType.ASSISTANT_SESSION_ACCEPTED,
        context_type=ContextType.EMAIL_REPLY,
        assistant_output_id=41,
    )
    assert duplicate.id == unlinked.id
    linked = await manager.find_sample_for_assistant_output(41, [])
    assert linked is not None and linked.id == unlinked.id


class _FakeHistoryService:
    def __init__(self, detail: dict | None) -> None:
        self.detail = detail

    async def get_assistant_output_detail(self, assistant_output_id: int) -> dict | None:
        if self.detail is None or assistant_output_id != self.detail["id"]:
            return None
        return dict(self.detail)


class _FakePersonalization:
    def __init__(self, linked: WritingSample | None = None) -> None:
        self.linked = linked
        self.added: dict | None = None

    async def find_sample_for_assistant_output(self, assistant_output_id, candidate_contents):
        return self.linked

    async def add_writing_sample(self, **kwargs) -> WritingSample:
        self.added = kwargs
        return WritingSample(
            id="sample-9",
            source_type=kwargs["source_type"],
            context_type=kwargs["context_type"],
            content=kwargs["content"],
            content_hash=hashlib.sha256(kwargs["content"].encode("utf-8")).hexdigest(),
        )


def _history_detail(context_type: str | None) -> dict:
    return {
        "id": 7,
        "output_type": "assistant_session",
        "output_text": "Original reply",
        "refinements": [],
        "app_name": "Mail",
        "context_type": context_type,
        "recipient": "miriam@example.com" if context_type else None,
    }


def _client(monkeypatch, detail: dict | None, personalization: _FakePersonalization) -> TestClient:
    monkeypatch.setattr(history_router_module, "_get_service", lambda: _FakeHistoryService(detail))
    monkeypatch.setattr(history_router_module, "_get_personalization_service", lambda: personalization)
    app = FastAPI()
    app.include_router(history_router_module.router)
    return TestClient(app)


def test_history_detail_reports_context_and_saved_sample(monkeypatch) -> None:
    linked = WritingSample(
        id="sample-3",
        source_type=SourceType.ASSISTANT_SESSION_ACCEPTED,
        context_type=ContextType.EMAIL_REPLY,
        content="Original reply",
        content_hash=hashlib.sha256(b"Original reply").hexdigest(),
    )
    unsaved = _client(monkeypatch, _history_detail("email_reply"), _FakePersonalization()).get("/assistant-outputs/7")
    saved = _client(monkeypatch, _history_detail(None), _FakePersonalization(linked)).get("/assistant-outputs/7")

    assert unsaved.status_code == 200
    assert unsaved.json()["sample_context_type"] == "email_reply"
    assert unsaved.json()["saved_sample"] is None
    assert saved.json()["sample_context_type"] is None
    assert saved.json()["saved_sample"] == {"id": "sample-3", "content": "Original reply", "context_type": "email_reply"}


def test_save_sample_uses_stored_context_and_requires_legacy_choice(monkeypatch) -> None:
    personalization = _FakePersonalization()
    client = _client(monkeypatch, _history_detail("email_reply"), personalization)

    saved = client.post("/assistant-outputs/7/save-sample", json={"content": "Edited reply", "context_type": "document"})

    assert saved.status_code == 200
    assert saved.json() == {
        "status": "saved",
        "sample_id": "sample-9",
        "content": "Edited reply",
        "context_type": "email_reply",
    }
    assert personalization.added["context_type"] == ContextType.EMAIL_REPLY
    assert personalization.added["source_type"] == SourceType.ASSISTANT_SESSION_ACCEPTED
    assert personalization.added["recipient"] == "miriam@example.com"
    assert personalization.added["assistant_output_id"] == 7

    legacy_personalization = _FakePersonalization()
    legacy_client = _client(monkeypatch, _history_detail(None), legacy_personalization)
    missing = legacy_client.post("/assistant-outputs/7/save-sample", json={"content": "Reply"})
    invalid = legacy_client.post("/assistant-outputs/7/save-sample", json={"content": "Reply", "context_type": "all"})
    chosen = legacy_client.post("/assistant-outputs/7/save-sample", json={"content": "Reply", "context_type": "social_media"})

    assert missing.status_code == 400
    assert invalid.status_code == 400
    assert chosen.status_code == 200
    assert legacy_personalization.added["context_type"] == ContextType.SOCIAL_MEDIA


def test_save_sample_rejects_blank_content_and_unknown_rows(monkeypatch) -> None:
    personalization = _FakePersonalization()
    client = _client(monkeypatch, _history_detail("email_reply"), personalization)

    blank = client.post("/assistant-outputs/7/save-sample", json={"content": "   \n"})
    unknown = client.post("/assistant-outputs/999/save-sample", json={"content": "Reply"})

    assert blank.status_code == 400
    assert unknown.status_code == 404
    assert personalization.added is None


@pytest.mark.asyncio
async def test_fresh_sample_links_to_history_row(db_path: str) -> None:
    manager = WritingSamplesManager(db_path)

    sample = await manager.add_writing_sample(
        content="Fresh linked text",
        source_type=SourceType.ASSISTANT_SESSION_ACCEPTED,
        context_type=ContextType.DOCUMENT,
        assistant_output_id=42,
    )

    linked = await manager.find_sample_for_assistant_output(42, [])
    assert linked is not None and linked.id == sample.id
    assert await manager.find_sample_for_assistant_output(43, []) is None
