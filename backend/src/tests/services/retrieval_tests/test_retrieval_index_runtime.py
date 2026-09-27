"""Tests for coalesced retrieval index runtime."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

import pytest

from api.services.retrieval.index_runtime import RetrievalIndexRuntime


@pytest.mark.asyncio
async def test_start_schedules_without_blocking():
    indexer = MagicMock()
    indexer.rebuild_if_stale.return_value = {"rebuilt": True, "document_count": 1}
    runtime = RetrievalIndexRuntime(indexer)

    await runtime.start()
    await asyncio.sleep(0.05)

    assert indexer.rebuild_if_stale.call_count >= 1
    status = runtime.get_status()
    assert status.last_reasons == ["startup"]


@pytest.mark.asyncio
async def test_concurrent_requests_coalesce_to_one_extra_run():
    indexer = MagicMock()
    calls = {"count": 0}
    gate = threading.Event()

    def _rebuild():
        calls["count"] += 1
        if calls["count"] == 1:
            gate.wait(timeout=1.0)
        return {"rebuilt": True, "document_count": calls["count"]}

    runtime = RetrievalIndexRuntime(indexer)
    indexer.rebuild_if_stale.side_effect = _rebuild

    runtime.request_reconciliation("first")

    async def _wait_and_request_second():
        await asyncio.sleep(0.01)
        runtime.request_reconciliation("second")
        gate.set()

    second = asyncio.create_task(_wait_and_request_second())
    await runtime.stop()
    await second

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_reconcile_after_narrative_pass_awaits_completion():
    indexer = MagicMock()
    indexer.rebuild_if_stale.return_value = {"rebuilt": True, "document_count": 2}
    runtime = RetrievalIndexRuntime(indexer)

    await runtime.reconcile_after_narrative_pass()

    assert indexer.rebuild_if_stale.call_count == 1
    assert runtime.get_status().last_reasons == ["narrative_pass_complete"]


@pytest.mark.asyncio
async def test_failure_records_error_status():
    indexer = MagicMock()
    indexer.rebuild_if_stale.side_effect = RuntimeError("boom")
    runtime = RetrievalIndexRuntime(indexer)

    await runtime.start()
    await runtime.stop()

    assert runtime.get_status().last_error == "boom"
