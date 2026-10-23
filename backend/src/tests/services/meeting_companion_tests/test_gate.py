from api.services.meeting_companion.gate import (
    ALL_TRIGGERS,
    DEFERRED_TRIGGERS,
    Gate,
    GateDecision,
    keywords_from_topic,
    light_stem,
    watch_matches,
)
from api.services.meeting_companion.models import CompanionTurn, CompanionWatch


def make_turn(index, text, start, role="other"):
    return CompanionTurn(id=f"t-{index:05d}", source_meeting_id="m", role=role, speaker="Zoom", start=start, end=start + 3, text=text)


def decide(gate, now, mode="active", watches=(), allowed=ALL_TRIGGERS):
    return gate.decide(now, mode=mode, watches=list(watches), allowed=allowed)


def make_watch(keywords=("billing", "invoice")):
    return CompanionWatch(id="w1", topic="billing", instruction="Summarize", keywords=list(keywords), created_at=0.0)


def test_light_stem_and_watch_matches():
    assert light_stem("billing") == light_stem("bills") == light_stem("billed") == "bill"
    assert light_stem("invoice") == light_stem("invoices") == "invoic"
    assert watch_matches(make_watch(), [make_turn(1, "the billing run failed twice last week", 0)])
    assert not watch_matches(make_watch(), [make_turn(1, "we should talk about hiring plans", 0)])
    assert not watch_matches(make_watch(keywords=()), [make_turn(1, "billing invoice", 0)])


def test_keywords_from_topic_drops_stopwords_and_caps_length():
    assert keywords_from_topic("the billing invoice run") == ["billing", "invoice", "run"]
    assert keywords_from_topic("") == []
    assert len(keywords_from_topic("alpha beta gamma delta epsilon zeta theta iota kappa")) == 6


def test_backchannel_never_fires_and_empty_gate_is_idle():
    gate = Gate()
    assert decide(gate, 1).reason == "idle"
    gate.add_turn(make_turn(1, "yeah okay right", 0), 1)
    assert decide(gate, 2).reason == "backchannel"


def test_question_fires_on_one_line_then_cooldown_and_pacing():
    gate = Gate()
    gate.add_turn(make_turn(1, "How does the retry policy handle timeouts in billing", 0), 100)
    first = decide(gate, 100)
    assert first.fire and first.trigger == "question" and len(first.new_turns) == 1
    gate.commit(first, 100)
    gate.add_turn(make_turn(2, "What happens when the invoice generation fails again", 3), 102)
    assert decide(gate, 102).reason == "pacing"
    assert decide(gate, 106).reason == "few lines"
    assert decide(gate, 111).trigger == "question"


def test_periodic_needs_three_substantive_lines_and_first_delay():
    gate = Gate()
    for index, arrival in enumerate((10, 20, 50), start=1):
        gate.add_turn(make_turn(index, "We should review the deployment pipeline for the billing service today", arrival), arrival)
    assert decide(gate, 50).reason == "waiting"
    fired = decide(gate, 56)
    assert fired.fire and fired.trigger == "periodic" and len(fired.new_turns) == 3


def test_two_substantive_lines_do_not_fire_periodic():
    gate = Gate()
    gate.add_turn(make_turn(1, "We should review the deployment pipeline today", 0), 0)
    gate.add_turn(make_turn(2, "The billing service needs another look soon", 3), 3)
    assert decide(gate, 30).reason == "few lines"


def test_topic_shift_after_baseline():
    gate = Gate()
    billing = [
        "the billing service generates invoices for every customer nightly",
        "invoices are emailed after the billing run completes successfully",
        "customers receive the invoice emails after billing completes",
        "the billing run failed twice last week for enterprise customers",
    ]
    for index, (text, arrival) in enumerate(zip(billing, (0, 10, 20, 30)), start=1):
        gate.add_turn(make_turn(index, text, arrival), arrival)
    periodic = decide(gate, 50)
    assert periodic.trigger == "periodic"
    gate.commit(periodic, 50)
    shift = [
        "kubernetes cluster autoscaling needs more memory limits",
        "the deployment manifests require updated resource requests",
        "autoscaler thresholds should trigger earlier under heavy traffic",
    ]
    for index, (text, arrival) in enumerate(zip(shift, (60, 62, 64)), start=10):
        gate.add_turn(make_turn(index, text, arrival), arrival)
    decision = decide(gate, 66)
    assert decision.fire and decision.trigger == "topic_shift"


def test_watch_fires_with_one_line_and_respects_cooldown():
    gate = Gate()
    watch = make_watch()
    gate.add_turn(make_turn(1, "the billing run failed twice last week", 0), 100)
    decision = decide(gate, 100, watches=[watch])
    assert decision.fire and decision.trigger == "watch" and decision.watch is watch
    gate.commit(decision, 100)
    gate.add_turn(make_turn(2, "the billing run failed again this morning", 60), 160)
    assert decide(gate, 160, watches=[watch]).fire is False
    gate.add_turn(make_turn(3, "billing is failing once more for customers", 230), 230)
    assert decide(gate, 230, watches=[watch]).trigger == "watch"


def test_inactive_watch_never_fires():
    gate = Gate()
    watch = make_watch().model_copy(update={"active": False})
    gate.add_turn(make_turn(1, "the billing run failed twice last week", 0), 0)
    assert decide(gate, 1, watches=[watch]).fire is False


def test_passive_mode_answers_questions_but_not_statements():
    gate = Gate()
    for index in range(1, 5):
        gate.add_turn(make_turn(index, "We should review the deployment pipeline for the billing service today", index), index)
    assert decide(gate, 30, mode="passive").reason == "passive"
    gate.add_turn(make_turn(9, "How does the retry policy handle timeouts in billing", 30), 30)
    assert decide(gate, 30, mode="passive").trigger == "question"


def test_capacity_restricts_triggers():
    gate = Gate()
    for index in range(1, 5):
        gate.add_turn(make_turn(index, "We should review the deployment pipeline for the billing service today", index), index)
    restricted = decide(gate, 50, allowed=DEFERRED_TRIGGERS)
    assert restricted.fire is False and restricted.reason == "waiting"
    assert decide(gate, 50, allowed=frozenset()).reason == "capacity"
    gate.add_turn(make_turn(9, "How does the retry policy handle timeouts in billing", 50), 50)
    assert decide(gate, 50, allowed=DEFERRED_TRIGGERS).trigger == "question"
    assert decide(gate, 50, allowed=frozenset()).fire is False


def test_ttl_moves_stale_lines_to_history_without_firing():
    gate = Gate()
    for index in range(1, 4):
        gate.add_turn(make_turn(index, "We should review the deployment pipeline for the billing service today", index), index)
    assert decide(gate, 200).reason == "idle"
    assert gate.pending_count() == 0
    assert len(gate.window()) == 3


def test_window_is_time_bounded_ordered_and_capped():
    gate = Gate()
    gate.add_turn(make_turn(1, "very old line about something else entirely here", 0), 0)
    gate.add_turn(make_turn(2, "recent line about the billing service today", 200), 200)
    gate.add_turn(make_turn(3, "another recent line about billing runs", 205), 205)
    assert [turn.id for turn in gate.window(window_seconds=90)] == ["t-00002", "t-00003"]
    assert [turn.id for turn in gate.window(window_seconds=1000, max_turns=2)] == ["t-00002", "t-00003"]


def test_seeded_history_is_context_only_and_never_fires():
    gate = Gate()
    gate.seed_history(make_turn(1, "How does the retry policy handle timeouts in billing", 0))
    assert gate.pending_count() == 0 and decide(gate, 5).reason == "idle"
    assert [turn.id for turn in gate.window()] == ["t-00001"]


def test_commit_resets_pending_and_unknown_decision_is_safe():
    gate = Gate()
    gate.add_turn(make_turn(1, "How does the retry policy handle timeouts in billing", 0), 0)
    gate.commit(GateDecision(fire=True, trigger=None), 0)
    assert gate.pending_count() == 0
