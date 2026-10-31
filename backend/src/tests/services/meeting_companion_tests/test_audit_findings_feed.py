"""Audit findings join the normal Companion feed at the point in the meeting where each miss happened."""

from api.services.meeting_companion.audit import AUDIT_ITEM_TRIGGER, findings_as_items
from api.services.meeting_companion.models import AuditMoment, AuditReport, CompanionItem, CompanionTurn, TranscriptRange


def turn(turn_id: str, start: float, end: float) -> CompanionTurn:
    return CompanionTurn(id=turn_id, source_meeting_id="m1", role="other", speaker="Speaker 1", start=start, end=end, text="words")


def moment(moment_id: str, kind: str, start: float, end: float, text: str, confidence: float = 0.7, why: str = "A follow-up was missed.") -> AuditMoment:
    return AuditMoment(id=moment_id, start=start, end=end, kind=kind, why=why, suggested_text=text, confidence=confidence)  # type: ignore[arg-type]


def report(*moments: AuditMoment) -> AuditReport:
    return AuditReport(audit_id="au-1", scope="meeting", moments=list(moments))


def shown(item_id: str, text: str, dismissed: bool = False) -> CompanionItem:
    return CompanionItem(
        id=item_id,
        kind="suggestion",
        text=text,
        confidence=0.8,
        transcript_range=TranscriptRange(start=1.0, end=2.0),
        trigger="topic_shift",
        dismissed=dismissed,
    )


def sequential_ids():
    counter = iter(range(1, 100))
    return lambda: f"it-{next(counter)}"


TURNS = [turn("t1", 0.0, 10.0), turn("t2", 10.0, 20.0), turn("t3", 20.0, 30.0)]


def test_each_finding_becomes_an_item_at_its_own_transcript_range():
    audit = report(
        moment("a", "todo", 12.0, 18.0, "Set up a follow-up with Ben about implementing the pricing spreadsheet."),
        moment("b", "note", 21.0, 25.0, "Margin applies as price equals cost divided by one minus margin."),
    )

    items = findings_as_items(audit, TURNS, [], id_factory=sequential_ids())

    assert [(item.id, item.kind, item.trigger) for item in items] == [("it-1", "suggestion", AUDIT_ITEM_TRIGGER), ("it-2", "insight", AUDIT_ITEM_TRIGGER)]
    assert (items[0].transcript_range.start, items[0].transcript_range.end, items[0].transcript_range.turn_ids) == (12.0, 18.0, ["t2"])
    assert items[1].transcript_range.turn_ids == ["t3"]
    assert items[0].rationale == "A follow-up was missed." and items[0].confidence == 0.7
    assert items[0].dismissed is False and items[0].pinned is False


def test_every_non_note_kind_becomes_a_suggestion_the_feed_can_act_on():
    audit = report(
        moment("a", "todo", 1.0, 2.0, "Draft the weekend pricing spreadsheet and send it for feedback."),
        moment("b", "agent_task", 3.0, 4.0, "Compile the catalog naming conventions into one reference document."),
        moment("c", "research", 5.0, 6.0, "Find the earlier decision about who owns naming for each category."),
    )

    kinds = [item.kind for item in findings_as_items(audit, TURNS, [], id_factory=sequential_ids())]

    assert kinds == ["suggestion", "suggestion", "suggestion"]


def test_a_finding_already_covered_by_a_shown_or_dismissed_item_is_not_added_again():
    audit = report(
        moment("a", "todo", 12.0, 18.0, "Set up a follow-up with Ben about implementing the pricing spreadsheet."),
        moment("b", "todo", 21.0, 25.0, "Ask Wayne who owns the naming convention for each catalog category."),
    )
    existing = [
        shown("x1", "Set up a follow-up with Ben about implementing the pricing spreadsheet."),
        shown("x2", "Ask Wayne who owns the naming convention for each catalog category.", dismissed=True),
    ]

    assert findings_as_items(audit, TURNS, existing, id_factory=sequential_ids()) == []


def test_two_similar_findings_in_one_report_produce_one_item():
    audit = report(
        moment("a", "todo", 12.0, 18.0, "Set up a follow-up with Ben about implementing the pricing spreadsheet."),
        moment("b", "todo", 40.0, 44.0, "Set up a follow-up with Ben about implementing the pricing spreadsheet."),
    )

    assert len(findings_as_items(audit, TURNS, [], id_factory=sequential_ids())) == 1


def test_an_empty_report_and_a_finding_with_no_overlapping_turns_are_handled():
    assert findings_as_items(report(), TURNS, [], id_factory=sequential_ids()) == []
    items = findings_as_items(report(moment("a", "note", 500.0, 510.0, "A fact about quoting tools.")), TURNS, [], id_factory=sequential_ids())
    assert len(items) == 1 and items[0].transcript_range.turn_ids == []
