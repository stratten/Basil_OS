"""Meeting detail returns analyses without the whole transcript, and pages the transcript."""

import json

import pytest
from pydantic import ValidationError

from api.services.agent_processing.tools.internal_basil_tools.retrieval_tool import RetrievalToolInput
from api.services.retrieval.contracts import RetrievalDetailRequest
from api.services.retrieval.detail_shaping import shape_detail


def _analysis(index: int, size: int = 50) -> dict:
    return {
        "meeting_id": "m1",
        "timestamp": f"2026-10-0{index + 1}T10:00:00Z",
        "filename": f"analysis_{index}.json",
        "modes": ["summary"],
        "model_used": "test-model",
        "content": {"summary": f"summary {index} " + "x" * size},
    }


def _detail(transcript: str, analyses: list) -> dict:
    return {
        "source_kind": "meeting",
        "source_id": "m1",
        "document": {"title": "Weekly"},
        "context": {
            "meeting_name": "Weekly",
            "purpose": "sync",
            "participants": ["a"],
            "start_time": "2026-10-01T10:00:00Z",
            "end_time": None,
            "duration_seconds": 60,
            "member_count": 1,
            "is_post_processed": True,
            "transcript": transcript,
            "analysis_count": len(analyses),
            "analyses": analyses,
            "latest_analysis": analyses[-1]["content"] if analyses else None,
        },
        "detail_available": True,
    }


def _request(**overrides) -> RetrievalDetailRequest:
    return RetrievalDetailRequest(source_kind="meeting", source_id="m1", **overrides)


def test_analyses_only_omits_transcript_and_metadata_and_duplicate_latest():
    detail = _detail("line\n" * 100000, [_analysis(0), _analysis(1)])
    shaped = shape_detail(detail, _request(sections=("analyses",)))["context"]
    assert "transcript" not in shaped
    assert "latest_analysis" not in shaped
    assert "meeting_name" not in shaped
    assert shaped["transcript_total_chars"] == 500000
    assert [item["index"] for item in shaped["analyses"]] == [1]
    assert [entry["index"] for entry in shaped["analysis_catalog"]] == [0, 1]
    assert len(json.dumps(shaped)) < 5000


def test_analysis_index_selects_older_and_negative_counts_from_end():
    detail = _detail("", [_analysis(0), _analysis(1), _analysis(2)])
    first = shape_detail(detail, _request(sections=("analyses",), analysis_index=0))["context"]
    assert first["analyses"][0]["filename"] == "analysis_0.json"
    second_last = shape_detail(detail, _request(sections=("analyses",), analysis_index=-2))["context"]
    assert second_last["analyses"][0]["filename"] == "analysis_1.json"


def test_out_of_range_analysis_index_explains_valid_range():
    detail = _detail("", [_analysis(0)])
    shaped = shape_detail(detail, _request(sections=("analyses",), analysis_index=5))["context"]
    assert shaped["analyses"] == []
    assert "out of range" in shaped["analysis_error"]


def test_meeting_without_analyses_returns_empty_list_and_catalog():
    shaped = shape_detail(_detail("hello", []), _request())["context"]
    assert shaped["analyses"] == []
    assert shaped["analysis_catalog"] == []
    assert shaped["transcript"] == "hello"
    assert shaped["transcript_range"]["truncated"] is False
    assert shaped["transcript_range"]["next_offset"] is None


def test_default_transcript_page_is_bounded_and_links_to_next_page():
    transcript = "".join(f"[{i}.0s] Speaker: sentence {i}\n" for i in range(5000))
    shaped = shape_detail(_detail(transcript, [_analysis(0)]), _request())["context"]
    page = shaped["transcript_range"]
    assert page["total_chars"] == len(transcript)
    assert page["truncated"] is True
    assert page["returned_chars"] <= 20000
    assert shaped["transcript"].endswith("\n")
    assert page["next_offset"] == page["returned_chars"]
    assert "transcript_offset=" in shaped["transcript_hint"]


def test_paging_reassembles_exact_transcript():
    transcript = "".join(f"[{i}.0s] Speaker: sentence {i}\n" for i in range(3000))
    collected = ""
    offset = 0
    for _ in range(100):
        shaped = shape_detail(
            _detail(transcript, []),
            _request(sections=("transcript",), transcript_offset=offset, transcript_limit=7000),
        )["context"]
        collected += shaped["transcript"]
        offset = shaped["transcript_range"]["next_offset"]
        if offset is None:
            break
    assert collected == transcript


def test_single_line_longer_than_limit_still_makes_progress():
    transcript = "x" * 50000
    shaped = shape_detail(_detail(transcript, []), _request(sections=("transcript",), transcript_limit=1000))["context"]
    assert shaped["transcript_range"]["returned_chars"] == 1000
    assert shaped["transcript_range"]["next_offset"] == 1000


def test_offset_past_end_returns_empty_not_error():
    shaped = shape_detail(_detail("short", []), _request(sections=("transcript",), transcript_offset=999))["context"]
    assert shaped["transcript"] == ""
    assert shaped["transcript_range"]["next_offset"] is None


def test_non_meeting_detail_is_returned_unchanged():
    detail = {"source_kind": "agent_task", "source_id": "t1", "context": {"result": "ok"}}
    assert shape_detail(detail, _request()) is detail
    assert shape_detail(None, _request()) is None


def test_tool_input_rejects_unknown_section_and_bad_limits():
    with pytest.raises(ValidationError):
        RetrievalToolInput(action="detail", source_kind="meeting", source_id="m1", sections=["audio"])
    with pytest.raises(ValidationError):
        RetrievalToolInput(action="detail", source_kind="meeting", source_id="m1", transcript_limit=0)
    with pytest.raises(ValidationError):
        RetrievalToolInput(action="detail", source_kind="meeting", source_id="m1", transcript_offset=-1)
