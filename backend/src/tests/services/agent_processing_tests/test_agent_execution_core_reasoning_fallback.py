"""Tests for the reasoning-model local-fallback eligibility logic in
execute_with_token_retry (agent_execution_core.py) -- the Agent Task surface's
"zero progress yet" gate for ModelUnavailableBeforeFirstResponse.
"""

import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from api.services.agent_processing.lifecycle.execution_graph.agent_execution_core import (
    ModelUnavailableBeforeFirstResponse,
    execute_with_token_retry,
)


def _make_progress_handler(completed_llm_calls: int) -> MagicMock:
    handler = MagicMock()
    handler.completed_llm_calls = completed_llm_calls
    return handler


@pytest.mark.asyncio
async def test_execute_with_token_retry_raises_model_unavailable_before_first_response_on_connection_error(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    agent_executor = MagicMock()
    agent_executor.ainvoke = AsyncMock(
        side_effect=ConnectionError("nodename nor servname provided, or not known")
    )
    handler = _make_progress_handler(completed_llm_calls=0)

    with pytest.raises(ModelUnavailableBeforeFirstResponse):
        await execute_with_token_retry(
            agent_executor,
            "do the thing",
            callbacks=[handler],
            max_transient_retries=2,
        )

    assert agent_executor.ainvoke.await_count == 3  # initial attempt + 2 retries


@pytest.mark.asyncio
async def test_execute_with_token_retry_does_not_swap_after_partial_progress(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    original_error = ConnectionError("nodename nor servname provided, or not known")
    agent_executor = MagicMock()
    agent_executor.ainvoke = AsyncMock(side_effect=original_error)
    handler = _make_progress_handler(completed_llm_calls=1)

    with pytest.raises(ConnectionError) as exc_info:
        await execute_with_token_retry(
            agent_executor,
            "do the thing",
            callbacks=[handler],
            max_transient_retries=2,
        )

    assert exc_info.value is original_error


@pytest.mark.asyncio
async def test_execute_with_token_retry_raises_model_unavailable_immediately_on_auth_error():
    agent_executor = MagicMock()
    agent_executor.ainvoke = AsyncMock(side_effect=Exception("Invalid API key provided"))
    handler = _make_progress_handler(completed_llm_calls=0)

    start = time.monotonic()
    with pytest.raises(ModelUnavailableBeforeFirstResponse):
        await execute_with_token_retry(
            agent_executor,
            "do the thing",
            callbacks=[handler],
            max_transient_retries=2,
        )
    elapsed = time.monotonic() - start

    assert elapsed < 0.5
    agent_executor.ainvoke.assert_awaited_once()
