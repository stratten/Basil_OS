"""refresh_first: the agent can collect not-yet-indexed records before a history query.

A meeting that ended minutes ago is not searchable until the periodic collection pass runs. refresh_first runs one pass on demand, never doubles a pass already in flight, never raises into the query, and respects the user turning collection off.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.internal_basil_tools import unified_history_tool as tool


class _FakeScheduler:
    def __init__(self, error=None, delay=0.0, running=False):
        self.error = error
        self.delay = delay
        self.run_count = 0
        self.status = SimpleNamespace(is_running_now=running)

    def get_status(self):
        return self.status

    async def run_now(self):
        self.run_count += 1
        self.status.is_running_now = True
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return self.error
        finally:
            self.status.is_running_now = False


@pytest.fixture(autouse=True)
def _reset_cooldown(monkeypatch):
    monkeypatch.setattr(tool, "_last_memory_refresh_finished", None)


def _install(monkeypatch, scheduler, carding_enabled=True):
    monkeypatch.setattr(
        "api.services.zettel.scheduler.get_zettel_scheduler", lambda: scheduler
    )
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: SimpleNamespace(zettel=SimpleNamespace(carding_enabled=carding_enabled)),
    )


@pytest.mark.asyncio
async def test_a_refresh_runs_one_pass_and_reports_completed(monkeypatch):
    scheduler = _FakeScheduler()
    _install(monkeypatch, scheduler)
    assert await tool.refresh_memory_stream() == {"status": "completed"}
    assert scheduler.run_count == 1


@pytest.mark.asyncio
async def test_a_second_refresh_inside_the_cooldown_is_skipped(monkeypatch):
    scheduler = _FakeScheduler()
    _install(monkeypatch, scheduler)
    await tool.refresh_memory_stream()
    second = await tool.refresh_memory_stream()
    assert second["status"] == "skipped_recent"
    assert scheduler.run_count == 1


@pytest.mark.asyncio
async def test_a_refresh_after_the_cooldown_runs_again(monkeypatch):
    scheduler = _FakeScheduler()
    _install(monkeypatch, scheduler)
    await tool.refresh_memory_stream()
    monkeypatch.setattr(tool, "_last_memory_refresh_finished", tool.time.monotonic() - 31.0)
    assert (await tool.refresh_memory_stream())["status"] == "completed"
    assert scheduler.run_count == 2


@pytest.mark.asyncio
async def test_turned_off_collection_is_respected(monkeypatch):
    scheduler = _FakeScheduler()
    _install(monkeypatch, scheduler, carding_enabled=False)
    result = await tool.refresh_memory_stream()
    assert result["status"] == "carding_disabled"
    assert scheduler.run_count == 0


@pytest.mark.asyncio
async def test_a_pass_already_running_is_waited_for_not_doubled_up_on(monkeypatch):
    scheduler = _FakeScheduler(running=True)
    _install(monkeypatch, scheduler)

    async def finish_the_running_pass():
        await asyncio.sleep(0.05)
        scheduler.status.is_running_now = False

    finisher = asyncio.ensure_future(finish_the_running_pass())
    result = await tool.refresh_memory_stream()
    await finisher
    assert result == {"status": "completed"}
    assert scheduler.run_count == 1


@pytest.mark.asyncio
async def test_a_pass_that_outlasts_the_timeout_keeps_running_and_the_query_proceeds(monkeypatch):
    scheduler = _FakeScheduler(delay=0.3)
    _install(monkeypatch, scheduler)
    monkeypatch.setattr(tool, "MEMORY_REFRESH_TIMEOUT_SECONDS", 0.0)
    result = await tool.refresh_memory_stream()
    assert result["status"] == "timed_out"
    await asyncio.sleep(0.4)
    assert scheduler.run_count == 1
    assert scheduler.status.is_running_now is False


@pytest.mark.asyncio
async def test_pass_errors_are_reported_without_raising(monkeypatch):
    scheduler = _FakeScheduler(error="meeting: disk unreadable")
    _install(monkeypatch, scheduler)
    result = await tool.refresh_memory_stream()
    assert result == {"status": "completed_with_errors", "error": "meeting: disk unreadable"}


@pytest.mark.asyncio
async def test_a_scheduler_that_raises_never_breaks_the_query(monkeypatch):
    def explode():
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr("api.services.zettel.scheduler.get_zettel_scheduler", explode)
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: SimpleNamespace(zettel=SimpleNamespace(carding_enabled=True)),
    )
    result = await tool.refresh_memory_stream()
    assert result["status"] == "error"
    assert "scheduler unavailable" in result["error"]


@pytest.mark.asyncio
async def test_the_query_reports_the_refresh_outcome_only_when_one_was_asked_for(monkeypatch):
    scheduler = _FakeScheduler()
    _install(monkeypatch, scheduler)
    seen = {}

    def fake_sync(*args, memory_refresh=None, **kwargs):
        seen["memory_refresh"] = memory_refresh
        return json.dumps({"success": True, "events": []})

    monkeypatch.setattr(tool, "_query_unified_history_sync", fake_sync)

    await tool._query_unified_history_impl()
    assert seen["memory_refresh"] is None
    assert scheduler.run_count == 0

    await tool._query_unified_history_impl(refresh_first=True)
    assert seen["memory_refresh"] == {"status": "completed"}
    assert scheduler.run_count == 1


def test_the_sync_query_includes_memory_refresh_in_its_response(monkeypatch):
    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection.get_sync_connection",
        lambda _path: _Conn(),
    )
    monkeypatch.setattr(
        "api.dependencies.get_sqlite_knowledge_service",
        lambda: SimpleNamespace(db_path=":memory:"),
    )
    monkeypatch.setattr("api.services.zettel.store.query_entries", lambda *a, **k: [])
    monkeypatch.setattr("api.services.zettel.store.count_entries_by", lambda *a, **k: {})

    with_refresh = json.loads(
        tool._query_unified_history_sync(memory_refresh={"status": "completed"})
    )
    without = json.loads(tool._query_unified_history_sync())
    assert with_refresh["memory_refresh"] == {"status": "completed"}
    assert "memory_refresh" not in without


def test_the_tool_schema_and_descriptions_tell_the_agent_about_refresh_first():
    assert "refresh_first" in tool.UnifiedHistoryInput.model_fields
    assert tool.UnifiedHistoryInput().refresh_first is False
    assert "refresh_first=true" in tool.SLIM_DESCRIPTION
    assert "refresh_first" in tool._FULL_DESCRIPTION
    assert "~/.basil/meetings/" in tool._FULL_DESCRIPTION
