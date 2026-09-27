"""Regression coverage for `recover_standardized_messages_from_database`.

Guards a real bug found via live functional verification (2026-07-24): the
function looked up `knowledge_service.agent_task_service` on the object
returned by an incompatible knowledge-service wrapper that only
exposed a nested SQLite delegate -- so every real invocation raised
`AttributeError` (caught non-fatally, but the "recover short output from the
DB" fallback never actually worked). The fix routes through
`get_sqlite_knowledge_service()` instead, matching the existing pattern in
`async_finalizer.py`.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.services.agent_processing.lifecycle.finalization.summary_payload import (
    recover_standardized_messages_from_database,
)


def _fake_knowledge_service(agent_task: SimpleNamespace | None) -> SimpleNamespace:
    return SimpleNamespace(
        agent_task_service=SimpleNamespace(get_agent_task=AsyncMock(return_value=agent_task))
    )


@pytest.mark.asyncio
async def test_short_circuits_without_touching_the_database_when_content_is_sufficient():
    sufficient = ["x" * 150]
    with patch("api.dependencies.get_sqlite_knowledge_service") as get_service:
        result = await recover_standardized_messages_from_database("task-1", sufficient)
    get_service.assert_not_called()
    assert result == sufficient


@pytest.mark.asyncio
async def test_short_circuits_without_touching_the_database_when_no_agent_task_id():
    thin = ["short"]
    with patch("api.dependencies.get_sqlite_knowledge_service") as get_service:
        result = await recover_standardized_messages_from_database(None, thin)
    get_service.assert_not_called()
    assert result == thin


@pytest.mark.asyncio
async def test_recovers_accumulated_output_from_the_sqlite_service_when_content_is_thin():
    accumulated = "Recovered content. " * 12  # > 100 chars
    fake_task = SimpleNamespace(result_data={"data": {"accumulated_output": accumulated}})
    fake_service = _fake_knowledge_service(fake_task)

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake_service) as get_service:
        result = await recover_standardized_messages_from_database("task-1", ["short"])

    get_service.assert_called_once()
    fake_service.agent_task_service.get_agent_task.assert_awaited_once_with("task-1")
    assert result == [accumulated]


@pytest.mark.asyncio
async def test_falls_back_to_original_content_when_the_database_lookup_raises():
    """Regression guard for the exact bug this fix addresses: a knowledge-service
    wrapper whose attribute access raises AttributeError must not propagate --
    the function must degrade gracefully and return the original messages."""
    thin = ["short"]

    class ExplodingKnowledgeService:
        @property
        def agent_task_service(self):
            raise AttributeError(
                "'KnowledgeService' object has no attribute 'agent_task_service'"
            )

    with patch(
        "api.dependencies.get_sqlite_knowledge_service",
        return_value=ExplodingKnowledgeService(),
    ):
        result = await recover_standardized_messages_from_database("task-1", thin)

    assert result == thin


@pytest.mark.asyncio
async def test_falls_back_to_original_content_when_no_agent_task_found():
    fake_service = _fake_knowledge_service(None)
    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake_service):
        result = await recover_standardized_messages_from_database("task-1", ["short"])
    assert result == ["short"]


@pytest.mark.asyncio
async def test_falls_back_to_original_content_when_accumulated_output_is_too_thin():
    fake_task = SimpleNamespace(result_data={"data": {"accumulated_output": "tiny"}})
    fake_service = _fake_knowledge_service(fake_task)
    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake_service):
        result = await recover_standardized_messages_from_database("task-1", ["short"])
    assert result == ["short"]
