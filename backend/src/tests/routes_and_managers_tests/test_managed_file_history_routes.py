"""Managed file-history routes: versions listing and restore."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.service import (
    AgentTaskMutations,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.dependencies import get_managed_file_history_service_for_routes
from api.routes.agent_tasks.managed_file_history_routes import router
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.blob_store import (
    ManagedHistoryBlobStore,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_service import (
    ManagedFileHistoryService,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
    LocalTextFileWriter,
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "routes.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()

    service = ManagedFileHistoryService(
        db_path=db_path,
        blob_store=ManagedHistoryBlobStore(tmp_path / "blobs"),
        text_writer=LocalTextFileWriter([tmp_path]),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/agent-tasks")
    app.dependency_overrides[get_managed_file_history_service_for_routes] = lambda: service
    app.state._test_service = service
    app.state._test_db_path = db_path
    app.state._test_tmp_path = tmp_path
    return TestClient(app)


async def _seed(client: TestClient, task_id: str, canonical_path: Path, content: str) -> str:
    mutations = AgentTaskMutations(client.app.state._test_db_path)
    await mutations.store_agent_task(agent_task_id=task_id, original_prompt="p", transcribed_prompt="p")
    result = await client.app.state._test_service.apply_managed_write(
        root_task_id=task_id, agent_task_id=task_id, path=str(canonical_path), content=content, mode="create",
    )
    assert result["success"] is True
    return canonical_path.resolve().as_posix()


@pytest.mark.asyncio
async def test_list_versions_returns_created_change(client: TestClient) -> None:
    tmp_path: Path = client.app.state._test_tmp_path
    target = tmp_path / "doc.txt"
    canonical = await _seed(client, "route-task-1", target, "hello")

    response = client.get("/api/v1/agent-tasks/managed-file-history/versions", params={"canonical_path": canonical})
    assert response.status_code == 200
    body = response.json()
    assert body["canonical_path"] == canonical
    assert len(body["versions"]) == 1
    assert body["versions"][0]["operation"] == "create"
    assert body["versions"][0]["root_task_id"] == "route-task-1"
    assert body["versions"][0]["agent_task_id"] == "route-task-1"


@pytest.mark.asyncio
async def test_restore_endpoint_restores_and_returns_success(client: TestClient) -> None:
    tmp_path: Path = client.app.state._test_tmp_path
    target = tmp_path / "restorable.txt"
    canonical = await _seed(client, "route-task-2", target, "v1")
    await client.app.state._test_service.apply_managed_write(
        root_task_id="route-task-2", agent_task_id="route-task-2", path=str(target), content="v2", mode="overwrite",
    )
    versions = client.get(
        "/api/v1/agent-tasks/managed-file-history/versions", params={"canonical_path": canonical},
    ).json()["versions"]
    assert versions[0]["operation"] == "overwrite"
    assert versions[0]["root_task_id"] == "route-task-2"
    assert versions[0]["agent_task_id"] == "route-task-2"
    v1_change_id = versions[1]["id"]

    response = client.post(
        "/api/v1/agent-tasks/managed-file-history/restore",
        json={"root_task_id": "route-task-2", "canonical_path": canonical, "restores_change_id": v1_change_id},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert target.read_text() == "v1"

    versions_after_restore = client.get(
        "/api/v1/agent-tasks/managed-file-history/versions", params={"canonical_path": canonical},
    ).json()["versions"]
    assert versions_after_restore[0]["operation"] == "rollback"
    assert versions_after_restore[0]["root_task_id"] == "route-task-2"
    assert versions_after_restore[0]["agent_task_id"] == "route-task-2"


@pytest.mark.asyncio
async def test_version_content_endpoint_returns_snapshot_text(client: TestClient) -> None:
    tmp_path: Path = client.app.state._test_tmp_path
    target = tmp_path / "content.txt"
    canonical = await _seed(client, "route-task-content", target, "v1")
    await client.app.state._test_service.apply_managed_write(
        root_task_id="route-task-content",
        agent_task_id="route-task-content",
        path=str(target),
        content="v2",
        mode="overwrite",
    )
    current_change_id = client.get(
        "/api/v1/agent-tasks/managed-file-history/versions",
        params={"canonical_path": canonical},
    ).json()["versions"][0]["id"]

    response = client.get(
        f"/api/v1/agent-tasks/managed-file-history/versions/{current_change_id}/content"
    )

    assert response.status_code == 200
    assert response.json()["content"] == "v2"
    assert response.json()["truncated"] is False


@pytest.mark.asyncio
async def test_restore_endpoint_returns_409_for_unknown_version(client: TestClient) -> None:
    tmp_path: Path = client.app.state._test_tmp_path
    target = tmp_path / "unknown.txt"
    canonical = await _seed(client, "route-task-3", target, "v1")

    response = client.post(
        "/api/v1/agent-tasks/managed-file-history/restore",
        json={"root_task_id": "route-task-3", "canonical_path": canonical, "restores_change_id": "does-not-exist"},
    )
    assert response.status_code == 409
