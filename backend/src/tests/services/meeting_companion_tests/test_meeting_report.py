import json

from api.services.meeting_companion.meeting_report import format_table, percentile, summarize_meeting
from api.services.meeting_companion.models import CompanionItem, TimelineEvent, TranscriptRange
from api.services.meeting_companion.run_fingerprint import build_run_payload, prompt_hash
from api.services.meeting_companion.gate import GateConfig
from api.services.meeting_companion.models import CompanionSettings


def event(seq, kind, payload, meeting_time=0.0):
    return TimelineEvent(id=f"e{seq}", seq=seq, kind=kind, meeting_time=meeting_time, wall_time="2026-10-21T10:00:00Z", payload=payload)


def note(item_id, end):
    item = CompanionItem(id=item_id, kind="suggestion", text="A note", confidence=0.9, transcript_range=TranscriptRange(start=end - 5, end=end), trigger="periodic")
    return event(int(end), "item", {"item": item.model_dump(mode="json")}, end)


def evaluation(seq, kept, latency, outcomes=(), error=None, waits=None):
    candidates = [{"kind": "suggestion", "text": "x", "confidence": 0.5, "outcome": outcome} for outcome in outcomes]
    return event(seq, "evaluation", {"trigger": "periodic", "new_lines": 3, "considered": "", "candidates": candidates, "kept": kept, "latency_ms": latency, "finish_reason": "stop", "model_id": "m", "error": error, "gate_waits": waits or {}, "discarded": None})


def test_percentile_uses_nearest_rank_and_handles_empty():
    assert percentile([], 0.5) is None
    assert percentile([100, 200, 300, 400], 0.5) == 200
    assert percentile([100, 200, 300, 400], 0.95) == 400
    assert percentile([700], 0.95) == 700


def test_a_meeting_is_summarized_from_its_events():
    events = [
        event(1, "run", {"model_id": "m", "prompt_hash": "abc123def456"}),
        note("n1", 1800.0),
        note("n2", 3600.0),
        evaluation(10, 1, 900, outcomes=["kept", "confidence_floor"], waits={"cooldown": 4}),
        evaluation(11, 0, 1500, outcomes=["confidence_floor"], waits={"cooldown": 2, "few_turns": 1}),
        evaluation(12, 0, 0, error="timeout"),
        event(13, "feedback", {"item_id": "n1", "action": "dismissed"}),
        event(14, "feedback", {"item_id": "n2", "action": "useful"}),
        event(15, "feedback", {"item_id": "m1", "action": "audit_agree"}),
        event(16, "error", {"code": "audit_failed", "message": "x"}),
        event(17, "investigation", {"status": "not_found", "shown": False, "reason": "no_answer_automatic"}),
        event(18, "investigation", {"status": "completed", "shown": True, "reason": ""}),
    ]
    row = summarize_meeting("m-1", events, "2026-10-21T11:00:00Z")
    assert row["duration_seconds"] == 3600 and row["notes"] == 2 and row["notes_per_hour"] == 2.0
    assert row["run"]["prompt_hash"] == "abc123def456" and row["sessions"] == 1
    evaluations = row["evaluations"]
    assert evaluations["logged"] == 3 and evaluations["silent"] == 1 and evaluations["errors"] == 1
    assert evaluations["candidate_outcomes"] == {"kept": 1, "confidence_floor": 2}
    assert evaluations["gate_waits"] == {"cooldown": 6, "few_turns": 1}
    assert evaluations["latency_p50_ms"] == 900 and evaluations["latency_p95_ms"] == 1500
    assert row["feedback"] == {"dismissed": 1, "useful": 1} and row["errors"] == {"audit_failed": 1}
    assert row["investigations"] == {"total": 2, "shown": 1, "statuses": {"not_found": 1, "completed": 1}, "withheld_reasons": {"no_answer_automatic": 1}}
    assert row["audit"] is None
    json.dumps(row)


def test_an_empty_or_very_short_meeting_does_not_divide_by_zero():
    row = summarize_meeting("m-2", [event(1, "run", {})])
    assert row["notes_per_hour"] is None and row["evaluations"]["latency_p50_ms"] is None and row["duration_seconds"] == 0


def test_the_table_lists_every_meeting_and_survives_missing_data():
    rows = [summarize_meeting("m-1", [note("n1", 600.0)]), summarize_meeting("m-2", [])]
    table = format_table(rows)
    assert "m-1" in table and "m-2" in table and "prompt" in table and "silent = " in table


def test_the_run_fingerprint_is_stable_and_captures_the_tuning_knobs():
    payload = build_run_payload(CompanionSettings(), GateConfig())
    assert payload["prompt_hash"] == prompt_hash() == build_run_payload(CompanionSettings(), GateConfig())["prompt_hash"]
    assert payload["gate"]["min_new_turns"] == GateConfig().min_new_turns and payload["has_focus"] is False
    focused = build_run_payload(CompanionSettings(focus="pricing"), GateConfig(min_new_turns=2))
    assert focused["has_focus"] is True and focused["gate"]["min_new_turns"] == 2 and "pricing" not in json.dumps(focused)
