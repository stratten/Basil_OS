"""Tests for GET /meetings/search (grouped + paginated, route ordering)."""

import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.routes.meetings import router as meetings_router
from api.routes.meetings import search_routes
from api.routes.meetings import meeting_grouping
from api.routes.meetings.analysis_summary import MeetingAnalysisSummary


def _raw(
    meeting_id: str,
    name: str,
    start_time: str,
    *,
    session_id: Optional[str] = None,
    audio_source: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": meeting_id,
        "name": name,
        "purpose": None,
        "participants": [],
        "start_time": start_time,
        "end_time": None,
        "duration_seconds": 0.0,
        "audio_path": None,
        "transcript_path": None,
        "is_post_processed": False,
        "session_id": session_id,
        "audio_source": audio_source,
        "timeline_offset_seconds": 0.0,
        "recording_part_index": 0,
    }


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(meetings_router)
    return TestClient(app)


def _patch(monkeypatch, raw_meetings: List[Dict[str, Any]], matched_ids: List[str]):
    monkeypatch.setattr(search_routes, "load_all_raw_meetings", lambda: raw_meetings)

    fake_repo = types.SimpleNamespace(
        search_meeting_ids=lambda **_kwargs: list(matched_ids)
    )
    fake_service = types.SimpleNamespace(meeting_transcript_search_repository=fake_repo)
    monkeypatch.setattr(search_routes, "get_sqlite_knowledge_service", lambda: fake_service)


def test_system_audio_member_match_returns_representative(monkeypatch):
    raw_meetings = [
        _raw("mic1", "Standup - Microphone", "2026-01-01T10:00:01Z",
             session_id="S", audio_source="Microphone"),
        _raw("sys1", "Standup - System Audio", "2026-01-01T10:00:00Z",
             session_id="S", audio_source="System Audio"),
    ]
    # The spoken word was only on the system-audio side.
    _patch(monkeypatch, raw_meetings, matched_ids=["sys1"])

    resp = _client().get("/meetings/search", params={"query": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "mic1", "match on a member surfaces the grouped representative"


def test_no_match_returns_empty(monkeypatch):
    _patch(monkeypatch, [_raw("a", "Thing", "2026-01-01T10:00:00Z")], matched_ids=[])
    resp = _client().get("/meetings/search", params={"query": "absent"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_pagination_of_grouped_results(monkeypatch):
    raw_meetings = [
        _raw("a", "A", "2026-01-03T10:00:00Z"),
        _raw("b", "B", "2026-01-02T10:00:00Z"),
        _raw("c", "C", "2026-01-01T10:00:00Z"),
    ]
    _patch(monkeypatch, raw_meetings, matched_ids=["a", "b", "c"])

    # Sorted newest-first (a, b, c); limit=1 offset=1 -> the middle one.
    resp = _client().get("/meetings/search", params={"query": "x", "limit": 1, "offset": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body] == ["b"]


def test_empty_query_returns_recent_list(monkeypatch):
    raw_meetings = [
        _raw("a", "A", "2026-01-02T10:00:00Z"),
        _raw("b", "B", "2026-01-01T10:00:00Z"),
    ]
    # matched_ids irrelevant for empty query; should not even be consulted.
    _patch(monkeypatch, raw_meetings, matched_ids=[])
    resp = _client().get("/meetings/search", params={"query": "   "})
    assert resp.status_code == 200
    assert [m["id"] for m in resp.json()] == ["a", "b"]


def test_search_route_not_shadowed_by_meeting_id(monkeypatch):
    # If /{meeting_id} shadowed /search, this would try to load a meeting named
    # "search" and 404. A 200 list proves the search route matched first.
    _patch(monkeypatch, [], matched_ids=[])
    resp = _client().get("/meetings/search", params={"query": "anything"})
    assert resp.status_code == 200


def test_text_constraints_are_forwarded_as_and_composed_filters(monkeypatch):
    captured: Dict[str, Any] = {}
    raw_meetings = [_raw("m1", "Review", "2026-01-01T10:00:00Z")]
    monkeypatch.setattr(search_routes, "load_all_raw_meetings", lambda: raw_meetings)
    fake_repo = types.SimpleNamespace(
        search_meeting_ids=lambda **kwargs: captured.update(kwargs) or ["m1"]
    )
    monkeypatch.setattr(
        search_routes,
        "get_sqlite_knowledge_service",
        lambda: types.SimpleNamespace(meeting_transcript_search_repository=fake_repo),
    )

    response = _client().get(
        "/meetings/search",
        params={"participants": "Miriam", "transcript": "opportunity,stage", "transcript_mode": "and"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["m1"]
    assert captured["participants"] == "Miriam"
    assert captured["transcript"] == "opportunity,stage"
    assert captured["transcript_mode"] == "and"


def test_scalar_filters_apply_to_grouped_meeting_members(monkeypatch):
    complete = _raw("mic1", "Review - Microphone", "2026-01-02T10:00:00Z", session_id="S", audio_source="Microphone")
    complete["is_post_processed"] = True
    zoom = _raw("zoom1", "Review - Zoom", "2026-01-02T10:00:00Z", session_id="S", audio_source="Zoom")
    zoom["is_post_processed"] = True
    incomplete = _raw("m2", "Later", "2026-01-03T10:00:00Z")
    _patch(monkeypatch, [complete, zoom, incomplete], matched_ids=[])
    monkeypatch.setattr(
        meeting_grouping,
        "build_analysis_summary",
        lambda *_args: MeetingAnalysisSummary(
            count=1,
            latest_filename="analysis.json",
            latest_timestamp="2026-01-02T10:00:00Z",
        ),
    )

    response = _client().get(
        "/meetings/search",
        params={"source": "zoom", "processing": "complete", "analysis": "has_analysis", "start_date": "2026-01-02", "end_date": "2026-01-02"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["mic1"]


def test_invalid_filter_values_are_rejected(monkeypatch):
    _patch(monkeypatch, [], matched_ids=[])

    invalid_status = _client().get("/meetings/search", params={"processing": "unknown"})
    invalid_dates = _client().get(
        "/meetings/search",
        params={"start_date": "2026-02-01", "end_date": "2026-01-01"},
    )

    assert invalid_status.status_code == 422
    assert invalid_dates.status_code == 422
