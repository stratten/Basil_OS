"""Spotlight search keeps partial results and reports incompleteness instead of returning nothing."""

from __future__ import annotations

import pytest

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval import (
    file_retrieval_service as retrieval_module,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.search_subprocess import (
    SearchProcessOutcome,
)


def _outcome(lines, *, timed_out=False, returncode=0, truncated=False, stderr_tail=""):
    return SearchProcessOutcome(
        lines=list(lines),
        timed_out=timed_out,
        returncode=returncode,
        stderr_tail=stderr_tail,
        truncated=truncated,
    )


def _install_fake_runner(monkeypatch, outcome):
    calls = []

    async def fake_runner(argv, *, timeout_seconds, max_lines=None):
        calls.append({"argv": list(argv), "timeout_seconds": timeout_seconds, "max_lines": max_lines})
        return outcome

    monkeypatch.setattr(retrieval_module, "run_bounded_search_process", fake_runner)
    return calls


@pytest.mark.asyncio
async def test_spotlight_timeout_keeps_partial_files_and_reports_error(tmp_path, monkeypatch):
    found = tmp_path / "Quarterly Report.pdf"
    found.write_bytes(b"%PDF-1.4 test")
    calls = _install_fake_runner(monkeypatch, _outcome([str(found)], timed_out=True, returncode=-15))

    service = retrieval_module.FileRetrievalService()
    result = await service.search_files_by_name("Quarterly Report")

    assert calls and calls[0]["argv"][0] == "mdfind"
    assert calls[0]["timeout_seconds"] == service.spotlight_timeout
    assert [meta.path for meta in result.files_found] == [str(found)]
    assert result.errors and "timed out" in result.errors[0]


@pytest.mark.asyncio
async def test_spotlight_complete_run_has_no_errors(tmp_path, monkeypatch):
    found = tmp_path / "notes.txt"
    found.write_text("hello")
    _install_fake_runner(monkeypatch, _outcome([str(found)]))

    result = await retrieval_module.FileRetrievalService().search_files_by_name("notes")

    assert len(result.files_found) == 1
    assert result.errors == []


@pytest.mark.asyncio
async def test_spotlight_truncation_is_reported(tmp_path, monkeypatch):
    _install_fake_runner(monkeypatch, _outcome([], truncated=True, returncode=-15))

    result = await retrieval_module.FileRetrievalService().search_files_by_name("anything")

    assert result.files_found == []
    assert result.errors and "cut short" in result.errors[0]


@pytest.mark.asyncio
async def test_spotlight_runner_exception_is_reported_not_silent(monkeypatch):
    async def exploding_runner(argv, *, timeout_seconds, max_lines=None):
        raise OSError("mdfind missing")

    monkeypatch.setattr(retrieval_module, "run_bounded_search_process", exploding_runner)

    result = await retrieval_module.FileRetrievalService().search_files_by_name("anything")

    assert result.files_found == []
    assert result.errors and "mdfind missing" in result.errors[0]
