"""An unavailable model must not burn retries, and entries with nothing to summarize are discarded instead of failing forever."""

import asyncio

import pytest

from .conftest import NonClosingConnection
from api.services.zettel import store
from api.services.zettel.narrative import enricher as enricher_module
from api.services.zettel.narrative.enricher import ZettelEnricher
from api.services.zettel.narrative.synthesizer import (
    ModelUnavailableError,
    SynthesisResult,
    synthesize,
)
from api.services.zettel.narrative.unsummarizable import discard_unsummarizable, is_unsummarizable, value_has_content
from api.services.zettel.sources.base import ZettelDraft, sources_by_kind


class _FakeSource:
    source_kind = "agent_task"

    def gather_context(self, conn, source_ids):
        return {sid: {"result_data": f"work for {sid}"} for sid in source_ids}


def _enricher(conn, sources=None):
    e = ZettelEnricher(sources=sources if sources is not None else {"agent_task": _FakeSource()})
    e._connection = lambda: NonClosingConnection(conn)
    return e


def _card(conn, source_id, *, kind="agent_task", event_type="agent_task_run", summary=None, status=None):
    store.insert_card(conn, ZettelDraft(
        source_kind=kind, source_id=source_id, event_type=event_type,
        occurred_at="2026-07-24T10:00:00+00:00", title=f"Entry {source_id}", summary=summary, source_status=status,
    ))


def _transcription(conn, transcription_id, text, status="completed"):
    conn.execute(
        "INSERT INTO transcriptions (id, timestamp, status, transcription_text, model_name, audio_file_path) VALUES (?, ?, ?, ?, ?, ?)",
        (transcription_id, "2026-07-24T10:00:00", status, text, "test-model", "/tmp/none.wav"),
    )


def _entry_state(conn, source_id):
    row = conn.execute(
        "SELECT narrative_state, narrative_attempts, narrative_error FROM zettel_entries WHERE source_id = ?", (source_id,)
    ).fetchone()
    return None if row is None else tuple(row)


# ---- model unavailable -------------------------------------------------------


def test_an_unavailable_model_leaves_every_entry_pending_and_uncharged_and_stops_the_pass(conn, monkeypatch):
    for index in range(5):
        _card(conn, f"t{index}")
    calls = []

    async def _unavailable(entry, context, *, model_id=None):
        calls.append(entry["entry_id"])
        raise ModelUnavailableError("Model is not loaded")

    monkeypatch.setattr(enricher_module, "synthesize", _unavailable)

    result = asyncio.run(_enricher(conn).run_pass(batch_size=2, max_attempts=3))

    assert result.finalized == 0 and result.failed == 0
    assert len(calls) <= 2, "the pass must stop admitting work once the model is known to be unavailable"
    for index in range(5):
        assert _entry_state(conn, f"t{index}") == ("pending", 0, None)
    assert len(result.errors) == 1 and "Model unavailable (Model is not loaded)" in result.errors[0]


def test_repeated_unavailable_passes_never_exhaust_an_entry(conn, monkeypatch):
    _card(conn, "t1")

    async def _unavailable(entry, context, *, model_id=None):
        raise ModelUnavailableError("Model is not loaded")

    monkeypatch.setattr(enricher_module, "synthesize", _unavailable)
    enricher = _enricher(conn)
    for _ in range(6):
        asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))

    assert _entry_state(conn, "t1") == ("pending", 0, None)

    async def _fine(entry, context, *, model_id=None):
        return SynthesisResult(narrative="Recovered.", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fine)
    result = asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))
    assert result.finalized == 1 and result.errors == []


def test_a_real_bad_reply_still_costs_an_attempt(conn, monkeypatch):
    from api.services.zettel.narrative.synthesizer import SynthesisError

    _card(conn, "t1")

    async def _bad(entry, context, *, model_id=None):
        raise SynthesisError("Model reply contained no JSON object with a narrative")

    monkeypatch.setattr(enricher_module, "synthesize", _bad)
    asyncio.run(_enricher(conn).run_pass(batch_size=10, max_attempts=3))

    assert _entry_state(conn, "t1")[:2] == ("pending", 1)


@pytest.mark.asyncio
async def test_synthesize_reports_not_loaded_and_no_model_as_unavailable_not_as_a_bad_entry(monkeypatch):
    class _Unloaded:
        model_name = "unloaded-model"

        async def generate_response(self, prompt, context=None, max_tokens=1024):
            raise RuntimeError("Model is not loaded")

    async def _get_unloaded(*args, **kwargs):
        return _Unloaded()

    async def _get_none(*args, **kwargs):
        return None

    entry = {"entry_id": "agent_task:t1", "title": "Task", "summary": "Did work"}
    monkeypatch.setattr("api.dependencies.get_model_usage_service", lambda: type("S", (), {"get_model_for_task": _get_unloaded})())
    with pytest.raises(ModelUnavailableError):
        await synthesize(entry, {"result_data": "details"})

    monkeypatch.setattr("api.dependencies.get_model_usage_service", lambda: type("S", (), {"get_model_for_task": _get_none})())
    with pytest.raises(ModelUnavailableError):
        await synthesize(entry, {"result_data": "details"})


@pytest.mark.asyncio
async def test_a_different_runtime_error_is_not_mistaken_for_an_unavailable_model(monkeypatch):
    class _Broken:
        model_name = "broken-model"

        async def generate_response(self, prompt, context=None, max_tokens=1024):
            raise RuntimeError("CUDA out of memory")

    async def _get_broken(*args, **kwargs):
        return _Broken()

    monkeypatch.setattr("api.dependencies.get_model_usage_service", lambda: type("S", (), {"get_model_for_task": _get_broken})())
    with pytest.raises(RuntimeError, match="CUDA out of memory") as raised:
        await synthesize({"entry_id": "agent_task:t1", "title": "Task", "summary": "Did work"}, {"result_data": "details"})
    assert not isinstance(raised.value, ModelUnavailableError)


# ---- nothing to summarize ----------------------------------------------------


def test_the_discard_rule_in_isolation():
    assert value_has_content({"a": None, "b": {"c": " "}, "d": []}) is False
    assert value_has_content({"a": None, "b": {"c": "text"}}) is True
    assert value_has_content({"count": 0}) is True
    assert is_unsummarizable(summary=None, source_status="completed", context={"transcription_text": ""}) is True
    assert is_unsummarizable(summary="  ", source_status=None, context={}) is True
    assert is_unsummarizable(summary="hello", source_status="completed", context={}) is False
    assert is_unsummarizable(summary=None, source_status="completed", context={"transcription_text": "words"}) is False
    assert is_unsummarizable(summary=None, source_status="pending", context={"transcription_text": ""}) is False
    assert is_unsummarizable(summary=None, source_status="scheduled", context=None) is False


def test_an_empty_completed_transcription_is_discarded_and_everything_else_is_kept(conn):
    _transcription(conn, "empty-done", "")
    _transcription(conn, "blank-done", "   ")
    _transcription(conn, "empty-pending", "", status="pending")
    _transcription(conn, "has-text", "Remember to call the dentist.")
    for source_id in ("empty-done", "blank-done", "empty-pending", "has-text"):
        _card(conn, source_id, kind="transcription", event_type="transcription", summary=None, status=None)
    conn.execute("UPDATE zettel_entries SET source_status = 'completed' WHERE source_id IN ('empty-done', 'blank-done', 'has-text')")
    conn.execute("UPDATE zettel_entries SET source_status = 'pending' WHERE source_id = 'empty-pending'")
    conn.execute("UPDATE zettel_entries SET narrative_state = 'failed', narrative_attempts = 3 WHERE source_id = 'empty-done'")

    discarded = discard_unsummarizable(conn, sources_by_kind())

    assert discarded == 2
    assert _entry_state(conn, "empty-done") is None
    assert _entry_state(conn, "blank-done") is None
    assert _entry_state(conn, "empty-pending")[0] == "pending"
    assert _entry_state(conn, "has-text")[0] == "pending"


def test_a_final_entry_is_never_discarded_even_when_its_source_is_empty(conn):
    _transcription(conn, "empty-final", "")
    _card(conn, "empty-final", kind="transcription", event_type="transcription", status="completed")
    store.write_narrative(conn, conn.execute("SELECT id FROM zettel_entries").fetchone()["id"], narrative="Kept.", model="m")

    assert discard_unsummarizable(conn, sources_by_kind()) == 0
    assert _entry_state(conn, "empty-final")[0] == "final"


def test_a_failing_source_is_skipped_not_treated_as_empty(conn):
    _card(conn, "t1", status="completed")

    class _Exploding:
        source_kind = "agent_task"

        def gather_context(self, conn, source_ids):
            raise RuntimeError("source table unavailable")

    assert discard_unsummarizable(conn, {"agent_task": _Exploding()}) == 0
    assert _entry_state(conn, "t1")[0] == "pending"


def test_a_discarded_entry_is_not_carded_again_because_its_source_row_stays_stamped(conn):
    from api.services.zettel.materializer import ZettelMaterializer

    _transcription(conn, "empty-done", "")
    materializer = ZettelMaterializer()
    materializer._connection = lambda: NonClosingConnection(conn)
    materializer.run_pass()
    entry = conn.execute("SELECT id, source_status FROM zettel_entries WHERE source_id = 'empty-done'").fetchone()
    assert entry is not None, "the empty transcription should have been carded before it is discarded"

    assert discard_unsummarizable(conn, sources_by_kind()) == 1
    assert _entry_state(conn, "empty-done") is None
    materializer.run_pass()

    assert _entry_state(conn, "empty-done") is None


def test_the_pass_discards_before_counting_and_never_calls_the_model_for_an_empty_entry(conn, monkeypatch):
    _transcription(conn, "empty-done", "")
    _transcription(conn, "has-text", "Real words.")
    for source_id in ("empty-done", "has-text"):
        _card(conn, source_id, kind="transcription", event_type="transcription", status="completed")
    seen = []

    async def _fake(entry, context, *, model_id=None):
        seen.append(entry["source_id"])
        return SynthesisResult(narrative="Done.", model_name="m")

    monkeypatch.setattr(enricher_module, "synthesize", _fake)
    enricher = _enricher(conn, sources=sources_by_kind())
    result = asyncio.run(enricher.run_pass(batch_size=10, max_attempts=3))

    assert seen == ["has-text"]
    assert result.discarded == 1 and result.finalized == 1
    assert enricher.get_progress().total == 1
