"""Tests for the file-find orchestrator: Spotlight -> cloud fallback, ranking, and result contract."""

from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_find_orchestrator import (
    find_or_list_candidates,
    prepare_path,
)

DRIVE_SHARED_BASE = (
    "/Users/x/Library/CloudStorage/GoogleDrive-x@y.com/"
    ".shortcut-targets-by-id/AAA/PayLink/Collateral"
)


def _fake_llm_request(path):
    metadata = SimpleNamespace(
        name=os.path.basename(path),
        size=1234,
        file_type=SimpleNamespace(value="pdf"),
        created_date=datetime(2026, 1, 1, 12, 0, 0),
        modified_date=datetime(2026, 1, 2, 12, 0, 0),
        extension=os.path.splitext(path)[1].lower(),
        mime_type="application/pdf",
        parent_directory=os.path.dirname(path),
    )
    file_content = SimpleNamespace(
        metadata=metadata,
        base64_content="QUJD",
        extracted_text=None,
    )
    return SimpleNamespace(
        file_path=path,
        file_content=file_content,
        encoding_preference=SimpleNamespace(value="base64"),
        prompt_context="ctx",
    )


class FakeRetrieval:
    def __init__(self, files_found=None):
        self._files_found = files_found or []

    async def search_files_by_name(self, filename, search_paths=None):
        return SimpleNamespace(files_found=list(self._files_found))

    async def prepare_file_for_llm(self, path, context, encoding):
        return _fake_llm_request(path)


class FakeCloud:
    def __init__(self, entries=None):
        self._entries = entries or []
        self.called = False

    async def search_cloud_files(self, filename, provider=None):
        self.called = True
        return list(self._entries)


def _spotlight_meta(path, *, ext, size, name=None, mtime=None):
    return SimpleNamespace(
        path=path,
        name=name or os.path.basename(path),
        size=size,
        modified_date=mtime or datetime(2026, 1, 1),
        file_type=SimpleNamespace(value="unknown"),
        extension=ext,
        is_readable=True,
    )


def _cloud_entry(name, *, size=80_000, mtime=1000.0, base=DRIVE_SHARED_BASE):
    return {
        "name": name,
        "path": f"{base}/{name}",
        "size": size,
        "modified_date": mtime,
        "is_readable": True,
        "cloud_provider": "google_drive",
        "is_cloud_file": True,
    }


@pytest.mark.asyncio
async def test_spotlight_empty_falls_back_to_cloud_and_lists_candidates():
    retrieval = FakeRetrieval(files_found=[])
    cloud = FakeCloud([
        _cloud_entry("V2 PayLink User Guide - AB.pdf"),
        _cloud_entry("PayLink User Guide - Bankwest.pdf"),
        _cloud_entry("PayLink Install Notes.gdoc", size=150),
    ])

    result = await find_or_list_candidates(retrieval, cloud, "PayLink User Guide")

    assert cloud.called is True
    assert result["success"] is True
    assert result["result_kind"] == "candidates"
    assert "base64_content" not in result  # no content prepared for ambiguous matches
    names = [c["name"] for c in result["candidates"]]
    assert "V2 PayLink User Guide - AB.pdf" in names
    # PDFs outrank the tiny .gdoc pointer stub.
    assert result["candidates"][0]["name"].endswith(".pdf")
    assert result["candidates"][-1]["name"].endswith(".gdoc")


@pytest.mark.asyncio
async def test_weak_spotlight_hit_still_consults_cloud():
    retrieval = FakeRetrieval(files_found=[
        _spotlight_meta(
            "/Users/x/Downloads/Gemini Meeting Notes.gdoc",
            ext=".gdoc",
            size=200,
            name="Gemini Meeting Notes.gdoc",
        )
    ])
    cloud = FakeCloud([
        _cloud_entry("V2 PayLink User Guide - AB.pdf"),
        _cloud_entry("PayLink User Guide - Bankwest.pdf"),
    ])

    result = await find_or_list_candidates(retrieval, cloud, "PayLink User Guide")

    assert cloud.called is True
    assert result["result_kind"] == "candidates"
    assert result["candidates"][0]["name"].endswith(".pdf")


@pytest.mark.asyncio
async def test_strong_local_hit_skips_cloud_and_prepares(tmp_path):
    real = tmp_path / "PayLink User Guide.pdf"
    real.write_bytes(b"%PDF-1.4 test")
    retrieval = FakeRetrieval(files_found=[
        _spotlight_meta(str(real), ext=".pdf", size=90_000, mtime=datetime(2026, 6, 1))
    ])
    cloud = FakeCloud([_cloud_entry("should-not-be-used.pdf")])

    result = await find_or_list_candidates(retrieval, cloud, "PayLink User Guide")

    assert cloud.called is False
    assert result["result_kind"] == "prepared"
    assert result["base64_content"] == "QUJD"


@pytest.mark.asyncio
async def test_confident_single_cloud_match_is_prepared(tmp_path):
    real = tmp_path / "PayLink Installation Guide.pdf"
    real.write_bytes(b"%PDF-1.4 test")
    retrieval = FakeRetrieval(files_found=[])
    cloud = FakeCloud([
        {
            "name": real.name,
            "path": str(real),
            "size": 90_000,
            "modified_date": 1000.0,
            "is_readable": True,
            "cloud_provider": "google_drive",
        }
    ])

    result = await find_or_list_candidates(retrieval, cloud, "PayLink Installation Guide")

    assert result["result_kind"] == "prepared"
    assert result["file_name"] == real.name


@pytest.mark.asyncio
async def test_confident_only_prepares_top_even_when_ambiguous(tmp_path):
    first = tmp_path / "A PayLink User Guide.pdf"
    second = tmp_path / "B PayLink User Guide.pdf"
    first.write_bytes(b"%PDF a")
    second.write_bytes(b"%PDF b")
    retrieval = FakeRetrieval(files_found=[])
    cloud = FakeCloud([
        {"name": first.name, "path": str(first), "size": 80_000, "modified_date": 1000.0},
        {"name": second.name, "path": str(second), "size": 80_000, "modified_date": 1000.0},
    ])

    result = await find_or_list_candidates(
        retrieval, cloud, "PayLink User Guide", confident_only=True
    )

    assert result["result_kind"] == "prepared"


@pytest.mark.asyncio
async def test_not_found_returns_failure():
    result = await find_or_list_candidates(FakeRetrieval(files_found=[]), FakeCloud([]), "nothing here")

    assert result["success"] is False
    assert result["result_kind"] == "not_found"


@pytest.mark.asyncio
async def test_prepare_path_bad_path_fails():
    result = await prepare_path(FakeRetrieval(), "/definitely/not/a/real/file.pdf")

    assert result["success"] is False
    assert result["result_kind"] == "not_found"


@pytest.mark.asyncio
async def test_prepare_path_reads_real_file(tmp_path):
    real = tmp_path / "chosen.pdf"
    real.write_bytes(b"%PDF data")

    result = await prepare_path(FakeRetrieval(), str(real), "context")

    assert result["success"] is True
    assert result["result_kind"] == "prepared"
    assert result["base64_content"] == "QUJD"
