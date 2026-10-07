from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.runtime.validation_profile import (
    ValidationRuntimeConfigurationError,
    ValidationRuntimeProfile,
    is_validation_runtime,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_routing_service import (
    AgentTaskRoutingService,
)
from api.services.agent_processing.lifecycle.runtime.delegated_agent_result_bridge import (
    DelegatedAgentResultBridge,
)
from api.services.validation.fixture_service import ValidationFixtureService


class _FakeWebSocketManager:
    def __init__(self) -> None:
        self.messages: list[object] = []

    async def broadcast(self, message: object) -> None:
        self.messages.append(message)
        return None


def _validation_environment(session_root: Path) -> dict[str, str]:
    return {
        "BASIL_RUNTIME_PROFILE": "validation",
        "BASIL_VALIDATION_SESSION_ROOT": str(session_root),
        "BASIL_HOST": "127.0.0.1",
        "BASIL_PORT": "8765",
        "BASIL_VALIDATION_SESSION_TOKEN": "fixture-token",
    }


def test_validation_profile_owns_only_the_synthetic_session_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions" / "live-preview"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))

    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    profile.ensure_directories()

    assert profile.session_home == session_home
    assert profile.data_root == session_home / ".basil" / "data"
    assert profile.owns(profile.data_root)
    assert not profile.owns(tmp_path / "normal-basil")


def test_validation_profile_rejects_a_non_session_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions" / "live-preview"
    (session_root / "home").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "normal-home"))

    with pytest.raises(
        ValidationRuntimeConfigurationError,
        match="synthetic home",
    ):
        ValidationRuntimeProfile.from_environment(
            _validation_environment(session_root)
        )


def test_validation_runtime_detection_requires_the_exact_profile() -> None:
    assert is_validation_runtime({"BASIL_RUNTIME_PROFILE": "validation"})
    assert not is_validation_runtime({"BASIL_RUNTIME_PROFILE": "Validation"})
    assert not is_validation_runtime({})


def test_validation_fixtures_include_an_ordered_multi_run_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions" / "history-fixture"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))
    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    service = ValidationFixtureService(profile, knowledge_service=None)  # type: ignore[arg-type]
    documents = {
        "markdown": tmp_path / "run-summary.md",
        "text": tmp_path / "notes.txt",
        "code": tmp_path / "preview.py",
        "html": tmp_path / "report.html",
        "html_css": tmp_path / "report.css",
        "html_js": tmp_path / "report.js",
        "local_preview_html": tmp_path / "local-preview" / "index.html",
        "local_preview_server": tmp_path / "local-preview" / "server.py",
        "pdf": tmp_path / "live-preview.pdf",
        "managed_history": tmp_path / "managed-history-fixture.txt",
        "managed_history_html": tmp_path / "managed-history-html-fixture.html",
    }

    fixtures = {fixture["id"]: fixture for fixture in service._fixture_definitions(documents)}

    managed_history_files = fixtures[service.managed_history_fixture_id]["result_data"][
        "finalizer_result"
    ]["result_payload"]["files"]
    assert {file["path"] for file in managed_history_files} == {
        str(documents["managed_history"]),
        str(documents["managed_history_html"]),
    }

    assert fixtures[service.run_history_fixture_id]["chain_sequence_number"] == 0
    assert {
        key: fixtures["validation-run-history-follow-up-1"][key]
        for key in ("root_task_id", "previous_task_id", "chain_sequence_number")
    } == {
        "root_task_id": service.run_history_fixture_id,
        "previous_task_id": service.run_history_fixture_id,
        "chain_sequence_number": 1,
    }
    assert {
        key: fixtures["validation-run-history-follow-up-2"][key]
        for key in ("root_task_id", "previous_task_id", "chain_sequence_number")
    } == {
        "root_task_id": service.run_history_fixture_id,
        "previous_task_id": "validation-run-history-follow-up-1",
        "chain_sequence_number": 2,
    }
    assert fixtures[service.local_preview_fixture_id]["root_task_id"] == service.local_preview_fixture_id


@pytest.mark.asyncio
async def test_pdf_fixture_mutation_is_atomic_and_advances_its_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions" / "live-preview"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))
    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    service = ValidationFixtureService(profile, knowledge_service=None)  # type: ignore[arg-type]
    documents = service._write_documents(revision=1)
    service.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    service.manifest_path.write_text(
        '{"pdfFixtureID":"validation-pdf-live","pdfPath":"' + str(documents["pdf"]) + '","pdfRevision":1}',
        encoding="utf-8",
    )
    before = documents["pdf"].read_bytes()

    result = await service.mutate(service.pdf_fixture_id)

    assert result["revision"] == 2
    assert documents["pdf"].read_bytes() != before
    assert '"pdfRevision": 2' in service.manifest_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_html_fixture_mutation_replaces_rendered_revision_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions" / "live-html-preview"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))
    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    service = ValidationFixtureService(profile, knowledge_service=None)  # type: ignore[arg-type]
    documents = service._write_documents(revision=1, html_revision=1)
    service.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    service.manifest_path.write_text(
        '{"pdfFixtureID":"validation-pdf-live","pdfPath":"' + str(documents["pdf"])
        + '","pdfRevision":1,"htmlFixtureID":"validation-html-live","htmlPath":"'
        + str(documents["html"]) + '","htmlRevision":1}',
        encoding="utf-8",
    )
    before = documents["html"].read_text(encoding="utf-8")

    result = await service.mutate(service.html_fixture_id)

    after = documents["html"].read_text(encoding="utf-8")
    assert result["revision"] == 2
    assert before != after
    assert '<output id="fixture-revision">2</output>' in after
    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    assert manifest["htmlRevision"] == 2
    assert manifest["pdfRevision"] == 1


@pytest.mark.asyncio
async def test_local_preview_fixture_mutation_replaces_rendered_revision_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions" / "local-preview"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))
    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    service = ValidationFixtureService(profile, knowledge_service=None)  # type: ignore[arg-type]
    documents = service._write_documents(
        revision=1,
        html_revision=1,
        local_preview_revision=1,
    )
    service.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    service.manifest_path.write_text(
        '{"pdfFixtureID":"validation-pdf-live","pdfPath":"' + str(documents["pdf"])
        + '","pdfRevision":1,"htmlFixtureID":"validation-html-live","htmlPath":"'
        + str(documents["html"])
        + '","htmlRevision":1,"localPreviewFixtureID":"validation-local-preview",'
        + '"localPreviewArtifactID":"validation-index","localPreviewPath":"'
        + str(documents["local_preview_html"])
        + '","localPreviewRevision":1}',
        encoding="utf-8",
    )
    before = documents["local_preview_html"].read_text(encoding="utf-8")

    result = await service.mutate(service.local_preview_fixture_id)

    after = documents["local_preview_html"].read_text(encoding="utf-8")
    assert result == {
        "fixtureID": service.local_preview_fixture_id,
        "path": str(documents["local_preview_html"]),
        "revision": 2,
    }
    assert before != after
    assert '<output id="local-preview-revision">2</output>' in after
    assert 'href="app.css"' in after
    assert 'src="app.js"' in after
    assert "BASIL_PREVIEW_RENDERED" in documents["local_preview_js"].read_text(
        encoding="utf-8"
    )
    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    assert manifest["localPreviewRevision"] == 2
    assert manifest["htmlRevision"] == 1


@pytest.mark.asyncio
async def test_managed_history_fixture_mutation_advances_both_artifacts_in_newest_first_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.blob_store import (
        ManagedHistoryBlobStore,
    )
    from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_service import (
        ManagedFileHistoryService,
    )
    from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
        LocalTextFileWriter,
    )

    session_root = tmp_path / "sessions" / "managed-history"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))
    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    knowledge_service = SQLiteKnowledgeService(session_root / "managed-history.db")
    fixture_service = ValidationFixtureService(profile, knowledge_service)

    manifest = await fixture_service.seed()
    text_path = Path(manifest["managedHistoryPath"])
    html_path = Path(manifest["managedHistoryHTMLPath"])

    first_mutation = await fixture_service.mutate(fixture_service.managed_history_fixture_id)
    second_mutation = await fixture_service.mutate(fixture_service.managed_history_fixture_id)

    assert first_mutation["version"] == 2
    assert second_mutation["version"] == 3
    assert first_mutation["path"] == str(text_path)
    assert first_mutation["htmlPath"] == str(html_path)

    history_service = ManagedFileHistoryService(
        db_path=knowledge_service.db_path,
        blob_store=ManagedHistoryBlobStore(profile.data_root / "managed_file_history" / "blobs"),
        text_writer=LocalTextFileWriter([profile.fixtures_root]),
    )

    text_versions = await history_service.list_versions(str(text_path.resolve()))
    assert len(text_versions) == 2
    text_contents = [
        (await history_service.get_version_content(version["id"]))["content"]
        for version in text_versions
    ]
    assert text_contents[0] == "Managed history fixture v3\n"
    assert text_contents[1] == "Managed history fixture v2\n"

    html_versions = await history_service.list_versions(str(html_path.resolve()))
    assert len(html_versions) == 2
    html_contents = [
        (await history_service.get_version_content(version["id"]))["content"]
        for version in html_versions
    ]
    assert '<output id="managed-history-html-revision">3</output>' in html_contents[0]
    assert '<output id="managed-history-html-revision">2</output>' in html_contents[1]

    restored = await history_service.restore_version(
        root_task_id=fixture_service.managed_history_fixture_id,
        canonical_path=str(text_path.resolve()),
        restores_change_id=text_versions[1]["id"],
        agent_task_id=fixture_service.managed_history_fixture_id,
    )

    assert restored["success"] is True
    assert text_path.read_text(encoding="utf-8") == "Managed history fixture v2\n"
    restored_versions = await history_service.list_versions(str(text_path.resolve()))
    assert len(restored_versions) == 3
    assert restored_versions[0]["operation"] == "rollback"
    assert restored_versions[0]["origin"] == "user"
    assert restored_versions[0]["restores_change_id"] == text_versions[1]["id"]


@pytest.mark.asyncio
async def test_unknown_fixture_mutation_leaves_artifacts_and_revisions_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "sessions" / "unknown-fixture"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))
    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    service = ValidationFixtureService(profile, knowledge_service=None)  # type: ignore[arg-type]
    documents = service._write_documents(revision=1, html_revision=1)
    service.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    service.manifest_path.write_text(
        '{"pdfFixtureID":"validation-pdf-live","pdfPath":"' + str(documents["pdf"])
        + '","pdfRevision":1,"htmlFixtureID":"validation-html-live","htmlPath":"'
        + str(documents["html"]) + '","htmlRevision":1}',
        encoding="utf-8",
    )
    manifest_before = service.manifest_path.read_text(encoding="utf-8")
    html_before = documents["html"].read_bytes()
    pdf_before = documents["pdf"].read_bytes()

    with pytest.raises(ValueError, match="Unknown validation fixture"):
        await service.mutate("not-a-validation-fixture")

    assert service.manifest_path.read_text(encoding="utf-8") == manifest_before
    assert documents["html"].read_bytes() == html_before
    assert documents["pdf"].read_bytes() == pdf_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture_id", "artifact_id", "display_name"),
    [
        (
            ValidationFixtureService.html_fixture_id,
            "validation-report",
            "report.html",
        ),
        (
            ValidationFixtureService.local_preview_fixture_id,
            ValidationFixtureService.local_preview_artifact_id,
            "index.html",
        ),
    ],
)
async def test_validation_fixture_mutation_publishes_matching_artifact_event(
    monkeypatch: pytest.MonkeyPatch,
    fixture_id: str,
    artifact_id: str,
    display_name: str,
) -> None:
    from api.routes import validation_routes

    fixture_service = SimpleNamespace(
        mutate=AsyncMock(
            return_value={
                "fixtureID": fixture_id,
                "path": f"/fixtures/{display_name}",
                "revision": 2,
            }
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                validation_fixture_service=fixture_service,
                wake_word_service=SimpleNamespace(broadcast=AsyncMock()),
            )
        )
    )
    broadcast = AsyncMock()
    monkeypatch.setattr(
        validation_routes,
        "broadcast_workflow_notification",
        broadcast,
    )

    mutation = await validation_routes.mutate_validation_fixture(
        fixture_id,
        request,
        SimpleNamespace(),
    )

    assert mutation["revision"] == 2
    fixture_service.mutate.assert_awaited_once_with(fixture_id)
    broadcast.assert_awaited_once()
    _, payload = broadcast.await_args.args
    assert payload["event_type"] == "agent_task_artifact"
    assert payload["agent_task_id"] == fixture_id
    assert payload["root_task_id"] == fixture_id
    assert payload["agent_task_artifact"] == {
        "artifact_id": artifact_id,
        "display_name": display_name,
        "local_path": f"/fixtures/{display_name}",
        "artifact_kind": "file",
        "operation": "modify",
        "lifecycle": "verified",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "verified",
            "summary": (
                "Validation local-preview fixture revision 2 is ready."
                if fixture_id == ValidationFixtureService.local_preview_fixture_id
                else "Validation HTML fixture revision 2 is ready."
            ),
        },
    }


@pytest.mark.asyncio
async def test_managed_history_fixture_mutation_publishes_two_correlated_artifact_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.routes import validation_routes

    fixture_id = ValidationFixtureService.managed_history_fixture_id
    fixture_service = SimpleNamespace(
        mutate=AsyncMock(
            return_value={
                "fixtureID": fixture_id,
                "path": "/fixtures/managed-history-fixture.txt",
                "htmlPath": "/fixtures/managed-history-html-fixture.html",
                "version": 2,
            }
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                validation_fixture_service=fixture_service,
                wake_word_service=SimpleNamespace(broadcast=AsyncMock()),
            )
        )
    )
    broadcast = AsyncMock()
    monkeypatch.setattr(
        validation_routes,
        "broadcast_workflow_notification",
        broadcast,
    )

    mutation = await validation_routes.mutate_validation_fixture(
        fixture_id,
        request,
        SimpleNamespace(),
    )

    assert mutation["version"] == 2
    fixture_service.mutate.assert_awaited_once_with(fixture_id)
    assert broadcast.await_count == 2

    text_call, html_call = broadcast.await_args_list
    _, text_payload = text_call.args
    _, html_payload = html_call.args

    assert text_payload["event_type"] == "agent_task_artifact"
    assert text_payload["agent_task_id"] == fixture_id
    assert text_payload["root_task_id"] == fixture_id
    assert text_payload["agent_task_artifact"] == {
        "artifact_id": "validation-managed-history-fixture",
        "display_name": "managed-history-fixture.txt",
        "local_path": "/fixtures/managed-history-fixture.txt",
        "artifact_kind": "file",
        "operation": "modify",
        "lifecycle": "verified",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "verified",
            "summary": "Validation managed-history text fixture revision 2 is ready.",
        },
    }

    assert html_payload["event_type"] == "agent_task_artifact"
    assert html_payload["agent_task_id"] == fixture_id
    assert html_payload["root_task_id"] == fixture_id
    assert html_payload["agent_task_artifact"] == {
        "artifact_id": "validation-managed-history-html-fixture",
        "display_name": "managed-history-html-fixture.html",
        "local_path": "/fixtures/managed-history-html-fixture.html",
        "artifact_kind": "file",
        "operation": "modify",
        "lifecycle": "verified",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "verified",
            "summary": "Validation managed-history HTML fixture revision 2 is ready.",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "expected_interaction_kind", "expected_event_type"),
    [
        ("form", "provider_user_input", "collaborative_checkpoint_request"),
        ("permission", "provider_permission", "execution_approval_request"),
    ],
)
async def test_validation_provider_interaction_fixtures_publish_through_the_real_routing_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
    expected_interaction_kind: str,
    expected_event_type: str,
) -> None:
    session_root = tmp_path / "sessions" / "provider-form"
    session_home = session_root / "home"
    session_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(session_home))
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[2]))
    profile = ValidationRuntimeProfile.from_environment(
        _validation_environment(session_root)
    )
    knowledge_service = SQLiteKnowledgeService(session_root / "provider-form.db")
    fixture_service = ValidationFixtureService(profile, knowledge_service)
    websocket_manager = _FakeWebSocketManager()
    routing_service = AgentTaskRoutingService(
        db_service=knowledge_service,
        websocket_manager=websocket_manager,
    )
    routing_service.set_provider_delegation_result_bridge(
        DelegatedAgentResultBridge(
            delegated_agent_repository=knowledge_service.delegated_agent_repository,
            delegated_agent_controller=object(),
        )
    )

    started = await fixture_service.start_provider_interaction_fixture(
        scenario=scenario,
        routing_service=routing_service,
    )

    task_id = started["agentTaskID"]
    assert Path(started["workspaceRoot"]).is_relative_to(profile.fixtures_root)
    running_task = fixture_service._provider_interaction_tasks[task_id]
    interaction = None
    async with asyncio.timeout(5.0):
        while interaction is None:
            if scenario == "permission":
                approval_event = next(
                    (
                        message
                        for message in websocket_manager.messages
                        if isinstance(message, dict)
                        and message.get("event_type") == expected_event_type
                    ),
                    None,
                )
                if isinstance(approval_event, dict):
                    interaction_id = approval_event.get("approval_id")
                    if isinstance(interaction_id, str):
                        interaction = await knowledge_service.provider_interaction_repository.get_interaction(
                            interaction_id
                        )
            else:
                interaction = await knowledge_service.provider_interaction_repository.get_pending_interaction_for_agent_task(
                    task_id
                )
            if interaction is None:
                await asyncio.sleep(0)

    assert interaction["interaction_kind"] == expected_interaction_kind
    assert any(
        isinstance(message, dict)
        and message.get("event_type") == expected_event_type
        for message in websocket_manager.messages
    )
    running_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running_task

    refreshed = await knowledge_service.provider_interaction_repository.get_interaction(
        str(interaction["id"])
    )
    assert refreshed is not None
    assert refreshed["status"] in {"canceled", "superseded"}


@pytest.mark.asyncio
async def test_validation_provider_permission_request_publishes_through_the_real_routing_service(
    tmp_path: Path,
) -> None:
    knowledge_service = SQLiteKnowledgeService(tmp_path / "provider-permission.db")
    agent_task_id = "validation-provider-permission"
    await knowledge_service.agent_task_service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="Validate provider permission delivery.",
        transcribed_prompt="Validate provider permission delivery.",
        status="processing",
        root_task_id=agent_task_id,
    )
    websocket_manager = _FakeWebSocketManager()
    routing_service = AgentTaskRoutingService(
        db_service=knowledge_service,
        websocket_manager=websocket_manager,
    )
    routing_service.set_provider_delegation_result_bridge(
        DelegatedAgentResultBridge(
            delegated_agent_repository=knowledge_service.delegated_agent_repository,
            delegated_agent_controller=object(),
        )
    )

    published = await routing_service.publish_provider_permission_request(
        agent_task_id=agent_task_id,
        root_task_id=agent_task_id,
        previous_task_id=None,
        interaction_id="permission-interaction-1",
        provider_run_id="provider-run-1",
        title="Allow the isolated validation action?",
        description="Validation-only provider permission request.",
        subject={"type": "command", "command": "true", "cwd": str(tmp_path)},
        allow_option_id="allow-once",
        reject_option_id="reject-once",
    )

    assert published is True
    timeline_steps = [
        message
        for message in websocket_manager.messages
        if isinstance(message, dict) and message.get("event_type") == "agent_task_step_detail"
    ]
    assert len(timeline_steps) == 1
    assert timeline_steps[0]["agent_task_id"] == agent_task_id
    assert timeline_steps[0]["correlation_id"] == "user_interaction_permission-interaction-1"
    assert timeline_steps[0]["metadata"]["user_interaction"]["kind"] == "provider_permission"
    assert timeline_steps[0]["metadata"]["user_interaction"]["status"] == "waiting"
    approval_requests = [
        message
        for message in websocket_manager.messages
        if isinstance(message, dict) and message.get("event_type") == "execution_approval_request"
    ]
    assert len(websocket_manager.messages) == len(timeline_steps) + len(approval_requests)
    assert approval_requests == [{
        "event_type": "execution_approval_request",
        "agent_task_id": agent_task_id,
        "approval_id": "permission-interaction-1",
        "command": "Allow the isolated validation action?",
        "reason": "Validation-only provider permission request.",
        "risk_level": "medium",
        "execution_type": "provider_permission",
        "provider_permission": {
            "interaction_id": "permission-interaction-1",
            "provider_run_id": "provider-run-1",
            "agent_task_id": agent_task_id,
            "subject": {"type": "command", "command": "true", "cwd": str(tmp_path)},
            "allow_option_id": "allow-once",
            "reject_option_id": "reject-once",
        },
        "root_task_id": agent_task_id,
    }]
