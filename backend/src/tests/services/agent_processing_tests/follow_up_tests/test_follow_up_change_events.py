"""The UI learns about scheduled follow-up changes through a broadcast event and a durable pending-follow-up route."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
    AgentTaskFollowUpRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_follow_up_migrations import (
    migrate_agent_follow_up_tables,
)
from api.routes.agent_tasks import history_routes
from api.routes.agent_tasks.core_routes import router as agent_task_router
from api.services import websocket_connection_manager
from api.services.agent_follow_ups.follow_up_events import (
    FOLLOW_UPS_CHANGED_EVENT,
    notify_follow_ups_changed,
)
from api.services.agent_follow_ups.follow_up_scheduler import AgentFollowUpScheduler

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def repository(tmp_path) -> AgentTaskFollowUpRepository:
    db_path = tmp_path / "follow_up_events.db"
    with sqlite3.connect(db_path) as conn:
        migrate_agent_follow_up_tables(conn)
    return AgentTaskFollowUpRepository(str(db_path))


@pytest.fixture
def broadcasts(monkeypatch):
    sent: list[dict] = []

    async def _record(payload, *, log=None):
        sent.append(payload)
        return 1

    monkeypatch.setattr(websocket_connection_manager, "broadcast_json_text", _record)
    return sent


@pytest.mark.asyncio
async def test_notify_sends_one_event_per_distinct_root(broadcasts):
    await notify_follow_ups_changed(["root-b", "root-a", "root-a", "", "  "])

    assert broadcasts == [
        {"event_type": FOLLOW_UPS_CHANGED_EVENT, "root_task_id": "root-a"},
        {"event_type": FOLLOW_UPS_CHANGED_EVENT, "root_task_id": "root-b"},
    ]
    assert all("agent_task_id" not in payload for payload in broadcasts)


@pytest.mark.asyncio
async def test_notify_never_raises_when_the_broadcast_fails(monkeypatch):
    async def _explode(payload, *, log=None):
        raise RuntimeError("socket down")

    monkeypatch.setattr(websocket_connection_manager, "broadcast_json_text", _explode)

    await notify_follow_ups_changed(["root-a"])


@pytest.mark.asyncio
async def test_all_pending_due_by_root_reports_only_scheduled_rows(repository):
    await repository.create_follow_up(root_task_id="root-a", source_agent_task_id="t", instructions="late", reason="", due_at="2026-10-12T15:00:00+00:00")
    await repository.create_follow_up(root_task_id="root-a", source_agent_task_id="t", instructions="soon", reason="", due_at="2026-10-12T13:00:00+00:00")
    await repository.create_follow_up(root_task_id="root-b", source_agent_task_id="t", instructions="gone", reason="", due_at="2026-10-12T14:00:00+00:00")
    await repository.cancel_pending_for_root("root-b", reason="canceled")

    assert await repository.all_pending_due_by_root() == {"root-a": "2026-10-12T13:00:00+00:00"}


@pytest.mark.asyncio
async def test_scheduler_tick_that_claims_a_follow_up_notifies_its_root(repository, broadcasts):
    await repository.create_follow_up(
        root_task_id="root-1",
        source_agent_task_id="task-1",
        instructions="Check the deploy",
        reason="",
        due_at=(NOW - timedelta(seconds=1)).isoformat(timespec="seconds"),
    )

    class _Chain:
        async def get_agent_task_chain(self, root_task_id):
            return [SimpleNamespace(id="turn-0", status="completed")]

        async def list_agent_tasks_by_origin(self, origin_type, origin_id, include_terminal=True):
            return []

    class _Submission:
        async def process_agent_task_direct(self, **kwargs):
            return {"success": True}

    scheduler = AgentFollowUpScheduler(
        repository=repository, chain_reader=_Chain(), submission_service=_Submission(), now_fn=lambda: NOW
    )
    await scheduler.run_once()
    assert broadcasts == [{"event_type": FOLLOW_UPS_CHANGED_EVENT, "root_task_id": "root-1"}]

    broadcasts.clear()
    await scheduler.run_once()
    assert broadcasts == []


def test_pending_route_lists_each_waiting_chain_soonest_first(repository):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(repository.create_follow_up(root_task_id="root-late", source_agent_task_id="t", instructions="x", reason="", due_at="2026-10-12T15:00:00+00:00"))
        loop.run_until_complete(repository.create_follow_up(root_task_id="root-soon", source_agent_task_id="t", instructions="x", reason="", due_at="2026-10-12T13:00:00+00:00"))
    finally:
        loop.close()

    knowledge_service = SimpleNamespace(agent_task_follow_up_repository=repository)
    app = FastAPI()
    app.include_router(agent_task_router)
    app.dependency_overrides[history_routes.get_sqlite_knowledge_service] = lambda: knowledge_service

    response = TestClient(app).get("/api/v1/agent-tasks/follow-ups/pending")

    assert response.status_code == 200
    assert response.json() == {
        "follow_ups": [
            {"root_task_id": "root-soon", "due_at": "2026-10-12T13:00:00+00:00"},
            {"root_task_id": "root-late", "due_at": "2026-10-12T15:00:00+00:00"},
        ]
    }


def test_pending_route_is_empty_when_nothing_is_waiting(repository):
    knowledge_service = SimpleNamespace(agent_task_follow_up_repository=repository)
    app = FastAPI()
    app.include_router(agent_task_router)
    app.dependency_overrides[history_routes.get_sqlite_knowledge_service] = lambda: knowledge_service

    response = TestClient(app).get("/api/v1/agent-tasks/follow-ups/pending")

    assert response.status_code == 200
    assert response.json() == {"follow_ups": []}


def _seed(repository, *items):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return [loop.run_until_complete(repository.create_follow_up(root_task_id=root, source_agent_task_id="t", instructions="x", reason="", due_at=due)) for root, due in items]
    finally:
        loop.close()


def _client(repository) -> TestClient:
    knowledge_service = SimpleNamespace(agent_task_follow_up_repository=repository)
    app = FastAPI()
    app.include_router(agent_task_router)
    app.dependency_overrides[history_routes.get_sqlite_knowledge_service] = lambda: knowledge_service
    return TestClient(app)


def test_user_can_stop_a_chains_scheduled_checks_and_the_ui_is_told(repository, broadcasts):
    first, second, other = _seed(
        repository,
        ("root-1", "2026-10-12T13:00:00+00:00"),
        ("root-1", "2026-10-12T14:00:00+00:00"),
        ("root-2", "2026-10-12T15:00:00+00:00"),
    )
    client = _client(repository)

    response = client.delete("/api/v1/agent-tasks/follow-ups/root-1")

    assert response.status_code == 200
    assert response.json() == {"success": True, "canceled_count": 2}
    assert broadcasts == [{"event_type": FOLLOW_UPS_CHANGED_EVENT, "root_task_id": "root-1"}]
    assert client.get("/api/v1/agent-tasks/follow-ups/pending").json() == {
        "follow_ups": [{"root_task_id": "root-2", "due_at": "2026-10-12T15:00:00+00:00"}]
    }


def test_stopping_checks_for_a_chain_with_none_is_a_quiet_no_op(repository, broadcasts):
    (kept,) = _seed(repository, ("root-2", "2026-10-12T15:00:00+00:00"))

    response = _client(repository).delete("/api/v1/agent-tasks/follow-ups/root-1")

    assert response.status_code == 200
    assert response.json() == {"success": True, "canceled_count": 0}
    assert broadcasts == []
