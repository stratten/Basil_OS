"""
Tests for the scheduled agent task agent tool.

These tests are written as pytest unit tests (not ad-hoc scripts) so they can
be folded directly into the automated suite as coverage expands.
"""

import json
import pytest

from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest
from api.services.agent_processing.tools.internal_basil_tools import scheduled_agent_task_tool as tool_module


@pytest.mark.asyncio
async def test_create_scheduled_agent_task_from_prompt_success(monkeypatch):
    """Tool should interpret and persist a scheduled agent task on valid prompt."""

    class FakeScheduledAgentTaskService:
        async def interpret_schedule_prompt(self, user_prompt: str, context_id: str | None = None):
            assert "every day at 8pm" in user_prompt
            assert context_id == "ctx-123"
            return {
                "title": "Daily Inbox Review",
                "agent_task_text": "Review inbox and summarize unanswered emails",
                "schedule_type": "recurring",
                "schedule_config": {"mode": "daily", "time": "20:00"},
                "timezone": "America/New_York",
                "needs_user_confirmation": False,
                "clarification_question": None,
                "confidence": 0.94,
            }

        async def create_scheduled_agent_task(
            self,
            *,
            title: str,
            agent_task_text: str,
            schedule_type: str,
            schedule_config: dict,
            timezone_name: str,
            source_type: str = "manual",
            is_active: bool = True,
        ):
            assert title == "Daily Inbox Review"
            assert agent_task_text.startswith("Review inbox")
            assert schedule_type == "recurring"
            assert schedule_config["mode"] == "daily"
            assert timezone_name == "America/New_York"
            assert source_type == "smart"
            assert is_active is True
            return {
                "id": "sched-001",
                "title": title,
                "agent_task_text": agent_task_text,
                "schedule_type": schedule_type,
                "schedule_config": schedule_config,
                "timezone": timezone_name,
                "source_type": source_type,
                "is_active": is_active,
            }

    monkeypatch.setattr(tool_module, "ScheduledAgentTaskService", FakeScheduledAgentTaskService)

    raw = await tool_module._create_scheduled_agent_task_impl(
        prompt="I want you to review my emails every day at 8pm and summarize unanswered messages.",
        context_id="ctx-123",
        is_active=True,
    )
    payload = json.loads(raw)
    assert payload["success"] is True
    assert payload["scheduled_agent_task"]["id"] == "sched-001"
    assert payload["scheduled_agent_task"]["source_type"] == "smart"


@pytest.mark.asyncio
async def test_create_scheduled_agent_task_from_prompt_requests_clarification(monkeypatch):
    """Tool should trigger checkpoint when the interpreter needs clarification."""

    class FakeScheduledAgentTaskService:
        async def interpret_schedule_prompt(self, user_prompt: str, context_id: str | None = None):
            raise ValueError("Need clarification (context_id=ctx-clarify): Which timezone should I use?")

    monkeypatch.setattr(tool_module, "ScheduledAgentTaskService", FakeScheduledAgentTaskService)

    with pytest.raises(CheckpointRequest) as exc:
        await tool_module._create_scheduled_agent_task_impl(
            prompt="Check my emails every evening and summarize unanswered threads.",
            context_id=None,
            is_active=True,
        )

    checkpoint_data = exc.value.checkpoint_data
    assert checkpoint_data["input_type"] == "text"
    assert "timezone" in checkpoint_data["prompt"].lower()
    assert "ctx-clarify" in checkpoint_data.get("context_summary", "")

