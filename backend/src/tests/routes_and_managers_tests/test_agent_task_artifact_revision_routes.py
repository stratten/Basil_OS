"""HTTP-level coverage for read-only, task-owned artifact revision routes."""

import pytest
from fastapi.testclient import TestClient

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.dependencies import get_sqlite_knowledge_service
from api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    service = SQLiteKnowledgeService(tmp_path / "artifact-revision-routes.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    app.dependency_overrides[get_sqlite_knowledge_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_sqlite_knowledge_service, None)


async def _seed_task_with_revision(client: TestClient) -> tuple[str, SQLiteKnowledgeService]:
    service = app.dependency_overrides[get_sqlite_knowledge_service]()
    await service.store_agent_task(
        agent_task_id="task-revision-routes",
        original_prompt="Create a report",
        transcribed_prompt="Create a report",
        status="processing",
    )
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations import (
        revision_repository,
    )
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
        run_write_transaction,
    )

    def _insert(conn):
        return revision_repository.insert_artifact_revision(
            conn,
            agent_task_id="task-revision-routes",
            artifact_id="artifact-1",
            local_path="/tmp/report.md",
            display_name="report.md",
            content_kind="markdown",
            content_sha256="a" * 64,
            content="# v1",
            byte_count=4,
        )

    run_write_transaction(service.db_path, "seed_revision", _insert)
    return "task-revision-routes", service


def test_list_revisions_returns_newest_first_metadata(client: TestClient) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_task_with_revision(client))

    response = client.get("/api/v1/agent-tasks/task-revision-routes/artifacts/artifact-1/revisions")

    assert response.status_code == 200
    body = response.json()
    assert len(body["revisions"]) == 1
    assert body["revisions"][0]["revision"] == 1
    assert body["revisions"][0]["content_kind"] == "markdown"
    assert "content" not in body["revisions"][0]


def test_get_revision_returns_content(client: TestClient) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_task_with_revision(client))

    response = client.get(
        "/api/v1/agent-tasks/task-revision-routes/artifacts/artifact-1/revisions/1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "# v1"
    assert body["content_sha256"] == "a" * 64


def test_get_missing_revision_returns_404(client: TestClient) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_task_with_revision(client))

    response = client.get(
        "/api/v1/agent-tasks/task-revision-routes/artifacts/artifact-1/revisions/9"
    )

    assert response.status_code == 404


def test_list_revisions_for_missing_task_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/agent-tasks/missing-task/artifacts/artifact-1/revisions")

    assert response.status_code == 404


def test_list_revisions_for_mismatched_artifact_is_owned_and_empty(client: TestClient) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_task_with_revision(client))

    response = client.get(
        "/api/v1/agent-tasks/task-revision-routes/artifacts/other-artifact/revisions"
    )

    assert response.status_code == 200
    assert response.json()["revisions"] == []


def test_existing_task_detail_route_is_unaffected_by_revision_routes(client: TestClient) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_task_with_revision(client))

    response = client.get("/api/v1/agent-tasks/task-revision-routes")

    assert response.status_code == 200
    assert response.json()["id"] == "task-revision-routes"
