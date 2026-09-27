"""Route-contract tests for task-owned local preview session endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_sqlite_knowledge_service
from api.routes.agent_tasks import local_preview_routes
from api.routes.agent_tasks.local_preview_routes import router as local_preview_router
from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher import (
    LocalPreviewServerLauncher,
)
from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_session_registry import (
    LocalPreviewSessionRegistry,
)
from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome


class _FakeKnowledgeService:
    def __init__(self, tasks: dict[str, object]):
        self.agent_task_service = SimpleNamespace(
            get_agent_task=AsyncMock(side_effect=lambda task_id: tasks.get(task_id)),
            get_agent_task_chain=AsyncMock(
                side_effect=lambda root_id: [
                    task for task in tasks.values()
                    if task.id == root_id or getattr(task, "root_task_id", None) == root_id
                ]
            ),
        )


def _task(*, task_id: str, artifact_id: str, path: str, root_task_id: str | None = None):
    return SimpleNamespace(
        id=task_id,
        root_task_id=root_task_id,
        status="completed",
        result_data={
            "files": [{
                "artifact_id": artifact_id,
                "name": path.rsplit("/", 1)[-1],
                "path": path,
                "kind": "file",
                "operation": "write",
            }]
        },
        execution_timeline=None,
        accumulated_artifacts=None,
    )


def _session_dto(**overrides):
    payload = {
        "session_id": "session-1",
        "agent_task_id": "task-1",
        "artifact_id": "artifact-1",
        "status": "running",
        "url": "http://127.0.0.1:4173",
        "host": "127.0.0.1",
        "port": 4173,
        "pid": 42,
        "last_error": None,
        "command": "python3",
        "args": ["-m", "http.server", "4173"],
        "cwd": "/tmp/project",
        "created_at": 1700000000.0,
        "stopped_at": None,
    }
    payload.update(overrides)
    return payload


class _FakeLauncher:
    def __init__(self, session=None):
        self.started = []
        self.stopped = []
        self._session = session or SimpleNamespace(to_dto=lambda: _session_dto())
        self._registry = SimpleNamespace(get=lambda session_id: self._session if session_id == self._session.to_dto()["session_id"] else None)

    async def start_session(self, **kwargs):
        self.started.append(kwargs)
        return self._session

    async def stop_session(self, session_id: str):
        self.stopped.append(session_id)
        stopped = SimpleNamespace(to_dto=lambda: _session_dto(status="stopped", pid=None, stopped_at=1700000005.0))
        self._session = stopped
        return stopped


def _client(knowledge, launcher, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(local_preview_router, prefix="/api/v1/agent-tasks")
    app.dependency_overrides[get_sqlite_knowledge_service] = lambda: knowledge
    monkeypatch.setattr(local_preview_routes, "get_local_preview_launcher", lambda request: launcher)
    return TestClient(app)


def test_unknown_agent_task_returns_404_before_approval(tmp_path, monkeypatch):
    artifact = tmp_path / "index.html"
    artifact.write_text("<html></html>", encoding="utf-8")
    launcher = _FakeLauncher()
    client = _client(_FakeKnowledgeService({}), launcher, monkeypatch)

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        response = client.post(
            "/api/v1/agent-tasks/missing-task/artifacts/artifact-1/local-preview/sessions",
            json={"command": "python3", "args": ["-m", "http.server", "4173"], "cwd": str(tmp_path), "port": 4173},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent Task not found."
    assert launcher.started == []
    approval_cls.assert_not_called()


def test_foreign_artifact_returns_404_before_approval(tmp_path, monkeypatch):
    owned = tmp_path / "owned.html"
    owned.write_text("<html></html>", encoding="utf-8")
    foreign = tmp_path / "foreign.html"
    foreign.write_text("<html></html>", encoding="utf-8")
    knowledge = _FakeKnowledgeService({
        "task-1": _task(task_id="task-1", artifact_id="owned-artifact", path=str(owned)),
        "task-2": _task(task_id="task-2", artifact_id="foreign-artifact", path=str(foreign)),
    })
    launcher = _FakeLauncher()
    client = _client(knowledge, launcher, monkeypatch)

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        response = client.post(
            "/api/v1/agent-tasks/task-1/artifacts/foreign-artifact/local-preview/sessions",
            json={"command": "python3", "args": ["-m", "http.server", "4173"], "cwd": str(tmp_path), "port": 4173},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Local preview artifact not found for this Agent Task."
    assert launcher.started == []
    approval_cls.assert_not_called()


def test_root_task_authorizes_an_artifact_owned_by_its_follow_up(tmp_path, monkeypatch):
    root_artifact = tmp_path / "root.html"
    root_artifact.write_text("<html></html>", encoding="utf-8")
    follow_up_artifact = tmp_path / "follow-up.html"
    follow_up_artifact.write_text("<html></html>", encoding="utf-8")
    knowledge = _FakeKnowledgeService({
        "task-1": _task(task_id="task-1", artifact_id="root-artifact", path=str(root_artifact)),
        "task-2": _task(
            task_id="task-2",
            root_task_id="task-1",
            artifact_id="follow-up-artifact",
            path=str(follow_up_artifact),
        ),
    })
    launcher = _FakeLauncher()
    client = _client(knowledge, launcher, monkeypatch)

    response = client.post(
        "/api/v1/agent-tasks/task-1/artifacts/follow-up-artifact/local-preview/sessions",
        json={"command": "python3", "args": ["-m", "http.server", "4173"], "cwd": str(tmp_path), "port": 4173},
    )

    assert response.status_code == 200
    assert launcher.started[0]["agent_task_id"] == "task-1"
    assert launcher.started[0]["artifact_id"] == "follow-up-artifact"


def test_cwd_outside_artifact_ancestry_returns_422(tmp_path, monkeypatch):
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    artifact = project / "index.html"
    artifact.write_text("<html></html>", encoding="utf-8")
    knowledge = _FakeKnowledgeService({
        "task-1": _task(task_id="task-1", artifact_id="artifact-1", path=str(artifact)),
    })
    launcher = _FakeLauncher()
    client = _client(knowledge, launcher, monkeypatch)

    response = client.post(
        "/api/v1/agent-tasks/task-1/artifacts/artifact-1/local-preview/sessions",
        json={"command": "python3", "args": ["-m", "http.server", "4173"], "cwd": str(other), "port": 4173},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Preview working directory must contain the selected task artifact."
    assert launcher.started == []


def test_denied_approval_does_not_start_a_process(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "preview-project"
    project.mkdir()
    artifact = project / "index.html"
    artifact.write_text("<html></html>", encoding="utf-8")
    knowledge = _FakeKnowledgeService({
        "task-1": _task(task_id="task-1", artifact_id="artifact-1", path=str(artifact)),
    })
    registry = LocalPreviewSessionRegistry()
    launcher = LocalPreviewServerLauncher(registry)
    client = _client(knowledge, launcher, monkeypatch)

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(
            return_value=ExecutionApprovalOutcome(approved=False, status="user_denied", reason="User denied.")
        )
        response = client.post(
            "/api/v1/agent-tasks/task-1/artifacts/artifact-1/local-preview/sessions",
            json={"command": "python3", "args": ["-m", "http.server", "4173"], "cwd": str(project), "port": 4173},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "denied"
    assert body["pid"] is None
    assert registry.get_process(body["session_id"]) is None
    approval_cls.return_value.request_approval_with_outcome.assert_awaited_once()
    assert "stdout_tail" not in body
    assert "stderr_tail" not in body


def test_session_response_includes_lifecycle_fields_and_excludes_process_tails(tmp_path, monkeypatch):
    artifact = tmp_path / "index.html"
    artifact.write_text("<html></html>", encoding="utf-8")
    knowledge = _FakeKnowledgeService({
        "task-1": _task(task_id="task-1", artifact_id="artifact-1", path=str(artifact)),
    })
    launcher = _FakeLauncher()
    client = _client(knowledge, launcher, monkeypatch)

    response = client.post(
        "/api/v1/agent-tasks/task-1/artifacts/artifact-1/local-preview/sessions",
        json={"command": "python3", "args": ["-m", "http.server", "4173"], "cwd": str(tmp_path), "port": 4173},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["command"] == "python3"
    assert body["args"] == ["-m", "http.server", "4173"]
    assert body["cwd"] == "/tmp/project"
    assert body["created_at"] == 1700000000.0
    assert body["stopped_at"] is None
    assert "stdout_tail" not in body
    assert "stderr_tail" not in body
    assert launcher.started[0]["agent_task_id"] == "task-1"
    assert launcher.started[0]["artifact_id"] == "artifact-1"


def test_get_and_stop_reject_mismatched_owners(tmp_path, monkeypatch):
    artifact = tmp_path / "index.html"
    artifact.write_text("<html></html>", encoding="utf-8")
    session = SimpleNamespace(
        agent_task_id="task-1",
        artifact_id="artifact-1",
        to_dto=lambda: _session_dto(),
    )
    launcher = _FakeLauncher(session)
    knowledge = _FakeKnowledgeService({
        "task-1": _task(task_id="task-1", artifact_id="artifact-1", path=str(artifact)),
    })
    client = _client(knowledge, launcher, monkeypatch)

    mismatched = client.get(
        "/api/v1/agent-tasks/task-2/artifacts/artifact-1/local-preview/sessions/session-1"
    )
    assert mismatched.status_code == 404
    stop = client.post(
        "/api/v1/agent-tasks/task-1/artifacts/other-artifact/local-preview/sessions/session-1/stop"
    )
    assert stop.status_code == 404
    assert launcher.stopped == []
