"""The daily sweep must not mark data consumed unless it was actually consumed."""

import asyncio

from api.services.memory import post_task_evaluator_orchestrator as orchestrator_module
from api.services.memory.post_task_evaluator_orchestrator import PostTaskEvaluatorOrchestrator


class _Settings:
    memory_daily_enabled = True
    skill_daily_enabled = False
    memory_processing_model = None
    skill_processing_model = None


def _signal(occurred_at="2026-07-24T10:00:00+00:00"):
    from api.services.memory.memory_evaluator import ActivitySignal

    return ActivitySignal(
        source="agent_task", occurred_at=occurred_at, summary="did a thing", metadata={}
    )


def _orchestrator(tmp_path, monkeypatch, signals, entry_ids):
    orchestrator = PostTaskEvaluatorOrchestrator()
    monkeypatch.setattr(
        type(orchestrator), "watermark_path",
        property(lambda self: tmp_path / "watermarks.json"),
    )
    monkeypatch.setattr(orchestrator, "_load_memory_intelligence_settings", lambda: _Settings())
    monkeypatch.setattr(orchestrator, "_select_fallback_model_id", lambda: "model-x")
    monkeypatch.setattr(
        "api.services.zettel.memory_bridge.load_unswept_signals",
        lambda limit=300: (signals, entry_ids),
    )
    return orchestrator


def _capture_stamps(monkeypatch):
    stamped = []
    monkeypatch.setattr(
        "api.services.zettel.memory_bridge.mark_swept",
        lambda entry_ids, **kwargs: stamped.extend(entry_ids) or len(entry_ids),
    )
    return stamped


class _Evaluator:
    """Stands in for MemoryEvaluator; raises when told to."""

    fail = False

    def __init__(self, model_id=None):
        self.model_id = model_id

    async def evaluate_signals(self, signals):
        if _Evaluator.fail:
            raise RuntimeError("model unavailable")
        return ["proposal"]


def _install_evaluator(monkeypatch, orchestrator, *, fail):
    _Evaluator.fail = fail
    monkeypatch.setattr(orchestrator_module, "MemoryEvaluator", _Evaluator)

    async def _store(proposals):
        return len(proposals)

    monkeypatch.setattr(orchestrator, "_store_memory_proposals", _store)


def test_no_signals_stamps_nothing(tmp_path, monkeypatch):
    orchestrator = _orchestrator(tmp_path, monkeypatch, [], [])
    stamped = _capture_stamps(monkeypatch)
    asyncio.run(orchestrator.run_daily_sweep())
    assert stamped == []


def test_successful_evaluation_stamps_the_entries_it_read(tmp_path, monkeypatch):
    orchestrator = _orchestrator(tmp_path, monkeypatch, [_signal()], ["e1", "e2"])
    stamped = _capture_stamps(monkeypatch)
    _install_evaluator(monkeypatch, orchestrator, fail=False)

    result = asyncio.run(orchestrator.run_daily_sweep())
    assert result.memory_proposals_added == 1
    # Includes e2, which produced no signal - declined rows are still consumed.
    assert stamped == ["e1", "e2"]


def test_failed_evaluation_leaves_the_entries_unstamped(tmp_path, monkeypatch):
    orchestrator = _orchestrator(tmp_path, monkeypatch, [_signal()], ["e1"])
    stamped = _capture_stamps(monkeypatch)
    _install_evaluator(monkeypatch, orchestrator, fail=True)

    result = asyncio.run(orchestrator.run_daily_sweep())
    assert result.errors
    # The next sweep must see e1 again rather than losing it to a dead model.
    assert stamped == []


def test_the_memory_signals_watermark_is_gone(tmp_path, monkeypatch):
    """Zettel consumption is per-row now; only the skill sweep keeps a cursor."""
    orchestrator = _orchestrator(tmp_path, monkeypatch, [], [])
    assert "memory_signals" not in orchestrator._read_watermarks()
    assert "agent_tasks" in orchestrator._read_watermarks()


def test_a_stale_watermark_file_is_read_without_error(tmp_path, monkeypatch):
    """Existing installs may still have the old key on disk; it is simply ignored."""
    orchestrator = _orchestrator(tmp_path, monkeypatch, [], [])
    orchestrator.watermark_path.parent.mkdir(parents=True, exist_ok=True)
    orchestrator.watermark_path.write_text(
        '{"agent_tasks": "2026-07-01T00:00:00+00:00", '
        '"memory_signals": "2026-07-24T10:00:00+00:00"}',
        encoding="utf-8",
    )
    watermarks = orchestrator._read_watermarks()
    assert watermarks == {"agent_tasks": "2026-07-01T00:00:00+00:00"}
