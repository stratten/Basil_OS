"""Tests for the schedule review tool: list every schedule, pause one, and refuse everything else."""

import json

import pytest

from api.services.agent_processing.tools.internal_basil_tools import scheduled_agent_task_audit_tool as tool_module


def _schedule(schedule_id: str, active: bool = True, text: str = "Summarize my inbox") -> dict:
    return {
        "id": schedule_id,
        "title": f"Schedule {schedule_id}",
        "agent_task_text": text,
        "schedule_type": "recurring",
        "timezone": "America/New_York",
        "is_active": active,
        "next_run_at": "2026-11-06T13:00:00Z",
        "last_run_at": None,
        "last_status": "completed",
        "connection_ids": ["secret-connection-id"],
    }


class FakeService:
    def __init__(self, items):
        self.items = {item["id"]: dict(item) for item in items}
        self.updates = []

    async def list_scheduled_agent_tasks(self, include_inactive: bool = True):
        assert include_inactive is True
        return list(self.items.values())

    async def get_scheduled_agent_task(self, schedule_id):
        return self.items.get(schedule_id)

    async def update_scheduled_agent_task(self, schedule_id, updates):
        self.updates.append((schedule_id, updates))
        if schedule_id not in self.items:
            return None
        self.items[schedule_id].update(updates)
        return self.items[schedule_id]


@pytest.fixture
def service(monkeypatch):
    fake = FakeService([_schedule("a"), _schedule("b", active=False, text="x" * 1000)])
    monkeypatch.setattr(tool_module, "ScheduledAgentTaskService", lambda: fake)
    return fake


async def _run(**kwargs):
    return json.loads(await tool_module._manage_scheduled_agent_tasks_impl(**kwargs))


@pytest.mark.asyncio
async def test_list_shows_every_schedule_with_a_bounded_preview_and_no_connection_details(service):
    result = await _run(action="list")
    assert result["success"] and [item["id"] for item in result["scheduled_agent_tasks"]] == ["a", "b"]
    assert len(result["scheduled_agent_tasks"][1]["what_it_does"]) == tool_module.TEXT_PREVIEW_LIMIT + 3
    assert "connection_ids" not in json.dumps(result)


@pytest.mark.asyncio
async def test_pause_only_clears_the_active_flag(service):
    result = await _run(action="pause", scheduled_agent_task_id="a")
    assert result["success"] and result["changed"] and result["scheduled_agent_task"]["is_active"] is False
    assert service.updates == [("a", {"is_active": False})]


@pytest.mark.asyncio
async def test_pausing_an_already_paused_schedule_changes_nothing(service):
    result = await _run(action="pause", scheduled_agent_task_id="b")
    assert result["success"] and result["changed"] is False
    assert service.updates == []


@pytest.mark.asyncio
async def test_pause_refuses_a_missing_or_unknown_id(service):
    assert (await _run(action="pause"))["success"] is False
    assert (await _run(action="pause", scheduled_agent_task_id="nope"))["success"] is False
    assert service.updates == []


@pytest.mark.asyncio
async def test_resume_edit_and_delete_are_not_actions(service):
    for action in ("resume", "delete", "update"):
        assert (await _run(action=action, scheduled_agent_task_id="a"))["success"] is False
    assert service.updates == []


def test_the_tool_is_in_the_schedule_family_and_offers_only_list_and_pause():
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import FAMILY_DEFINITIONS

    schedule = next(family for family in FAMILY_DEFINITIONS if family.name == "schedule")
    assert tool_module.TOOL_NAME in schedule.tool_names
    built = tool_module.create_scheduled_agent_task_audit_tool()
    assert built.name == tool_module.TOOL_NAME
    assert tool_module.ScheduledAgentTaskAuditInput.model_json_schema()["properties"]["action"]["enum"] == ["list", "pause"]
