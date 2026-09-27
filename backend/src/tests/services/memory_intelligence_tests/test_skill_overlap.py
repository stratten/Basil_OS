"""Unit tests for the deterministic skill-overlap detector.

These tests use no model and no filesystem; they verify ranking, source-task
overlap, body-key selection, and the backstop predicate (including the negative
case where genuinely distinct material must not be flagged as overlapping).
"""

from api.services.skills import skill_overlap
from api.services.skills.skill_overlap import RankableItem


def test_text_similarity_identical_and_disjoint() -> None:
    assert skill_overlap.text_similarity("convert pdf markdown", "convert pdf markdown") == 1.0
    assert skill_overlap.text_similarity("convert pdf markdown", "schedule calendar invite") == 0.0


def test_source_task_overlap_iou() -> None:
    assert skill_overlap.source_task_overlap(["t1", "t2"], ["t2", "t3"]) == 1 / 3
    assert skill_overlap.source_task_overlap(["t1"], ["t1"]) == 1.0
    assert skill_overlap.source_task_overlap([], ["t1"]) == 0.0
    assert skill_overlap.source_task_overlap(["t1"], ["t9"]) == 0.0


def test_select_body_keys_only_related_and_respects_top_k() -> None:
    items = [
        RankableItem(key="pdf", text="Convert PDF documents to clean Markdown output"),
        RankableItem(key="invoice", text="Convert PDF invoices into Markdown summaries"),
        RankableItem(key="calendar", text="Schedule recurring calendar meetings with attendees"),
    ]
    keys = skill_overlap.select_body_keys("convert this pdf into markdown", items, top_k=6)
    assert "pdf" in keys
    assert "invoice" in keys
    # Unrelated item has zero similarity and must never be selected, even with
    # spare top_k budget.
    assert "calendar" not in keys


def test_select_body_keys_caps_to_top_k() -> None:
    items = [
        RankableItem(key=f"pdf-{index}", text="convert pdf markdown document")
        for index in range(10)
    ]
    keys = skill_overlap.select_body_keys("convert pdf markdown", items, top_k=3)
    assert len(keys) == 3


def test_proposal_overlaps_candidate_true_on_text() -> None:
    text = "convert pdf markdown tables margins headings layout structure"
    assert skill_overlap.proposal_overlaps_candidate(
        proposal_text=text,
        proposal_source_task_ids=["new-task"],
        candidate_text=text,
        candidate_source_task_ids=["old-task"],
    )


def test_proposal_overlaps_candidate_true_on_source_only() -> None:
    # Text is unrelated, but a shared source task forces the overlap flag.
    assert skill_overlap.proposal_overlaps_candidate(
        proposal_text="schedule calendar meeting",
        proposal_source_task_ids=["shared-task"],
        candidate_text="convert pdf markdown",
        candidate_source_task_ids=["shared-task"],
    )


def test_proposal_overlaps_candidate_false_when_distinct() -> None:
    assert not skill_overlap.proposal_overlaps_candidate(
        proposal_text="schedule a recurring calendar meeting with attendees",
        proposal_source_task_ids=["task-a"],
        candidate_text="convert pdf documents into clean markdown",
        candidate_source_task_ids=["task-b"],
    )
