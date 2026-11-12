"""Where the transcript file is refreshed: saved transcripts, saved analyses, meeting detail, and the retrieval tool's refresh_first.

Every hook is best-effort: a failure in the file step must never fail the save, the analysis, or the query it rides on.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.internal_basil_tools import retrieval_tool
from api.services.retrieval.sources.zettel_source import ZettelBackedRetrievalSource
from api.services.whisper_live_core.post_processing import meeting_transcript_file as tf
from api.services.whisper_live_core.post_processing.meeting_transcript_markdown import TRANSCRIPT_MARKDOWN_FILENAME
from api.services.whisper_live_core.post_processing.transcript_merger import save_transcript_to_file


def _meeting(root: Path, folder="mic-1", source="Microphone", session="S1", segments=None) -> Path:
    directory = root / folder
    directory.mkdir()
    (directory / "metadata.json").write_text(json.dumps({
        "id": folder, "name": f"Stand Up - {source}", "session_id": session,
        "audio_source": source, "start_time": "2026-11-11T16:03:26.000000Z", "recording_part_index": 0,
    }))
    if segments is not None:
        (directory / "transcript.json").write_text(json.dumps({"segments": segments}))
    return directory


SEGMENTS = [{"start": 1.0, "end": 2.0, "text": "Hello there.", "speaker": None}]


def test_saving_a_transcript_refreshes_the_calls_transcript_file(tmp_path):
    directory = _meeting(tmp_path)
    asyncio.run(save_transcript_to_file({"segments": SEGMENTS}, directory / "transcript.json"))
    written = (directory / TRANSCRIPT_MARKDOWN_FILENAME).read_text(encoding="utf-8")
    assert written.endswith("[0:01] Microphone\n    Hello there.\n")


def test_saving_a_transcript_in_a_folder_without_metadata_just_saves(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    asyncio.run(save_transcript_to_file({"segments": SEGMENTS}, bare / "transcript.json"))
    assert (bare / "transcript.json").exists()
    assert not (bare / TRANSCRIPT_MARKDOWN_FILENAME).exists()


def test_a_failing_file_step_never_fails_the_transcript_save(tmp_path, monkeypatch):
    directory = _meeting(tmp_path)

    def explode(_directory):
        raise OSError("disk full")

    monkeypatch.setattr(tf, "ensure_meeting_transcript_markdown", explode)
    asyncio.run(save_transcript_to_file({"segments": SEGMENTS}, directory / "transcript.json"))
    assert json.loads((directory / "transcript.json").read_text())["segments"][0]["text"] == "Hello there."


def _analyzer(directory: Path):
    from api.services.whisper_live_core.post_processing.meeting_analyzer import MeetingAnalyzer

    analyzer = MeetingAnalyzer.__new__(MeetingAnalyzer)
    analyzer.meeting_id = directory.name
    analyzer.meeting_dir = directory
    analyzer.saved_analysis_filename = None
    return analyzer


def _analysis():
    return SimpleNamespace(
        to_dict=lambda: {"summary": "s"},
        analyzed_at=datetime(2026, 11, 11, 16, 15, 36),
        modes_analyzed=["summary"],
        model_used="test-model",
    )


def _stub_metadata(monkeypatch):
    metadata = SimpleNamespace(analyses=None, to_dict=lambda: {"id": "mic-1"})
    monkeypatch.setattr(
        "api.services.meetings.meeting_recorder.MeetingRecorder.load_metadata",
        staticmethod(lambda meeting_id: metadata),
    )


def test_saving_an_analysis_writes_the_transcript_file(tmp_path, monkeypatch):
    directory = _meeting(tmp_path, segments=SEGMENTS)
    _stub_metadata(monkeypatch)
    asyncio.run(_analyzer(directory)._save_analysis(_analysis()))
    assert any(path.name.startswith("analysis_") for path in directory.iterdir())
    assert (directory / TRANSCRIPT_MARKDOWN_FILENAME).read_text(encoding="utf-8").endswith("[0:01] Microphone\n    Hello there.\n")


def test_a_failing_file_step_never_fails_a_saved_analysis(tmp_path, monkeypatch):
    directory = _meeting(tmp_path, segments=SEGMENTS)
    _stub_metadata(monkeypatch)

    def explode(_directory):
        raise OSError("disk full")

    monkeypatch.setattr(tf, "ensure_meeting_transcript_markdown", explode)
    analyzer = _analyzer(directory)
    asyncio.run(analyzer._save_analysis(_analysis()))
    assert analyzer.saved_analysis_filename is not None
    assert (directory / analyzer.saved_analysis_filename).exists()


class _FakeMeetingSource:
    def gather_context(self, conn, source_ids):
        return {source_id: {"transcript": "t", "analyses": [], "meeting_name": "Stand Up"} for source_id in source_ids}


def _meeting_detail_source(monkeypatch):
    source = ZettelBackedRetrievalSource.__new__(ZettelBackedRetrievalSource)
    source.source_kind = "meeting"
    monkeypatch.setattr(source, "hydrate", lambda conn, source_id: SimpleNamespace(metadata={"title": "Stand Up"}), raising=False)
    monkeypatch.setattr(
        "api.services.retrieval.sources.zettel_source.sources_by_kind",
        lambda: {"meeting": _FakeMeetingSource(), "agent_task": _FakeMeetingSource()},
    )
    return source


def test_meeting_detail_includes_the_transcript_file_path(monkeypatch):
    source = _meeting_detail_source(monkeypatch)
    monkeypatch.setattr(tf, "meeting_transcript_markdown_path", lambda meeting_id: f"/meetings/{meeting_id}/transcript_interleaved.md")
    detail = source.detail(None, "mic-1")
    assert detail["context"]["transcript_markdown_path"] == "/meetings/mic-1/transcript_interleaved.md"
    assert detail["detail_available"] is True


def test_meeting_detail_reports_no_path_when_the_file_cannot_be_produced(monkeypatch):
    source = _meeting_detail_source(monkeypatch)
    monkeypatch.setattr(tf, "meeting_transcript_markdown_path", lambda meeting_id: None)
    assert source.detail(None, "mic-1")["context"]["transcript_markdown_path"] is None


def test_other_source_kinds_do_not_get_a_transcript_path(monkeypatch):
    source = _meeting_detail_source(monkeypatch)
    source.source_kind = "agent_task"
    detail = source.detail(None, "task-1")
    assert "transcript_markdown_path" not in detail["context"]


def _service(captured):
    def search(request):
        captured["search"] = request
        return {"success": True, "action": "search", "results": []}

    def detail(request):
        captured["detail"] = request
        return {"success": True, "action": "detail"}

    return SimpleNamespace(search=search, detail=detail, catalog=lambda: {"success": True})


@pytest.mark.asyncio
async def test_refresh_first_collects_records_before_a_search_and_reports_the_outcome(monkeypatch):
    captured, order = {}, []

    async def fake_refresh():
        order.append("refresh")
        return {"status": "completed"}

    service = _service(captured)
    original_search = service.search
    service.search = lambda request: (order.append("search"), original_search(request))[1]
    monkeypatch.setattr(retrieval_tool, "refresh_memory_stream", fake_refresh)
    monkeypatch.setattr(retrieval_tool, "get_unified_retrieval_service", lambda: service)

    response = json.loads(await retrieval_tool.create_retrieval_tool().ainvoke({"action": "search", "query": "stand-up", "refresh_first": True}))
    assert order == ["refresh", "search"]
    assert response["memory_refresh"] == {"status": "completed"}


@pytest.mark.asyncio
async def test_refresh_first_is_off_by_default_and_does_not_touch_the_response(monkeypatch):
    calls = []

    async def fake_refresh():
        calls.append(True)
        return {"status": "completed"}

    monkeypatch.setattr(retrieval_tool, "refresh_memory_stream", fake_refresh)
    monkeypatch.setattr(retrieval_tool, "get_unified_retrieval_service", lambda: _service({}))
    response = json.loads(await retrieval_tool.create_retrieval_tool().ainvoke({"action": "search", "query": "stand-up"}))
    assert calls == []
    assert "memory_refresh" not in response


@pytest.mark.asyncio
async def test_refresh_first_is_ignored_for_detail_and_catalog(monkeypatch):
    calls = []

    async def fake_refresh():
        calls.append(True)
        return {"status": "completed"}

    monkeypatch.setattr(retrieval_tool, "refresh_memory_stream", fake_refresh)
    monkeypatch.setattr(retrieval_tool, "get_unified_retrieval_service", lambda: _service({}))
    tool = retrieval_tool.create_retrieval_tool()
    detail = json.loads(await tool.ainvoke({"action": "detail", "source_kind": "meeting", "source_id": "m1", "refresh_first": True}))
    catalog = json.loads(await tool.ainvoke({"action": "catalog", "refresh_first": True}))
    assert calls == []
    assert "memory_refresh" not in detail and "memory_refresh" not in catalog


def test_the_retrieval_tool_teaches_the_agent_the_file_and_the_refresh():
    tool = retrieval_tool.create_retrieval_tool()
    assert "transcript_markdown_path" in tool.description
    assert "refresh_first=true" in tool.description
    assert "~/.basil/meetings/" in tool.description
    assert retrieval_tool.RetrievalToolInput(action="catalog").refresh_first is False
