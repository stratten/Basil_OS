"""`/api/v1/todos` route coverage: full CRUD/transition surface, optimistic-
concurrency 409s (including the structured conflict body), malformed and
oversized requests (Pydantic `extra=forbid` / field-length validators), the
worker-launch 503-when-no-bridge and 409-for-candidate paths, and idempotent
meeting-proposal promotion."""

from pathlib import Path
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_todo_service
from api.routes.todos import router as todos_router
from api.routes.todos import routes as todos_routes_module
from api.services.todos.agent_task_bridge import TodoAgentTaskBridge, set_todo_agent_task_bridge
from api.services.todos.repository import TodoRepository
from api.services.todos.service import TodoService


class FakeAgentTaskLookup:
    def __init__(self) -> None:
        self.statuses_by_todo_id: dict[str, dict] = {}

    async def list_agent_tasks_by_origin(self, origin_type: str, origin_id: str, include_terminal: bool = True):
        return []

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str):
        return []

    async def get_agent_task(self, agent_task_id: str):
        return None

    async def list_latest_agent_task_status_by_origins(self, origin_type: str, origin_ids: list[str]):
        return {
            todo_id: self.statuses_by_todo_id[todo_id]
            for todo_id in origin_ids
            if todo_id in self.statuses_by_todo_id
        }


def _build_client(tmp_path: Path) -> tuple[TestClient, TodoService]:
    service = TodoService(
        repository=TodoRepository(str(tmp_path / "routes.db")), agent_task_service=FakeAgentTaskLookup(),
    )
    app = FastAPI()
    app.include_router(todos_router)
    app.dependency_overrides[get_todo_service] = lambda: service
    set_todo_agent_task_bridge(None)  # default: no bridge registered
    return TestClient(app), service


@pytest.fixture
def client_and_service(tmp_path: Path):
    return _build_client(tmp_path)


def test_get_workspace_returns_empty_hydration_initially(client_and_service) -> None:
    client, _ = client_and_service
    response = client.get("/api/v1/todos/workspace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["counts_by_status"] == {}


def test_create_item_then_list_and_get(client_and_service) -> None:
    client, _ = client_and_service
    create_response = client.post(
        "/api/v1/todos/items",
        json={"title": "Draft the follow-up email", "idempotency_key": "create-item"},
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "open"

    list_response = client.get("/api/v1/todos/items")
    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 1

    get_response = client.get(f"/api/v1/todos/items/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Draft the follow-up email"


def test_workspace_defaults_to_creation_order_and_accepts_updated_order(client_and_service) -> None:
    client, service = client_and_service
    first = client.post("/api/v1/todos/items", json={"title": "First", "idempotency_key": "first"}).json()
    second = client.post("/api/v1/todos/items", json={"title": "Second", "idempotency_key": "second"}).json()
    connection = service.repository._connection()
    try:
        connection.execute(
            "UPDATE todo_items SET created_at = ?, updated_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", first["id"]),
        )
        connection.execute(
            "UPDATE todo_items SET created_at = ?, updated_at = ? WHERE id = ?",
            ("2026-02-01T00:00:00Z", "2026-01-01T00:00:00Z", second["id"]),
        )
        connection.commit()
    finally:
        connection.close()

    default_order = client.get("/api/v1/todos/workspace")
    updated_order = client.get("/api/v1/todos/workspace?sort_by=updated_at")
    invalid_order = client.get("/api/v1/todos/workspace?sort_by=not_a_real_column")

    assert [item["id"] for item in default_order.json()["items"]] == [second["id"], first["id"]]
    assert [item["id"] for item in updated_order.json()["items"]] == [first["id"], second["id"]]
    assert invalid_order.status_code == 422


def test_workspace_accepts_due_date_order_with_nulls_last(client_and_service) -> None:
    client, _ = client_and_service
    undated = client.post(
        "/api/v1/todos/items", json={"title": "No due date", "idempotency_key": "undated"},
    ).json()
    later = client.post(
        "/api/v1/todos/items",
        json={"title": "Due later", "idempotency_key": "later", "due_at": "2026-01-20T00:00:00.000Z"},
    ).json()
    soon = client.post(
        "/api/v1/todos/items",
        json={"title": "Due soon", "idempotency_key": "soon", "due_at": "2026-01-05T00:00:00.000Z"},
    ).json()

    response = client.get("/api/v1/todos/workspace?sort_by=due_at")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [soon["id"], later["id"], undated["id"]]


def test_workspace_sorts_by_title_ascending_case_insensitively(client_and_service) -> None:
    client, _ = client_and_service
    lower = client.post(
        "/api/v1/todos/items", json={"title": "apple task", "idempotency_key": "lower"},
    ).json()
    upper = client.post(
        "/api/v1/todos/items", json={"title": "Banana task", "idempotency_key": "upper"},
    ).json()
    other = client.post(
        "/api/v1/todos/items", json={"title": "cherry task", "idempotency_key": "other"},
    ).json()

    response = client.get("/api/v1/todos/workspace?sort_by=title")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [lower["id"], upper["id"], other["id"]]


def test_workspace_sorts_by_priority_high_first_by_default(client_and_service) -> None:
    client, _ = client_and_service
    low = client.post(
        "/api/v1/todos/items", json={"title": "Low", "priority": "low", "idempotency_key": "low"},
    ).json()
    high = client.post(
        "/api/v1/todos/items", json={"title": "High", "priority": "high", "idempotency_key": "high"},
    ).json()
    normal = client.post(
        "/api/v1/todos/items", json={"title": "Normal", "priority": "normal", "idempotency_key": "normal"},
    ).json()

    response = client.get("/api/v1/todos/workspace?sort_by=priority")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [high["id"], normal["id"], low["id"]]


def test_workspace_sorts_by_status_workflow_order_by_default(client_and_service) -> None:
    client, _ = client_and_service
    open_item = client.post(
        "/api/v1/todos/items", json={"title": "Open one", "idempotency_key": "open-one"},
    ).json()
    completed_item = client.post(
        "/api/v1/todos/items", json={"title": "Completed one", "idempotency_key": "completed-one"},
    ).json()
    client.post(
        f"/api/v1/todos/items/{completed_item['id']}/complete",
        json={"expected_revision": completed_item["revision"]},
    )

    response = client.get("/api/v1/todos/workspace?sort_by=status")

    assert response.status_code == 200
    ids_in_order = [item["id"] for item in response.json()["items"]]
    assert ids_in_order.index(open_item["id"]) < ids_in_order.index(completed_item["id"])


def test_workspace_explicit_sort_direction_overrides_column_default(client_and_service) -> None:
    client, _ = client_and_service
    first = client.post(
        "/api/v1/todos/items", json={"title": "First created", "idempotency_key": "first"},
    ).json()
    second = client.post(
        "/api/v1/todos/items", json={"title": "Second created", "idempotency_key": "second"},
    ).json()

    ascending = client.get("/api/v1/todos/workspace?sort_by=created_at&sort_direction=asc").json()["items"]
    descending = client.get("/api/v1/todos/workspace?sort_by=created_at&sort_direction=desc").json()["items"]

    assert [item["id"] for item in ascending] == [first["id"], second["id"]]
    assert [item["id"] for item in descending] == [second["id"], first["id"]]


def test_workspace_due_date_nulls_last_regardless_of_explicit_direction(client_and_service) -> None:
    client, _ = client_and_service
    undated = client.post(
        "/api/v1/todos/items", json={"title": "No due date", "idempotency_key": "undated-desc"},
    ).json()
    dated = client.post(
        "/api/v1/todos/items",
        json={"title": "Due dated", "idempotency_key": "dated-desc", "due_at": "2026-01-20T00:00:00.000Z"},
    ).json()

    response = client.get("/api/v1/todos/workspace?sort_by=due_at&sort_direction=desc")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [dated["id"], undated["id"]]


def test_workspace_page_filters_statuses_and_returns_a_clear_error_for_an_invalid_cursor(client_and_service) -> None:
    client, _ = client_and_service
    open_item = client.post(
        "/api/v1/todos/items", json={"title": "Open item", "idempotency_key": "workspace-open"},
    ).json()
    completed_item = client.post(
        "/api/v1/todos/items", json={"title": "Completed item", "idempotency_key": "workspace-completed"},
    ).json()
    client.post(
        f"/api/v1/todos/items/{completed_item['id']}/complete",
        json={"expected_revision": completed_item["revision"]},
    )

    filtered = client.get("/api/v1/todos/workspace?status=open&limit=1")
    invalid_cursor = client.get("/api/v1/todos/workspace?cursor=not-a-cursor")

    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [open_item["id"]]
    assert filtered.json()["has_more"] is False
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json() == {"detail": "Invalid To-Do workspace cursor"}


def test_todo_agent_status_endpoint_reflects_active_worker(client_and_service) -> None:
    client, service = client_and_service
    item = client.post(
        "/api/v1/todos/items", json={"title": "Needs a worker", "idempotency_key": "worker-status"},
    ).json()
    service.agent_task_service.statuses_by_todo_id[item["id"]] = {
        "agent_task_id": "agent-task-for-todo-status-test",
        "status": "awaiting_user_input",
        "result_severity": None,
        "is_active": True,
        "updated_at": "2026-01-01T00:00:00Z",
    }

    response = client.get(f"/api/v1/todos/agent-status?ids={item['id']}")

    assert response.status_code == 200
    assert response.json()[item["id"]]["status"] == "awaiting_user_input"
    assert response.json()[item["id"]]["is_active"] is True


def test_workspace_response_includes_agent_status_snapshot(client_and_service) -> None:
    client, service = client_and_service
    no_worker = client.post(
        "/api/v1/todos/items", json={"title": "No worker yet", "idempotency_key": "no-worker"},
    ).json()
    with_worker = client.post(
        "/api/v1/todos/items", json={"title": "Has a worker", "idempotency_key": "has-worker"},
    ).json()
    service.agent_task_service.statuses_by_todo_id[with_worker["id"]] = {
        "agent_task_id": "agent-task-for-workspace-snapshot-test",
        "status": "processing",
        "result_severity": None,
        "is_active": True,
        "updated_at": "2026-01-01T00:00:00Z",
    }

    response = client.get("/api/v1/todos/workspace")

    assert response.status_code == 200
    rows_by_id = {row["id"]: row for row in response.json()["items"]}
    assert rows_by_id[no_worker["id"]]["agent_status"] is None
    assert rows_by_id[with_worker["id"]]["agent_status"]["status"] == "processing"


def test_create_item_rejects_blank_title(client_and_service) -> None:
    client, _ = client_and_service
    response = client.post("/api/v1/todos/items", json={"title": "   ", "idempotency_key": "blank-title"})
    assert response.status_code == 422


def test_create_item_rejects_oversized_description(client_and_service) -> None:
    client, _ = client_and_service
    response = client.post(
        "/api/v1/todos/items", json={"title": "Valid title", "description": "x" * 12001, "idempotency_key": "long-description"},
    )
    assert response.status_code == 422


def test_create_item_rejects_unknown_fields(client_and_service) -> None:
    client, _ = client_and_service
    response = client.post(
        "/api/v1/todos/items", json={"title": "Valid title", "idempotency_key": "unknown-field", "unexpected_field": "nope"},
    )
    assert response.status_code == 422


def test_get_item_returns_404_for_missing_id(client_and_service) -> None:
    client, _ = client_and_service
    response = client.get("/api/v1/todos/items/does-not-exist")
    assert response.status_code == 404


def test_update_item_with_stale_revision_returns_409_with_structured_conflict_body(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post("/api/v1/todos/items", json={"title": "Original", "idempotency_key": "stale-conflict"}).json()

    response = client.patch(
        f"/api/v1/todos/items/{created['id']}",
        json={"expected_revision": 99, "title": "Should not apply"},
    )

    assert response.status_code == 409
    conflict = response.json()
    assert conflict["detail"] == f"Conflict on To-Do {created['id']}"
    assert conflict["item"]["title"] == "Original"


def test_update_item_rejects_an_empty_patch_and_invalid_lifecycle_transitions(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post("/api/v1/todos/items", json={"title": "Original", "idempotency_key": "invalid-transition"}).json()

    empty_patch = client.patch(
        f"/api/v1/todos/items/{created['id']}",
        json={"expected_revision": created["revision"]},
    )
    assert empty_patch.status_code == 422

    invalid_accept = client.post(
        f"/api/v1/todos/items/{created['id']}/accept",
        json={"expected_revision": created["revision"]},
    )
    assert invalid_accept.status_code == 409

    invalid_dismiss = client.post(
        f"/api/v1/todos/items/{created['id']}/dismiss",
        json={"expected_revision": created["revision"]},
    )
    assert invalid_dismiss.status_code == 409


def test_update_item_can_clear_an_explicit_due_date(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post(
        "/api/v1/todos/items",
        json={"title": "Dated item", "due_at": "2026-01-01T12:00:00Z", "idempotency_key": "dated-item"},
    ).json()

    response = client.patch(
        f"/api/v1/todos/items/{created['id']}",
        json={"expected_revision": created["revision"], "due_at": None},
    )

    assert response.status_code == 200
    assert response.json()["due_at"] is None


def test_delete_item_hard_deletes_the_todo_and_rejects_stale_revisions(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post("/api/v1/todos/items", json={"title": "Delete me", "idempotency_key": "delete-me"}).json()
    stale = client.request(
        "DELETE",
        f"/api/v1/todos/items/{created['id']}",
        json={"expected_revision": created["revision"] + 1},
    )
    assert stale.status_code == 409
    assert stale.json()["item"]["id"] == created["id"]

    deleted = client.request(
        "DELETE",
        f"/api/v1/todos/items/{created['id']}",
        json={"expected_revision": created["revision"]},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"id": created["id"]}
    assert client.get(f"/api/v1/todos/items/{created['id']}").status_code == 404


def test_replace_notes_then_accept_dismiss_complete_reopen_cancel_flow(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post(
        "/api/v1/todos/items", json={"title": "Full lifecycle", "idempotency_key": "full-lifecycle"},
    ).json()

    notes_response = client.put(
        f"/api/v1/todos/items/{created['id']}/notes",
        json={"notes": "First note", "expected_revision": created["revision"]},
    )
    assert notes_response.status_code == 200
    notes_item = notes_response.json()
    assert notes_item["notes"] == "First note"

    complete_response = client.post(
        f"/api/v1/todos/items/{created['id']}/complete",
        json={"expected_revision": notes_item["revision"]},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"
    assert complete_response.json()["completed_at"]

    completed_date_response = client.patch(
        f"/api/v1/todos/items/{created['id']}",
        json={"expected_revision": complete_response.json()["revision"], "completed_at": "2025-12-24T09:30:00Z"},
    )
    assert completed_date_response.status_code == 200
    assert completed_date_response.json()["completed_at"] == "2025-12-24T09:30:00Z"

    reopen_response = client.post(
        f"/api/v1/todos/items/{created['id']}/reopen",
        json={"expected_revision": completed_date_response.json()["revision"]},
    )
    assert reopen_response.status_code == 200
    assert reopen_response.json()["status"] == "open"
    assert reopen_response.json()["completed_at"] is None


def test_reference_routes_add_deduplicate_and_remove_with_optimistic_revision(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post(
        "/api/v1/todos/items", json={"title": "Reference item", "idempotency_key": "reference-routes"},
    ).json()

    added_response = client.post(
        f"/api/v1/todos/items/{created['id']}/references",
        json={"path": "/tmp/project/brief.pdf", "expected_revision": created["revision"]},
    )
    assert added_response.status_code == 200
    added = added_response.json()
    assert added["references"][0]["path"] == "/tmp/project/brief.pdf"

    duplicate_response = client.post(
        f"/api/v1/todos/items/{created['id']}/references",
        json={"path": "/tmp/project/brief.pdf", "expected_revision": added["revision"]},
    )
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["revision"] == added["revision"]

    stale_remove = client.request(
        "DELETE",
        f"/api/v1/todos/items/{created['id']}/references/{added['references'][0]['id']}",
        json={"expected_revision": created["revision"]},
    )
    assert stale_remove.status_code == 409
    assert stale_remove.json()["item"]["references"][0]["id"] == added["references"][0]["id"]

    remove_response = client.request(
        "DELETE",
        f"/api/v1/todos/items/{created['id']}/references/{added['references'][0]['id']}",
        json={"expected_revision": added["revision"]},
    )
    assert remove_response.status_code == 200
    assert remove_response.json()["references"] == []


def test_reference_routes_reject_invalid_paths_and_missing_references(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post(
        "/api/v1/todos/items", json={"title": "Invalid reference", "idempotency_key": "invalid-reference"},
    ).json()
    invalid_path = client.post(
        f"/api/v1/todos/items/{created['id']}/references",
        json={"path": "relative/path", "expected_revision": created["revision"]},
    )
    assert invalid_path.status_code == 422

    missing_reference = client.request(
        "DELETE",
        f"/api/v1/todos/items/{created['id']}/references/missing",
        json={"expected_revision": created["revision"]},
    )
    assert missing_reference.status_code == 409


def test_launch_worker_returns_503_when_no_bridge_is_registered(client_and_service) -> None:
    client, _ = client_and_service
    created = client.post("/api/v1/todos/items", json={"title": "Needs a worker", "idempotency_key": "worker-unavailable"}).json()

    response = client.post(
        f"/api/v1/todos/items/{created['id']}/workers",
        json={"expected_revision": created["revision"]},
    )

    assert response.status_code == 503


def test_launch_worker_returns_409_for_a_candidate_item(client_and_service) -> None:
    client, service = client_and_service

    class StubSubmission:
        async def process_agent_task_direct(self, **kwargs):
            return {"success": True}

        async def broadcast(self, event):
            pass

    set_todo_agent_task_bridge(
        TodoAgentTaskBridge(
            todo_service=service, agent_task_service=FakeAgentTaskLookup(),
            agent_task_submission_service=StubSubmission(),
        )
    )
    import asyncio

    detail, _created = asyncio.run(
        service.repository.create_todo_item_with_source(
            title="Candidate", description="", notes="", responsibility="unspecified", priority="normal",
            due_at=None, status="candidate", created_by_kind="system", created_by_id=None, idempotency_key=None,
            idempotency_payload_hash=None, source_kind=None, source_id=None, source_locator=None, source_excerpt="",
        )
    )

    response = client.post(
        f"/api/v1/todos/items/{detail.id}/workers",
        json={"expected_revision": detail.revision},
    )

    assert response.status_code == 409


def test_launch_worker_succeeds_and_starts_a_worker_task(client_and_service) -> None:
    client, service = client_and_service
    created = client.post("/api/v1/todos/items", json={"title": "Ready for a worker", "idempotency_key": "worker-success"}).json()

    launched_calls = []

    class StubSubmission:
        async def process_agent_task_direct(self, **kwargs):
            launched_calls.append(kwargs)
            return {"success": True}

        async def broadcast(self, event):
            pass

    set_todo_agent_task_bridge(
        TodoAgentTaskBridge(
            todo_service=service, agent_task_service=FakeAgentTaskLookup(),
            agent_task_submission_service=StubSubmission(),
        )
    )

    response = client.post(
        f"/api/v1/todos/items/{created['id']}/workers",
        json={"expected_revision": created["revision"]},
    )

    assert response.status_code == 200
    assert response.json()["item"]["status"] == "in_progress"
    assert response.json()["agent_task_id"]
    assert len(launched_calls) == 1
    assert launched_calls[0]["origin_type"] == "todo"


def test_promote_meeting_proposal_is_idempotent_on_repeated_source(client_and_service) -> None:
    client, _ = client_and_service
    body = {
        "meeting_id": "m1", "filename": "analysis_20260101_000000.json", "proposal_id": "p1",
        "source_task": "Follow up with Alex", "suggested_agent_task": "Draft the follow-up email",
        "why_basil_can_help": "Basil can draft it.",
    }

    first = client.post("/api/v1/todos/meeting-proposals/promote", json=body)
    second = client.post("/api/v1/todos/meeting-proposals/promote", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_promote_meeting_proposal_rejects_unknown_fields(client_and_service) -> None:
    client, _ = client_and_service
    response = client.post(
        "/api/v1/todos/meeting-proposals/promote",
        json={
            "meeting_id": "m1", "filename": "f1", "proposal_id": "p1", "source_task": "t",
            "suggested_agent_task": "a", "unexpected": "nope",
        },
    )
    assert response.status_code == 422


def test_promote_meeting_proposal_rejects_blank_derived_title(client_and_service) -> None:
    client, _ = client_and_service
    response = client.post(
        "/api/v1/todos/meeting-proposals/promote",
        json={
            "meeting_id": "m1", "filename": "f1", "proposal_id": "p1", "source_task": "   ",
            "suggested_agent_task": "Keep the full source description.",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Meeting proposal title must not be blank."
