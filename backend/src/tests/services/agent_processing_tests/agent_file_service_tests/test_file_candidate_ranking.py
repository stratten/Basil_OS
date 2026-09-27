"""Unit tests for pure file-candidate ranking (no I/O)."""

from __future__ import annotations

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_candidate_ranking import (
    partition_candidates,
    rank_candidates,
    score_candidate,
)


def _candidate(name, *, size=50_000, modified=1000.0, extension=None):
    ext = extension if extension is not None else "." + name.rsplit(".", 1)[-1]
    return {
        "name": name,
        "path": f"/drive/{name}",
        "size": size,
        "modified_date": modified,
        "extension": ext,
    }


def test_pointer_stub_deranked_below_real_pdf_even_when_newer():
    query = "PayLink User Guide"
    stub = _candidate("PayLink User Guide.gdoc", size=150, modified=2000.0)
    pdf = _candidate("PayLink User Guide.pdf", size=80_000, modified=1000.0)

    ranked = rank_candidates([stub, pdf], query)

    assert ranked[0]["name"].endswith(".pdf")
    assert score_candidate(pdf, query) > score_candidate(stub, query)


def test_higher_name_overlap_wins():
    query = "quarterly revenue report"
    strong = _candidate("quarterly revenue report.pdf")
    weak = _candidate("revenue.pdf")

    ranked = rank_candidates([weak, strong], query)

    assert ranked[0]["name"] == "quarterly revenue report.pdf"


def test_recency_breaks_score_ties():
    query = "report"
    older = _candidate("report.pdf", modified=1000.0)
    newer = dict(_candidate("report.pdf", modified=5000.0), path="/drive/newer/report.pdf")

    ranked = rank_candidates([older, newer], query)

    assert ranked[0]["modified_date"] == 5000.0


def test_partition_single_candidate_is_confident():
    query = "PayLink User Guide"
    ranked = rank_candidates([_candidate("PayLink User Guide.pdf")], query)

    confident, all_candidates = partition_candidates(ranked)

    assert confident is not None
    assert len(all_candidates) == 1


def test_partition_close_scores_are_ambiguous():
    query = "PayLink Guide"
    ranked = rank_candidates(
        [
            _candidate("PayLink Guide v1.pdf"),
            _candidate("PayLink Guide v2.pdf"),
            _candidate("PayLink Guide Bankwest.pdf"),
        ],
        query,
    )

    confident, all_candidates = partition_candidates(ranked)

    assert confident is None
    assert len(all_candidates) == 3


def test_partition_dominant_top_is_confident():
    query = "PayLink Installation Guide"
    ranked = rank_candidates(
        [
            _candidate("PayLink Installation Guide.pdf"),
            _candidate("unrelated notes.gdoc", size=120),
        ],
        query,
    )

    confident, _ = partition_candidates(ranked)

    assert confident is not None
    assert confident["name"] == "PayLink Installation Guide.pdf"
