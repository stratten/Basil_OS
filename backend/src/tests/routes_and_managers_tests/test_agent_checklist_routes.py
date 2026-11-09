"""HTTP-level coverage for the user's view of, and edits to, a chain's checklist."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.dependencies import get_sqlite_knowledge_service
from api.main import app

BASE = "/api/v1/agent-tasks"


@pytest.fixture
def service(tmp_path, monkeypatch: pytest.MonkeyPatch):
    knowledge_service = SQLiteKnowledgeService(tmp_path / "checklist-routes.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: knowledge_service)
    app.dependency_overrides[get_sqlite_knowledge_service] = lambda: knowledge_service
    published: list = []

    async def capture(self, message):
        published.append(message)

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster.AgentTaskEventBroadcaster.broadcast", capture
    )
    knowledge_service.published = published
    asyncio.run(knowledge_service.store_agent_task(agent_task_id="root-a", original_prompt="Insurance", transcribed_prompt="Insurance", status="completed"))
    asyncio.run(knowledge_service.store_agent_task(
        agent_task_id="follow-a", original_prompt="More", transcribed_prompt="More", status="completed",
        root_task_id="root-a", previous_task_id="root-a", chain_sequence_number=1,
    ))
    try:
        yield knowledge_service
    finally:
        app.dependency_overrides.pop(get_sqlite_knowledge_service, None)


@pytest.fixture
def client(service) -> TestClient:
    return TestClient(app)


def _add(client, title="Book a GP visit", task="root-a", **extra):
    return client.post(f"{BASE}/{task}/checklist/items", json={"title": title, **extra})


def test_an_empty_checklist_reads_as_empty_and_creates_nothing(client, service):
    body = client.get(f"{BASE}/root-a/checklist").json()

    assert body["exists"] is False and body["items"] == [] and body["counts"]["total"] == 0 and body["notes_max_chars"] == 4000
    assert asyncio.run(service.agent_work_session_repository.get_latest_session_for_root("root-a")) is None


def test_unknown_task_is_a_404(client):
    assert client.get(f"{BASE}/nope/checklist").status_code == 404
    assert client.post(f"{BASE}/nope/checklist/items", json={"title": "x"}).status_code == 404


def test_user_items_are_created_against_the_chain_root_even_from_a_follow_up(client, service):
    created = _add(client, task="follow-a", required=True, detail="Ask about referral").json()
    body = client.get(f"{BASE}/root-a/checklist").json()

    assert created["created"] is True and created["item"]["origin"] == "user"
    assert [item["title"] for item in body["items"]] == ["Book a GP visit"]
    assert body["counts"]["total"] == 1 and body["items"][0]["required"] is True
    assert service.published[-1]["event_type"] == "agent_checklist_updated" and service.published[-1]["root_task_id"] == "root-a"
    assert client.get(f"{BASE}/follow-a/checklist").json()["items"][0]["id"] == created["item"]["id"]


def test_blank_and_invalid_input_is_rejected_with_readable_errors(client):
    assert client.post(f"{BASE}/root-a/checklist/items", json={"title": ""}).status_code == 422
    assert client.post(f"{BASE}/root-a/checklist/items", json={"title": "x", "status": "discovered"}).status_code == 422
    item = _add(client).json()["item"]
    assert client.patch(f"{BASE}/root-a/checklist/items/{item['id']}", json={"status": "weird"}).status_code == 422
    assert client.patch(f"{BASE}/root-a/checklist/items/{item['id']}", json={"unknown_field": 1}).status_code == 422


def test_patch_checks_the_revision_and_returns_the_latest_item_on_conflict(client):
    item = _add(client).json()["item"]
    url = f"{BASE}/root-a/checklist/items/{item['id']}"

    ok = client.patch(url, json={"status": "waiting_user", "waiting_on": "Pick a time", "expected_revision": 1})
    stale = client.patch(url, json={"title": "Different", "expected_revision": 1})

    assert ok.status_code == 200 and ok.json()["item"]["revision"] == 2
    assert stale.status_code == 409 and stale.json()["current"]["status"] == "waiting_user"
    assert client.patch(f"{BASE}/root-a/checklist/items/missing", json={"status": "done"}).status_code == 404


def test_archive_close_and_reopen(client):
    first = _add(client, "One").json()["item"]
    _add(client, "Two")

    archived = client.post(f"{BASE}/root-a/checklist/items/{first['id']}/archive", json={"archived": True}).json()
    body = client.get(f"{BASE}/root-a/checklist").json()
    closed = client.post(f"{BASE}/root-a/checklist/close", json={"closed": True}).json()
    _add(client, "Three")
    reopened = client.get(f"{BASE}/root-a/checklist").json()

    assert archived["item"]["archived_at"] and len(body["items"]) == 2 and body["counts"]["total"] == 1
    assert closed["closed_at"] and reopened["closed_at"] is None


def test_notes_conflict_limit_and_round_trip(client):
    saved = client.put(f"{BASE}/root-a/checklist/notes", json={"content": "Clinic replies Fridays.", "expected_revision": 0})
    stale = client.put(f"{BASE}/root-a/checklist/notes", json={"content": "Other", "expected_revision": 0})
    too_long = client.put(f"{BASE}/root-a/checklist/notes", json={"content": "x" * 4500})

    assert saved.status_code == 200 and saved.json()["notes"]["revision"] == 1 and saved.json()["notes"]["updated_by"] == "user"
    assert stale.status_code == 409 and stale.json()["current"]["content"] == "Clinic replies Fridays."
    assert too_long.status_code == 422 and "Condense" in too_long.json()["detail"]
    assert client.get(f"{BASE}/root-a/checklist").json()["notes"]["content"] == "Clinic replies Fridays."


def test_item_log_lists_steps_and_captured_actions(client, service):
    asyncio.run(service.agent_work_session_repository.get_or_create_root_session(root_task_id="root-a", goal="g", collection_type="agent_work"))
    session = asyncio.run(service.agent_work_session_repository.get_latest_session_for_root("root-a"))
    asyncio.run(service.agent_work_item_repository.add_items(session_id=session["id"], items=[{"external_id": "thread-3"}]))
    captured = asyncio.run(service.agent_work_item_repository.get_items(session_id=session["id"]))[0]
    asyncio.run(service.agent_work_receipt_repository.add_receipt(
        session_id=session["id"], item_id=captured["id"], agent_task_id="root-a", service="email_service", method="send_email",
        execution_state="succeeded", verification_status="verified", requested_effect={"material_write": True}, evidence={"message_id": "m-1"},
    ))
    item = _add(client, refs=[{"ref_kind": "gmail_thread", "external_id": "thread-3"}]).json()["item"]
    client.patch(f"{BASE}/root-a/checklist/items/{item['id']}", json={"status": "in_progress", "event_text": "drafting"})

    log = client.get(f"{BASE}/root-a/checklist/items/{item['id']}/log").json()

    assert [event["kind"] for event in log["events"]] == ["added", "status"] and log["events"][1]["actor"] == "user"
    assert log["captured"][0]["service"] == "email_service" and log["captured"][0]["method"] == "send_email"
    assert client.get(f"{BASE}/root-a/checklist/items/missing/log").status_code == 404


def test_offering_an_item_as_a_todo_creates_a_candidate_and_logs_it(client, service, monkeypatch):
    calls = []

    class _Todos:
        async def create_todo_from_agent_tool(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id="todo-1", status=kwargs["status"])

    monkeypatch.setattr("api.dependencies.get_todo_service", lambda: _Todos())
    item = _add(client, "Choose a visit time", status="waiting_user", waiting_on="Your calendar").json()["item"]

    response = client.post(f"{BASE}/root-a/checklist/items/{item['id']}/todo")
    log = client.get(f"{BASE}/root-a/checklist/items/{item['id']}/log").json()

    assert response.json() == {"todo_id": "todo-1", "status": "candidate"}
    assert calls[0]["status"] == "candidate" and calls[0]["title"] == "Choose a visit time" and "Your calendar" in calls[0]["description"]
    assert log["events"][-1]["kind"] == "todo_offered"
    assert client.post(f"{BASE}/root-a/checklist/items/missing/todo").status_code == 404


def test_history_list_items_carry_the_checklist_counter(client):
    first = _add(client, "One").json()["item"]
    _add(client, "Two")
    client.patch(f"{BASE}/root-a/checklist/items/{first['id']}", json={"status": "done"})

    history = client.get(f"{BASE}/history").json()
    row = next(item for item in history["agentTasks"] if item["id"] == "root-a")

    assert (row["checklist_done"], row["checklist_total"]) == (1, 2)
