from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.core.knowledge.personalization.writing_samples_manager import WritingSamplesManager
from api.core.knowledge.personalization_models import ContextType, SourceType, WritingSample
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.routes.personalization import router as personalization_router
from api.routes.personalization.dependencies import get_personalization_service
from api.routes.personalization.models import SaveWritingSampleRequest, UpdateWritingSampleRequest
from api.routes.personalization.writing_sample_routes import save_writing_sample, update_writing_sample


@pytest.fixture
def writing_samples_manager(tmp_path) -> WritingSamplesManager:
    db_path = str(tmp_path / "knowledge.db")
    SchemaManager(db_path).initialize_db()
    return WritingSamplesManager(db_path)


@pytest.mark.asyncio
async def test_update_writing_sample_replaces_content_and_tracks_edit_distance(
    writing_samples_manager: WritingSamplesManager,
) -> None:
    original_content = "Thank you for your message."
    updated_content = "Thank you for your message. I will reply tomorrow."
    sample = await writing_samples_manager.add_writing_sample(
        content=original_content,
        source_type=SourceType.MANUAL_ENTRY,
        context_type=ContextType.EMAIL_REPLY,
    )

    updated = await writing_samples_manager.update_writing_sample(sample.id, updated_content)

    assert updated is not None
    assert updated.content == updated_content
    assert updated.content_hash == hashlib.sha256(updated_content.encode("utf-8")).hexdigest()
    assert updated.was_edited is True
    assert updated.edit_distance is not None
    assert updated.edit_distance > 0


@pytest.mark.asyncio
async def test_update_writing_sample_returns_none_for_unknown_id(
    writing_samples_manager: WritingSamplesManager,
) -> None:
    updated = await writing_samples_manager.update_writing_sample("missing-sample", "Updated content")

    assert updated is None


class _WritingSampleRouteService:
    def __init__(self) -> None:
        self.saved_source_type: SourceType | None = None
        self.auto_analyze_style: bool | None = None
        self.update_kwargs: dict = {}

    async def add_writing_sample(self, **kwargs) -> WritingSample:
        self.saved_source_type = kwargs["source_type"]
        self.auto_analyze_style = kwargs["auto_analyze_style"]
        return WritingSample(
            id="sample-1",
            source_type=kwargs["source_type"],
            context_type=kwargs["context_type"],
            content=kwargs["content"],
            content_hash=hashlib.sha256(kwargs["content"].encode("utf-8")).hexdigest(),
        )

    async def update_writing_sample(self, sample_id: str, content: str, **kwargs) -> WritingSample | None:
        self.update_kwargs = kwargs
        if sample_id == "missing-sample":
            return None
        return WritingSample(
            id=sample_id,
            source_type=SourceType.MANUAL_ENTRY,
            context_type=kwargs.get("context_type") or ContextType.DOCUMENT,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            recipient=kwargs.get("recipient") if kwargs.get("update_recipient") else None,
            was_edited=True,
            edit_distance=1,
        )


@pytest.mark.asyncio
async def test_save_writing_sample_defaults_source_type_to_suggestion_accepted() -> None:
    service = _WritingSampleRouteService()

    response = await save_writing_sample(
        SaveWritingSampleRequest(content="A sample", context_type="document"),
        service,
    )

    assert response.status == "saved"
    assert service.saved_source_type == SourceType.SUGGESTION_ACCEPTED
    assert service.auto_analyze_style is True


@pytest.mark.asyncio
async def test_save_writing_sample_uses_manual_entry_source_type() -> None:
    service = _WritingSampleRouteService()

    response = await save_writing_sample(
        SaveWritingSampleRequest(content="A manual sample", context_type="document", source_type="manual_entry"),
        service,
    )

    assert response.status == "saved"
    assert service.saved_source_type == SourceType.MANUAL_ENTRY
    assert service.auto_analyze_style is False


@pytest.mark.asyncio
async def test_update_writing_sample_route_returns_not_found_for_unknown_id() -> None:
    service = _WritingSampleRouteService()

    with pytest.raises(HTTPException) as error:
        await update_writing_sample(
            "missing-sample",
            UpdateWritingSampleRequest(content="Updated content"),
            service,
        )

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_update_writing_sample_route_rejects_blank_content() -> None:
    service = _WritingSampleRouteService()

    with pytest.raises(HTTPException) as error:
        await update_writing_sample(
            "sample-1",
            UpdateWritingSampleRequest(content="   \n"),
            service,
        )

    assert error.value.status_code == 400


def test_patch_writing_sample_http_route_is_mounted_under_user_prefix() -> None:
    app = FastAPI()
    app.include_router(personalization_router)
    app.dependency_overrides[get_personalization_service] = _WritingSampleRouteService
    client = TestClient(app)

    response = client.patch("/user/writing-samples/sample-1", json={"content": "Edited content"})
    missing = client.patch("/user/writing-samples/missing-sample", json={"content": "Edited content"})
    blank = client.patch("/user/writing-samples/sample-1", json={"content": " "})

    assert response.status_code == 200
    assert response.json() == {
        "status": "updated",
        "sample_id": "sample-1",
        "content": "Edited content",
        "context_type": "document",
        "recipient": None,
    }
    assert missing.status_code == 404
    assert blank.status_code == 400


@pytest.mark.asyncio
async def test_update_writing_sample_changes_context_and_recipient_without_edit_tracking(
    writing_samples_manager: WritingSamplesManager,
) -> None:
    sample = await writing_samples_manager.add_writing_sample(
        content="Hello team.",
        source_type=SourceType.MANUAL_ENTRY,
        context_type=ContextType.EMAIL_REPLY,
        recipient="old@example.com",
    )

    updated = await writing_samples_manager.update_writing_sample(
        sample.id,
        "Hello team.",
        context_type=ContextType.DOCUMENT,
        recipient="new@example.com",
        update_recipient=True,
    )

    assert updated is not None
    assert updated.context_type == ContextType.DOCUMENT
    assert updated.recipient == "new@example.com"
    assert updated.was_edited is False
    assert updated.edit_distance is None

    cleared = await writing_samples_manager.update_writing_sample(
        sample.id, "Hello team.", recipient=None, update_recipient=True
    )
    assert cleared is not None
    assert cleared.recipient is None
    assert cleared.context_type == ContextType.DOCUMENT

    untouched = await writing_samples_manager.update_writing_sample(
        sample.id, "Hello team, updated."
    )
    assert untouched is not None
    assert untouched.recipient is None
    assert untouched.context_type == ContextType.DOCUMENT
    assert untouched.was_edited is True


@pytest.mark.asyncio
async def test_update_writing_sample_route_leaves_context_and_recipient_when_omitted() -> None:
    service = _WritingSampleRouteService()

    await update_writing_sample("sample-1", UpdateWritingSampleRequest(content="Edited"), service)

    assert service.update_kwargs == {
        "context_type": None,
        "recipient": None,
        "update_recipient": False,
    }


@pytest.mark.asyncio
async def test_update_writing_sample_route_passes_context_and_clears_blank_recipient() -> None:
    service = _WritingSampleRouteService()

    response = await update_writing_sample(
        "sample-1",
        UpdateWritingSampleRequest(content="Edited", context_type="social_media", recipient="   "),
        service,
    )

    assert service.update_kwargs == {
        "context_type": ContextType.SOCIAL_MEDIA,
        "recipient": None,
        "update_recipient": True,
    }
    assert response.context_type == "social_media"
    assert response.recipient is None


@pytest.mark.asyncio
@pytest.mark.parametrize("context_type", ["all", "not_a_context", ""])
async def test_update_writing_sample_route_rejects_invalid_context(context_type: str) -> None:
    with pytest.raises(HTTPException) as error:
        await update_writing_sample(
            "sample-1",
            UpdateWritingSampleRequest(content="Edited", context_type=context_type),
            _WritingSampleRouteService(),
        )

    assert error.value.status_code == 400
