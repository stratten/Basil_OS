"""File context detection must not run osascript on the event-loop thread."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval import (
    file_context_detection_service as detection_module,
)


def _install_recording_run(monkeypatch, stdout):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": list(argv), "thread": threading.get_ident(), "kwargs": kwargs})
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(detection_module.subprocess, "run", fake_run)
    return calls


@pytest.mark.asyncio
async def test_window_info_runs_osascript_off_the_event_loop(monkeypatch):
    calls = _install_recording_run(monkeypatch, "Preview|||com.apple.Preview|||Report.pdf")
    loop_thread = threading.get_ident()

    info = await detection_module.FileContextDetectionService()._get_window_info()

    assert info["success"] is True
    assert info["window_title"] == "Report.pdf"
    assert len(calls) == 1
    assert calls[0]["argv"][0] == "osascript"
    assert calls[0]["kwargs"]["timeout"] == 10
    assert calls[0]["thread"] != loop_thread


@pytest.mark.asyncio
async def test_accessibility_probe_runs_osascript_off_the_event_loop(monkeypatch):
    calls = _install_recording_run(monkeypatch, "no file information here")
    loop_thread = threading.get_ident()
    current = detection_module.FileContextResult(
        success=False,
        app_name="Preview",
        bundle_id="com.apple.Preview",
        window_title="Untitled",
    )

    result = await detection_module.FileContextDetectionService()._probe_accessibility(current)

    assert result is current
    assert len(calls) == 1
    assert calls[0]["thread"] != loop_thread
