"""The generated task title is pushed to connected windows as soon as it is saved, so a sidebar row stops showing the prompt text without the task being reopened."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List
from unittest.mock import AsyncMock

import pytest

from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_routing_service import (
    AgentTaskRoutingService,
)


class _FakeModelUsage:
    def __init__(self, _model_service: Any) -> None:
        pass

    async def get_model_for_task(self, capabilities: Any) -> Any:
        return SimpleNamespace(id="fake-model")


def _service(monkeypatch, response: str, canceled: bool = False):
    monkeypatch.setattr("api.dependencies.get_model_service", lambda: object())
    monkeypatch.setattr("api.services.model_usage_service.ModelUsageService", _FakeModelUsage)
    monkeypatch.setattr("api.core.models.model_invocation.call_model_with_prompt", AsyncMock(return_value=response))
    update_title = AsyncMock()
    db_service = SimpleNamespace(agent_task_service=SimpleNamespace(_mutations=SimpleNamespace(update_agent_task_title=update_title)))
    sent: List[dict] = []

    async def broadcast(message: dict) -> None:
        sent.append(message)

    service = AgentTaskRoutingService(
        db_service=db_service,
        websocket_manager=SimpleNamespace(broadcast=broadcast),
        is_canceled=lambda _agent_task_id: canceled,
    )
    return service, update_title, sent


@pytest.mark.asyncio
async def test_saved_title_is_broadcast_for_the_task(monkeypatch):
    service, update_title, sent = _service(monkeypatch, "Weekly Inbox Triage")

    await service.generate_agent_task_title("task-1", "Complete this to-do on the user's behalf: triage the inbox")

    update_title.assert_awaited_once_with("task-1", "Weekly Inbox Triage")
    assert sent == [{"event_type": "agent_task_title", "agent_task_id": "task-1", "title": "Weekly Inbox Triage"}]


@pytest.mark.asyncio
async def test_markdown_in_the_model_reply_is_stripped_before_saving_and_sending(monkeypatch):
    service, update_title, sent = _service(monkeypatch, '**"Quarterly Budget Review"**')

    await service.generate_agent_task_title("task-1", "Review the budget")

    saved_title = update_title.await_args.args[1]
    assert "*" not in saved_title and '"' not in saved_title
    assert sent[0]["title"] == saved_title


@pytest.mark.asyncio
async def test_nothing_is_saved_or_sent_for_an_unusable_reply(monkeypatch):
    service, update_title, sent = _service(monkeypatch, "")

    await service.generate_agent_task_title("task-1", "Review the budget")

    update_title.assert_not_awaited()
    assert sent == []


@pytest.mark.asyncio
async def test_a_canceled_task_gets_its_title_saved_but_no_broadcast(monkeypatch):
    service, update_title, sent = _service(monkeypatch, "Weekly Inbox Triage", canceled=True)

    await service.generate_agent_task_title("task-1", "Review the inbox")

    update_title.assert_awaited_once()
    assert sent == []
