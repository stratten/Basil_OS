import pytest

from api.services.meeting_companion.evaluator import EvaluationOutcome
from api.services.meeting_companion.models import CompanionItem, CompanionTurn, CompanionWatch, TranscriptRange
from api.services.meeting_companion.replay import format_report, replay, segments_to_turns

STATEMENT = "We should review the deployment pipeline for the billing service today"
QUESTION = "How does the retry policy handle timeouts in billing"


def synthetic_turns():
    return [
        CompanionTurn(
            id=f"t-{index + 1:05d}",
            source_meeting_id="m",
            role="other",
            speaker="Zoom",
            start=index * 10.0,
            end=index * 10.0 + 3.0,
            text=QUESTION if index == 6 else STATEMENT,
        )
        for index in range(12)
    ]


def test_segments_to_turns_assembles_fragments_per_speaker_and_skips_interim_and_blank():
    segments = [
        {"start": 0.0, "end": 0.6, "text": " hello", "speaker": "Microphone"},
        {"start": 0.6, "end": 1.5, "text": " everyone today.", "speaker": "Microphone"},
        {"start": 2.0, "end": 3.0, "text": " thanks all", "speaker": "Zoom"},
        {"start": 3.0, "end": 4.0, "text": " for coming?", "speaker": "Zoom"},
        {"start": 9.0, "end": 10.0, "text": "junk", "speaker": "Zoom", "is_interim": True},
        {"start": 11.0, "end": 12.0, "text": "   ", "speaker": "Zoom"},
    ]
    turns = segments_to_turns(segments)
    assert [turn.text for turn in turns] == ["hello everyone today.", "thanks all for coming?"]
    assert [turn.role for turn in turns] == ["self", "other"]
    assert [turn.id for turn in turns] == ["r-1-00001", "r-2-00001"]


def test_segments_to_turns_handles_empty_input():
    assert segments_to_turns([]) == []


@pytest.mark.asyncio
async def test_dry_run_reports_when_the_gate_would_fire():
    report = await replay(synthetic_turns())
    assert report.turn_count == 12
    assert [(step.trigger, step.time) for step in report.steps] == [("periodic", 48.0), ("question", 63.0)]
    assert report.trigger_counts == {"periodic": 1, "question": 1}
    assert report.items == [] and report.error_count == 0
    assert "evaluations: 2" in format_report(report) and "01:03 question" in format_report(report)


@pytest.mark.asyncio
async def test_passive_mode_only_answers_the_question():
    report = await replay(synthetic_turns(), mode="passive")
    assert [step.trigger for step in report.steps] == ["question"]


@pytest.mark.asyncio
async def test_watch_fires_during_replay():
    watch = CompanionWatch(id="w1", topic="retry", instruction="Summarize retries", keywords=["retry"], created_at=0.0)
    report = await replay(synthetic_turns(), mode="passive", watches=[watch])
    assert report.steps[0].trigger == "watch" and report.steps[0].time == 63.0


@pytest.mark.asyncio
async def test_evaluator_receives_state_and_already_shown_and_items_are_collected():
    requests = []

    async def evaluate(request):
        requests.append(request)
        number = len(requests)
        item = CompanionItem(
            id=f"it-{number}",
            kind="insight",
            text=f"Note number {number}",
            confidence=0.9,
            transcript_range=TranscriptRange(start=0.0, end=1.0),
            trigger=request.trigger,
        )
        return EvaluationOutcome(items=[item], conversation_state=f"State {number}", latency_ms=120)

    async def lookup(text):
        return None

    report = await replay(synthetic_turns(), evaluate=evaluate, context_lookup=lookup)
    assert len(requests) == 2
    assert requests[0].conversation_state == "" and requests[0].already_shown == [] and requests[0].has_roots is True
    assert requests[1].conversation_state == "State 1" and requests[1].already_shown == ["Note number 1"]
    assert [item.id for item in report.items] == ["it-1", "it-2"]
    assert report.steps[0].item_count == 1 and report.steps[0].latency_ms == 120
    assert "latency=120ms" in format_report(report)


@pytest.mark.asyncio
async def test_evaluator_errors_are_recorded_not_raised():
    async def evaluate(request):
        return EvaluationOutcome(error="timeout", latency_ms=60000)

    report = await replay(synthetic_turns(), evaluate=evaluate)
    assert report.error_count == 2 and "ERROR=timeout" in format_report(report)


@pytest.mark.asyncio
async def test_empty_transcript_and_report_serialization():
    empty = await replay([])
    assert empty.steps == [] and empty.to_dict()["trigger_counts"] == {}
    report = await replay(synthetic_turns())
    payload = report.to_dict()
    assert payload["trigger_counts"] == {"periodic": 1, "question": 1} and len(payload["steps"]) == 2
