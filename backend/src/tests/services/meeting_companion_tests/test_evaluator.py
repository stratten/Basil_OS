import asyncio
import itertools

import pytest

from api.core.models.model_invocation import StructuredModelOutputError, StructuredModelResponse
from api.services.meeting_companion.context_pack import ContextExcerpt, ContextPack
from api.services.meeting_companion.evaluator import (
    CompanionEvaluationResponse,
    CompanionEvaluator,
    EvaluatedItem,
    EvaluationRequest,
    materialize_items,
)
from api.services.meeting_companion.models import CompanionTurn, CompanionWatch


def make_turn(index, text, start):
    return CompanionTurn(id=f"t-{index:05d}", source_meeting_id="m", role="other", speaker="Zoom", start=start, end=start + 3, text=text)


def make_request(**overrides):
    turns = [make_turn(1, "How does the retry policy handle timeouts", 10.0), make_turn(2, "I think it backs off", 14.0)]
    pack = ContextPack(excerpts=[ContextExcerpt("c1", "r1", "proj/retry.py", 3, 9, "def backoff(attempt): return min(30, 2 ** attempt)", 5.0)])
    values = dict(
        trigger="question",
        mode="active",
        meeting_time=17.0,
        new_turns=turns,
        window_turns=turns,
        conversation_state="Team discusses retries.",
        already_shown=[],
        pack=pack,
        has_roots=True,
        watch=None,
        model_id=None,
    )
    values.update(overrides)
    return EvaluationRequest(**values)


def counter_ids():
    sequence = itertools.count(1)
    return lambda: f"it-{next(sequence)}"


def item(text, kind="answer", confidence=0.9, pack_ids=(), source_turn_ids=()):
    return EvaluatedItem(kind=kind, text=text, confidence=confidence, pack_ids=list(pack_ids), source_turn_ids=list(source_turn_ids))


def test_materialize_resolves_citations_and_ranges():
    response = CompanionEvaluationResponse(items=[item("Backoff is capped at thirty seconds.", pack_ids=["c1", "c9"], source_turn_ids=["t-00001"])])
    items, dropped = materialize_items(response, make_request(), id_factory=counter_ids())
    assert dropped == 0 and len(items) == 1
    assert items[0].id == "it-1" and items[0].no_source is False
    assert [citation.path for citation in items[0].citations] == ["proj/retry.py"]
    assert (items[0].transcript_range.start, items[0].transcript_range.end) == (10.0, 13.0)
    assert items[0].transcript_range.turn_ids == ["t-00001"]


def test_answer_without_valid_citation_is_marked_no_source_but_insight_is_not():
    response = CompanionEvaluationResponse(
        items=[item("Probably exponential backoff.", pack_ids=["c9"]), item("This conflicts with last week's plan.", kind="insight")]
    )
    items, _ = materialize_items(response, make_request(), id_factory=counter_ids())
    assert [entry.no_source for entry in items] == [True, False]
    assert items[0].transcript_range.turn_ids == ["t-00001", "t-00002"]


def test_confidence_floor_depends_on_trigger_and_values_are_clamped():
    response = CompanionEvaluationResponse(items=[item("Maybe worth noting something here.", kind="insight", confidence=0.5)])
    assert materialize_items(response, make_request(trigger="periodic"), id_factory=counter_ids())[0] == []
    assert len(materialize_items(response, make_request(trigger="question"), id_factory=counter_ids())[0]) == 1
    clamped = CompanionEvaluationResponse(items=[item("Strong claim worth showing now.", kind="insight", confidence=7.5)])
    assert materialize_items(clamped, make_request(trigger="periodic"), id_factory=counter_ids())[0][0].confidence == 1.0


def test_duplicates_blank_text_and_item_cap_are_dropped():
    already = ["The retry policy caps backoff at thirty seconds."]
    response = CompanionEvaluationResponse(
        items=[
            item("The retry policy caps its backoff at thirty seconds.", kind="insight"),
            item("   ", kind="insight"),
            item("Timeouts are configured per upstream service.", kind="insight"),
            item("Retries are logged with a correlation identifier.", kind="insight"),
            item("A third distinct note about deployment windows.", kind="insight"),
        ]
    )
    items, dropped = materialize_items(response, make_request(already_shown=already), id_factory=counter_ids())
    assert [entry.text for entry in items] == ["Timeouts are configured per upstream service.", "Retries are logged with a correlation identifier."]
    assert dropped == 3


def test_long_text_is_cut_and_watch_id_is_recorded():
    watch = CompanionWatch(id="w1", topic="retry", instruction="Summarize retries", keywords=["retry"], created_at=0)
    response = CompanionEvaluationResponse(items=[item("word " * 400, kind="insight")])
    items, _ = materialize_items(response, make_request(trigger="watch", watch=watch), id_factory=counter_ids())
    assert len(items[0].text) <= 600 and items[0].watch_id == "w1"


def test_prompt_contains_rules_sections_pack_and_watch_instruction():
    watch = CompanionWatch(id="w1", topic="retry", instruction="Summarize retries", keywords=["retry"], created_at=0)
    prompt = CompanionEvaluator().build_prompt(make_request(trigger="watch", watch=watch, already_shown=["Earlier note."]))
    for expected in (
        "Silence is the default",
        "TRIGGER",
        "STANDING REQUEST FROM THE USER\nSummarize retries",
        "CONVERSATION SO FAR\nTeam discusses retries.",
        "- Earlier note.",
        '<excerpt id="c1" path="proj/retry.py"',
        "[t-00001 @ 00:10] Zoom: How does the retry policy handle timeouts",
        "NEW SINCE LAST EVALUATION\nt-00001, t-00002",
    ):
        assert expected in prompt


def test_prompt_states_when_nothing_is_attached_or_found():
    no_roots = CompanionEvaluator().build_prompt(make_request(has_roots=False, pack=None))
    assert "(no files are attached)" in no_roots
    empty = CompanionEvaluator().build_prompt(make_request(pack=ContextPack()))
    assert "nothing relevant was found" in empty


class FakeModel:
    pass


def make_evaluator(caller, loader=None, **overrides):
    async def default_loader(model_id):
        default_loader.calls.append(model_id)
        return FakeModel()

    default_loader.calls = []
    evaluator = CompanionEvaluator(
        model_loader=loader or default_loader,
        schema_caller=caller,
        token_budget=lambda model: 800,
        id_factory=counter_ids(),
        **overrides,
    )
    return evaluator, (loader or default_loader)


@pytest.mark.asyncio
async def test_evaluate_success_returns_items_and_state():
    seen = {}

    async def caller(model, *, prompt, response_model, max_tokens):
        seen.update(prompt=prompt, max_tokens=max_tokens, response_model=response_model)
        value = CompanionEvaluationResponse(
            items=[item("Backoff is capped at thirty seconds.", pack_ids=["c1"], source_turn_ids=["t-00001"])],
            conversation_state="Retries are being reviewed.",
        )
        return StructuredModelResponse(value=value, enforcement="strict_json_fallback", finish_reason="stop")

    evaluator, _ = make_evaluator(caller)
    outcome = await evaluator.evaluate(make_request())
    assert outcome.error is None and len(outcome.items) == 1
    assert outcome.conversation_state == "Retries are being reviewed." and outcome.finish_reason == "stop"
    assert seen["max_tokens"] == 800 and seen["response_model"] is CompanionEvaluationResponse and "TRIGGER" in seen["prompt"]


@pytest.mark.asyncio
async def test_model_is_loaded_once_per_selection():
    async def caller(model, *, prompt, response_model, max_tokens):
        return StructuredModelResponse(value=CompanionEvaluationResponse(), enforcement="strict_json_fallback")

    evaluator, loader = make_evaluator(caller)
    await evaluator.evaluate(make_request(model_id="a"))
    await evaluator.evaluate(make_request(model_id="a"))
    await evaluator.evaluate(make_request(model_id="b"))
    assert loader.calls == ["a", "b"]


@pytest.mark.asyncio
async def test_loader_failure_is_returned_not_raised():
    async def loader(model_id):
        raise RuntimeError("no model")

    async def caller(*args, **kwargs):
        raise AssertionError("caller must not run")

    evaluator, _ = make_evaluator(caller, loader=loader)
    outcome = await evaluator.evaluate(make_request())
    assert outcome.items == [] and outcome.error.startswith("model_unavailable")


@pytest.mark.asyncio
async def test_structured_and_unexpected_errors_are_returned():
    async def structured(model, *, prompt, response_model, max_tokens):
        raise StructuredModelOutputError("bad json", category="provider", retryable=False)

    evaluator, loader = make_evaluator(structured)
    outcome = await evaluator.evaluate(make_request())
    assert outcome.error.startswith("provider:")
    await evaluator.evaluate(make_request())
    assert loader.calls == [None, None]

    async def unexpected(model, *, prompt, response_model, max_tokens):
        raise ValueError("kaboom")

    evaluator, _ = make_evaluator(unexpected)
    assert (await evaluator.evaluate(make_request())).error.startswith("evaluation_failed")


@pytest.mark.asyncio
async def test_timeout_is_returned():
    async def slow(model, *, prompt, response_model, max_tokens):
        await asyncio.sleep(1)

    evaluator, _ = make_evaluator(slow, timeout_seconds=0.01)
    outcome = await evaluator.evaluate(make_request())
    assert outcome.error == "timeout" and outcome.items == []


def test_evaluation_prompt_carries_the_user_focus_only_when_set():
    assert "USER FOCUS" not in CompanionEvaluator().build_prompt(make_request())
    prompt = CompanionEvaluator().build_prompt(make_request(focus=" Watch for budget risk "))
    assert "USER FOCUS" in prompt
    assert "Watch for budget risk" in prompt
    assert prompt.index("USER FOCUS") < prompt.index("CONVERSATION SO FAR")
