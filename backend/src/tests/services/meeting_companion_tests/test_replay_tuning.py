import json
from types import SimpleNamespace

import pytest

from api.services.meeting_companion import evaluator as evaluator_module
from api.services.meeting_companion import prompts as prompts_module
from api.services.meeting_companion.evaluator import CompanionEvaluationResponse, CompanionEvaluator
from api.services.meeting_companion.models import AuditMoment, CompanionItem, CompanionTurn, TranscriptRange
from api.services.meeting_companion.replay import replay
from api.services.meeting_companion.replay_compare import ComparisonRow, RecordedCaller, RecordingCaller, format_comparison, load_marked_moments, row_for
from api.services.meeting_companion.replay_scoring import ReplayScore, improves, score_replay
from api.services.meeting_companion.replay_tuning import CANDIDATES, ORIGINAL_RULE_ONE, applied, candidate_names, gate_config_for, resolve

STATEMENT = "We should review the deployment pipeline for the billing service today"


def moment(moment_id, start, end, mark, text="Remember the Friday deadline for billing."):
    return AuditMoment(id=moment_id, start=start, end=end, kind="note", why="Missed", suggested_text=text, confidence=0.8, mark=mark)


def item(item_id, start, end, text="Something unrelated entirely about lunch", kind="suggestion"):
    return CompanionItem(id=item_id, kind=kind, text=text, confidence=0.9, transcript_range=TranscriptRange(start=start, end=end), trigger="periodic")


def turns():
    return [
        CompanionTurn(id=f"t-{index + 1:05d}", source_meeting_id="m", role="other", speaker="Zoom", start=index * 10.0, end=index * 10.0 + 3.0, text=STATEMENT)
        for index in range(12)
    ]


def test_scoring_counts_agreed_matches_silence_broken_and_other_notes():
    moments = [moment("a1", 100, 110, "agree"), moment("a2", 400, 410, "agree"), moment("d1", 200, 210, "disagree"), moment("u1", 300, 310, None)]
    notes = [item("n1", 105, 108), item("n2", 205, 207), item("n3", 700, 710), item("p1", 400, 405, kind="proposal")]
    score = score_replay(notes, moments)
    assert (score.agreed_total, score.agreed_matched) == (2, 1)
    assert (score.disagreed_total, score.disagreed_hit) == (1, 1)
    assert score.items == 3 and score.unmatched_items == 1
    assert score.matched_moment_ids == ["a1"]


def test_scoring_matches_a_nearby_note_only_when_it_says_something_similar():
    moments = [moment("a1", 100, 110, "agree")]
    near_similar = item("n1", 130, 135, text="Remember the Friday deadline for billing work")
    near_different = item("n2", 130, 135, text="Completely different subject matter here")
    far_similar = item("n3", 900, 905, text="Remember the Friday deadline for billing work")
    assert score_replay([near_similar], moments).agreed_matched == 1
    assert score_replay([near_different], moments).agreed_matched == 0
    assert score_replay([far_similar], moments).agreed_matched == 0


def test_scoring_with_no_findings_or_no_notes_is_all_zero():
    assert score_replay([], []).to_dict()["items"] == 0
    assert score_replay([item("n1", 1, 2)], []).unmatched_items == 1


def test_improves_requires_more_agreed_and_no_more_broken_silence():
    base = ReplayScore(agreed_total=3, agreed_matched=1, disagreed_total=2, disagreed_hit=1)
    assert improves(base, ReplayScore(agreed_total=3, agreed_matched=2, disagreed_total=2, disagreed_hit=1))
    assert not improves(base, ReplayScore(agreed_total=3, agreed_matched=2, disagreed_total=2, disagreed_hit=2))
    assert not improves(base, ReplayScore(agreed_total=3, agreed_matched=1, disagreed_total=2, disagreed_hit=0))


def test_candidates_cover_the_plan_and_resolve_rejects_unknown_names():
    assert set(CANDIDATES) == {"floor-0.5", "min-turns-2", "ttl-120", "periodic-60", "soften-silence"}
    assert candidate_names()[-1] == "all"
    combined = resolve("all")
    assert combined.gate == {"min_new_turns": 2, "ttl_seconds": 120.0, "periodic_cooldown": 60.0}
    assert combined.periodic_floor == 0.5 and combined.softened_prompt is True
    with pytest.raises(ValueError):
        resolve("nope")


def test_gate_config_changes_only_what_the_candidate_names():
    default = gate_config_for(None)
    tuned = gate_config_for(resolve("min-turns-2"))
    assert default.min_new_turns == 3 and tuned.min_new_turns == 2
    assert tuned.ttl_seconds == default.ttl_seconds and tuned.periodic_cooldown == default.periodic_cooldown


def test_applied_overrides_then_restores_floor_and_prompt_even_on_error():
    shipped_floor = evaluator_module.DEFAULT_CONFIDENCE_FLOOR
    shipped_rules = prompts_module.RULES
    assert ORIGINAL_RULE_ONE in shipped_rules
    with applied(resolve("all")):
        assert evaluator_module.min_confidence_for("periodic") == 0.5
        assert evaluator_module.min_confidence_for("question") == 0.4
        assert ORIGINAL_RULE_ONE not in prompts_module.RULES and "Prefer silence over a weak note" in prompts_module.RULES
    assert evaluator_module.DEFAULT_CONFIDENCE_FLOOR == shipped_floor and prompts_module.RULES == shipped_rules
    with pytest.raises(RuntimeError):
        with applied(resolve("floor-0.5")):
            raise RuntimeError("boom")
    assert evaluator_module.DEFAULT_CONFIDENCE_FLOOR == shipped_floor


def test_softened_prompt_refuses_to_run_when_rule_one_has_changed(monkeypatch):
    monkeypatch.setattr(prompts_module, "RULES", prompts_module.RULES.replace(ORIGINAL_RULE_ONE, "1. Something else."))
    with pytest.raises(RuntimeError):
        with applied(resolve("soften-silence")):
            pass


async def stub_model(model_id):
    return SimpleNamespace(model_id=model_id)


def evaluator_with(caller):
    return CompanionEvaluator(model_loader=stub_model, schema_caller=caller, token_budget=lambda model: 1500)


@pytest.mark.asyncio
async def test_recorded_responses_make_a_floor_candidate_testable_without_a_model():
    recorded_items = [{"items": [{"kind": "suggestion", "text": "Confirm the pipeline review owner", "confidence": 0.55, "source_turn_ids": []}], "conversation_state": "", "considered": "Weighed it."}]
    recorded_items = recorded_items * 2
    baseline_evaluator = evaluator_with(RecordedCaller(recorded_items))
    baseline = await replay(turns(), evaluate=baseline_evaluator.evaluate)
    assert baseline.items == []
    with applied(resolve("floor-0.5")):
        candidate_evaluator = evaluator_with(RecordedCaller(recorded_items))
        candidate = await replay(turns(), evaluate=candidate_evaluator.evaluate)
    assert len(candidate.items) >= 1 and candidate.items[0].text == "Confirm the pipeline review owner"


@pytest.mark.asyncio
async def test_recorded_caller_runs_out_cleanly_and_rejects_non_list_files(tmp_path):
    caller = RecordedCaller([])
    outcome = await evaluator_with(caller).evaluate(
        SimpleNamespace(trigger="periodic", mode="active", meeting_time=1.0, new_turns=turns()[:3], window_turns=turns()[:3], conversation_state="", already_shown=[], pack=None, has_roots=False, watch=None, model_id=None, focus="")
    )
    assert outcome.error and "ran out" in outcome.error
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        RecordedCaller.load(path)


@pytest.mark.asyncio
async def test_recording_caller_saves_what_the_model_returned_and_it_replays(tmp_path):
    parsed = CompanionEvaluationResponse(items=[], conversation_state="State", considered="Quiet.")

    async def inner(model, *, prompt, response_model, max_tokens):
        return SimpleNamespace(value=parsed, finish_reason=None)

    recorder = RecordingCaller(inner)
    await recorder(None, prompt="p", response_model=CompanionEvaluationResponse, max_tokens=10)
    path = tmp_path / "recording.json"
    recorder.save(path)
    again = await RecordedCaller.load(path)(None, prompt="p", response_model=CompanionEvaluationResponse, max_tokens=10)
    assert again.value.conversation_state == "State" and again.value.considered == "Quiet."


@pytest.mark.asyncio
async def test_comparison_table_marks_a_candidate_apply_only_when_the_rule_is_met():
    report = await replay(turns())
    baseline = row_for("baseline", report, ReplayScore(agreed_total=2, agreed_matched=0, disagreed_total=1, disagreed_hit=0, items=0))
    better = ComparisonRow("floor-0.5", 3, ReplayScore(agreed_total=2, agreed_matched=1, disagreed_total=1, disagreed_hit=0, items=2))
    noisier = ComparisonRow("ttl-120", 3, ReplayScore(agreed_total=2, agreed_matched=2, disagreed_total=1, disagreed_hit=1, items=4))
    table = format_comparison([baseline, better, noisier])
    lines = {line.split()[0]: line for line in table.splitlines()[1:]}
    assert "baseline" in lines["baseline"] and "APPLY" in lines["floor-0.5"] and "do not apply" in lines["ttl-120"]


def test_comparison_explains_when_there_is_nothing_to_judge_against():
    empty = ComparisonRow("baseline", 2, ReplayScore())
    assert "No finding in this meeting is marked Good catch" in format_comparison([empty, ComparisonRow("floor-0.5", 2, ReplayScore())])
    assert format_comparison([]) == "nothing to compare"


def test_marked_moments_come_from_the_saved_audit_and_are_empty_without_one():
    assert load_marked_moments(None) == []
    assert load_marked_moments(SimpleNamespace(audit=None)) == []
    assert [entry.id for entry in load_marked_moments(SimpleNamespace(audit=SimpleNamespace(moments=[moment("a1", 1, 2, "agree")])))] == ["a1"]
