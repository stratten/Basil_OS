"""The finalizing pass: finalize valid narratives and cap failed retries."""

import asyncio

import pytest

from .conftest import NonClosingConnection
from api.services.zettel import store
from api.services.zettel.narrative import enricher as enricher_module
from api.services.zettel.narrative.enricher import ZettelEnricher
from api.services.zettel.narrative.narrative_processing_run_policy import (
    NarrativeProcessingRunPolicy,
)
from api.services.zettel.narrative.synthesizer import SynthesisError, SynthesisResult, _parse
from api.services.zettel.sources.base import ZettelDraft


class _FakeSource:
    source_kind = "agent_task"

    def gather_context(self, conn, source_ids):
        return {sid: {"result_data": f"work for {sid}"} for sid in source_ids}


def _enricher(conn):
    e = ZettelEnricher(sources={"agent_task": _FakeSource()})
    e._connection = lambda: NonClosingConnection(conn)
    return e


def _card(conn, source_id):
    store.insert_card(conn, ZettelDraft(
        source_kind="agent_task", source_id=source_id, event_type="agent_task_run",
        occurred_at="2026-07-24T10:00:00+00:00", title=f"Task {source_id}",
    ))


def test_closed_entry_is_finalized(conn, monkeypatch):
    _card(conn, "t1")

    async def _fake(entry, context, *, model_id=None):
        assert context == {"result_data": "work for t1"}
        return SynthesisResult(narrative="You finished it.", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = asyncio.run(_enricher(conn).run_pass(batch_size=10, max_attempts=3))
    assert result.finalized == 1
    row = conn.execute("SELECT narrative, narrative_state FROM zettel_entries").fetchone()
    assert row["narrative"] == "You finished it."
    assert row["narrative_state"] == "final"


def test_legacy_open_payload_is_finalized(conn, monkeypatch):
    _card(conn, "t1")

    async def _fake(entry, context, *, model_id=None):
        return _parse(
            '{"narrative":"Still going.","is_open":true,"open_note":"mid-run"}',
            "m",
        )

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = asyncio.run(_enricher(conn).run_pass(batch_size=10, max_attempts=3))
    assert result.still_open == 0
    assert result.finalized == 1
    row = conn.execute(
        "SELECT narrative_state, is_open, open_note FROM zettel_entries"
    ).fetchone()
    assert tuple(row) == ("final", 0, None)


def test_attempt_cap_marks_failed(conn, monkeypatch):
    _card(conn, "t1")

    async def _boom(entry, context, *, model_id=None):
        raise SynthesisError("no model")

    monkeypatch.setattr(enricher_module, "synthesize", _boom)
    result = asyncio.run(_enricher(conn).run_pass(batch_size=10, max_attempts=1))
    assert result.failed == 1
    row = conn.execute("SELECT narrative_state, narrative_attempts FROM zettel_entries").fetchone()
    assert row["narrative_state"] == "failed"
    assert row["narrative_attempts"] == 1


def test_pass_drains_backlog_beyond_one_chunk(conn, monkeypatch):
    for i in range(3):
        _card(conn, f"t{i}")

    async def _fake(entry, context, *, model_id=None):
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    # A chunk of 1 still drains all three in a single run.
    result = asyncio.run(_enricher(conn).run_pass(batch_size=1, max_attempts=3))
    assert result.finalized == 3
    finals = conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE narrative_state='final'"
    ).fetchone()["n"]
    assert finals == 3


def test_valid_entry_is_not_reprocessed_within_a_run(conn, monkeypatch):
    _card(conn, "t1")
    calls = {"n": 0}

    async def _fake(entry, context, *, model_id=None):
        calls["n"] += 1
        return SynthesisResult(narrative="still", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = asyncio.run(_enricher(conn).run_pass(batch_size=5, max_attempts=3))
    assert calls["n"] == 1
    assert result.finalized == 1
    assert conn.execute(
        "SELECT narrative_state FROM zettel_entries"
    ).fetchone()[0] == "final"


def test_nothing_pending_is_a_noop(conn, monkeypatch):
    async def _fake(entry, context, *, model_id=None):  # pragma: no cover - never called
        raise AssertionError("should not be called")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = asyncio.run(_enricher(conn).run_pass(batch_size=10, max_attempts=3))
    assert result.finalized == 0 and result.still_open == 0 and result.failed == 0


def test_cancel_stops_pass_after_current_entry(conn, monkeypatch):
    for i in range(3):
        _card(conn, f"t{i}")

    enricher = _enricher(conn)
    calls = {"n": 0}

    async def _fake(entry, context, *, model_id=None):
        calls["n"] += 1
        enricher.request_cancel()
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))

    # The entry in flight when cancel arrived still completes and is recorded;
    # cancellation is cooperative rather than an aborted model call.
    assert calls["n"] == 1
    assert result.finalized == 1

    states = [
        row["narrative_state"]
        for row in conn.execute("SELECT narrative_state FROM zettel_entries").fetchall()
    ]
    assert states.count("final") == 1
    assert states.count("pending") == 2

    # Entries never reached keep a zero attempt count, so cancelling does not
    # burn retries or push anything toward 'failed'.
    untouched = conn.execute(
        "SELECT narrative_attempts FROM zettel_entries WHERE narrative_state='pending'"
    ).fetchall()
    assert all(row["narrative_attempts"] == 0 for row in untouched)

    progress = enricher.get_progress()
    assert progress.cancel_requested is True
    assert progress.active is False


def test_request_cancel_is_false_when_no_pass_is_running(conn):
    assert _enricher(conn).request_cancel() is False


def test_cancel_flag_does_not_leak_into_the_next_pass(conn, monkeypatch):
    _card(conn, "t1")
    enricher = _enricher(conn)

    async def _cancelling(entry, context, *, model_id=None):
        enricher.request_cancel()
        return SynthesisResult(narrative="one", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _cancelling)
    asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))
    assert enricher.get_progress().cancel_requested is True

    _card(conn, "t2")

    async def _fine(entry, context, *, model_id=None):
        return SynthesisResult(narrative="two", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fine)
    result = asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))
    assert result.finalized == 1
    assert enricher.get_progress().cancel_requested is False


def test_max_records_stops_the_run_and_leaves_the_rest_pending(conn, monkeypatch):
    for i in range(5):
        _card(conn, f"t{i}")
    calls = {"n": 0}

    async def _fake(entry, context, *, model_id=None):
        calls["n"] += 1
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = asyncio.run(
        _enricher(conn).run_pass(batch_size=10, max_attempts=3, max_records=2)
    )

    assert calls["n"] == 2
    assert result.finalized == 2
    # Untouched entries stay queued; the cap bounds the run, not the queue.
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE narrative_state='pending'"
    ).fetchone()["n"] == 3


def test_max_records_caps_the_run_even_when_the_chunk_is_larger(conn, monkeypatch):
    """The chunk read must not gather context for entries the run won't touch."""
    for i in range(5):
        _card(conn, f"t{i}")
    gathered: list = []

    class _CountingSource:
        def find_uncarded(self, conn, *, since_iso, limit):  # pragma: no cover
            return []

        def stamp(self, conn, entry_id, source_ids):  # pragma: no cover
            return None

        def count_uncarded(self, conn, *, since_iso):  # pragma: no cover
            return 0

        def gather_context(self, conn, ids):
            gathered.extend(ids)
            return {source_id: {} for source_id in ids}

    async def _fake(entry, context, *, model_id=None):
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    enricher = enricher_module.ZettelEnricher(sources={"agent_task": _CountingSource()})
    enricher._connection = lambda: NonClosingConnection(conn)  # type: ignore[method-assign]
    asyncio.run(enricher.run_pass(batch_size=50, max_attempts=3, max_records=2))

    assert len(gathered) == 2


def test_max_records_zero_or_none_means_no_limit(conn, monkeypatch):
    for i in range(4):
        _card(conn, f"t{i}")

    async def _fake(entry, context, *, model_id=None):
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = asyncio.run(
        _enricher(conn).run_pass(batch_size=10, max_attempts=3, max_records=0)
    )
    assert result.finalized == 4


def test_progress_total_reflects_the_capped_target(conn, monkeypatch):
    """ETA and the progress bar must describe this run, not the whole backlog."""
    for i in range(10):
        _card(conn, f"t{i}")

    async def _fake(entry, context, *, model_id=None):
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    enricher = _enricher(conn)
    asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3, max_records=3))

    assert enricher.get_progress().total == 3
    assert enricher.get_progress().processed == 3


def test_valid_entry_is_not_reprocessed_on_a_later_pass(conn, monkeypatch):
    _card(conn, "t1")
    calls = {"n": 0}

    async def _fake(entry, context, *, model_id=None):
        calls["n"] += 1
        return SynthesisResult(narrative="still", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    enricher = _enricher(conn)
    for _ in range(2):
        asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))

    assert calls["n"] == 1
    assert conn.execute(
        "SELECT narrative_state FROM zettel_entries"
    ).fetchone()["narrative_state"] == "final"


def test_run_policy_concurrency_and_strategy_appear_on_progress(conn, monkeypatch):
    _card(conn, "t1")
    invoked_model_ids = []

    async def _fake(entry, context, *, model_id=None, model_stage_semaphore=None):
        invoked_model_ids.append(model_id)
        return SynthesisResult(narrative="done", model_name=model_id)

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    enricher = _enricher(conn)
    policy = NarrativeProcessingRunPolicy(
        model_id="cloud-model",
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )

    asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3, run_policy=policy))

    progress = enricher.get_progress()
    assert invoked_model_ids == ["cloud-model"]
    assert progress.analysis_concurrency == 8
    assert progress.processing_strategy == "api_parallel"


def test_default_run_policy_stays_sequential_on_progress(conn, monkeypatch):
    _card(conn, "t1")

    async def _fake(entry, context, *, model_id=None):
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    enricher = _enricher(conn)

    asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))

    progress = enricher.get_progress()
    assert progress.analysis_concurrency == 1
    assert progress.processing_strategy == "sequential"


@pytest.mark.asyncio
async def test_api_parallel_policy_actually_overlaps_synthesis_calls(conn, monkeypatch):
    _card(conn, "t1")
    _card(conn, "t2")
    active_calls = 0
    max_concurrent_calls = 0
    both_entered = asyncio.Event()

    async def _fake(entry, context, *, model_id=None, model_stage_semaphore=None):
        nonlocal active_calls, max_concurrent_calls
        active_calls += 1
        max_concurrent_calls = max(max_concurrent_calls, active_calls)
        if active_calls == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=5)
        active_calls -= 1
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    policy = NarrativeProcessingRunPolicy(
        model_id="cloud-model",
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )
    result = await asyncio.wait_for(
        _enricher(conn).run_pass(batch_size=10, max_attempts=3, run_policy=policy),
        timeout=5,
    )

    assert max_concurrent_calls == 2
    assert result.finalized == 2


@pytest.mark.asyncio
async def test_sequential_policy_never_overlaps_synthesis_calls(conn, monkeypatch):
    _card(conn, "t1")
    _card(conn, "t2")
    active_calls = 0
    max_concurrent_calls = 0

    async def _fake(entry, context, *, model_id=None):
        nonlocal active_calls, max_concurrent_calls
        active_calls += 1
        max_concurrent_calls = max(max_concurrent_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    result = await asyncio.wait_for(
        _enricher(conn).run_pass(batch_size=10, max_attempts=3),
        timeout=5,
    )

    assert max_concurrent_calls == 1
    assert result.finalized == 2


@pytest.mark.asyncio
async def test_api_parallel_run_respects_max_records_cap(conn, monkeypatch):
    for index in range(5):
        _card(conn, f"t{index}")

    async def _fake(entry, context, *, model_id=None, model_stage_semaphore=None):
        await asyncio.sleep(0.01)
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    policy = NarrativeProcessingRunPolicy(
        model_id="cloud-model",
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )
    result = await asyncio.wait_for(
        _enricher(conn).run_pass(
            batch_size=10,
            max_attempts=3,
            max_records=2,
            run_policy=policy,
        ),
        timeout=5,
    )

    assert result.finalized == 2
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE narrative_state='pending'"
    ).fetchone()["n"] == 3


@pytest.mark.asyncio
async def test_api_parallel_cancellation_finishes_in_flight_items_without_new_admissions(
    conn, monkeypatch
):
    for index in range(10):
        _card(conn, f"t{index}")

    enricher = _enricher(conn)
    in_flight = 0
    all_workers_started = asyncio.Event()
    release_workers = asyncio.Event()

    async def _fake(entry, context, *, model_id=None, model_stage_semaphore=None):
        nonlocal in_flight
        in_flight += 1
        if in_flight == 8:
            all_workers_started.set()
        await release_workers.wait()
        return SynthesisResult(narrative="done", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    policy = NarrativeProcessingRunPolicy(
        model_id="cloud-model",
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )
    pass_task = asyncio.create_task(
        enricher.run_pass(batch_size=10, max_attempts=3, run_policy=policy)
    )
    await asyncio.wait_for(all_workers_started.wait(), timeout=5)
    assert enricher.request_cancel() is True
    release_workers.set()
    result = await asyncio.wait_for(pass_task, timeout=5)

    assert result.finalized == 8
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE narrative_state='pending'"
    ).fetchone()["n"] == 2


@pytest.mark.asyncio
async def test_api_parallel_write_error_waits_for_sibling_generations(conn, monkeypatch):
    _card(conn, "t1")
    _card(conn, "t2")
    enricher = _enricher(conn)
    calls_started = 0
    both_started = asyncio.Event()
    release_second = asyncio.Event()
    write_failed = asyncio.Event()

    async def _fake(entry, context, *, model_id=None, model_stage_semaphore=None):
        nonlocal calls_started
        calls_started += 1
        call_number = calls_started
        if calls_started == 2:
            both_started.set()
        await both_started.wait()
        if call_number == 2:
            await release_second.wait()
        return SynthesisResult(narrative="done", model_name="m")

    original_record_success = enricher._record_success
    write_calls = 0

    def _record_success(entry_id, synthesis, result):
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            write_failed.set()
            raise RuntimeError("database write failed")
        original_record_success(entry_id, synthesis, result)

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    monkeypatch.setattr(enricher, "_record_success", _record_success)
    policy = NarrativeProcessingRunPolicy(
        model_id="cloud-model",
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )
    pass_task = asyncio.create_task(
        enricher.run_pass(batch_size=10, max_attempts=3, run_policy=policy)
    )

    await asyncio.wait_for(write_failed.wait(), timeout=5)
    assert pass_task.done() is False
    assert enricher.get_progress().active is True

    release_second.set()
    with pytest.raises(RuntimeError, match="database write failed"):
        await asyncio.wait_for(pass_task, timeout=5)

    assert enricher.get_progress().active is False
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE narrative_state='final'"
    ).fetchone()["n"] == 1
