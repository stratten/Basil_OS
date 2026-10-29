import os
from pathlib import Path

import pytest

from api.services.document_reading import DocumentReadLimits, DocumentText, DocumentTextCache
from api.services.document_reading import cache as cache_module

from .document_fixtures import make_docx_package, word_document

LIMITS = DocumentReadLimits()


def doc_text(path: str, text: str = "words", status: str = "ok") -> DocumentText:
    return DocumentText(path=path, kind="docx", status=status, text=text)


def stat_of(path: Path):
    info = path.stat()
    return info.st_size, info.st_mtime


@pytest.fixture
def counted_reads(monkeypatch):
    calls = []
    original = cache_module.read_document_text

    def counting(path, limits, **kwargs):
        calls.append(str(path))
        return original(path, limits, **kwargs)

    monkeypatch.setattr(cache_module, "read_document_text", counting)
    return calls


def test_put_then_get_round_trips_and_deadline_results_are_not_stored():
    cache = DocumentTextCache()
    key = cache.key_for(Path("/tmp/a.docx"), 10, 1.0)
    cache.put(key, doc_text("/tmp/a.docx", "kept"))
    assert cache.get(key).text == "kept"
    deadline_key = cache.key_for(Path("/tmp/b.docx"), 10, 1.0)
    cache.put(deadline_key, doc_text("/tmp/b.docx", "partial", status="deadline"))
    assert cache.get(deadline_key) is None and len(cache) == 1


def test_read_caches_by_path_size_and_mtime_and_rereads_after_an_edit(tmp_path, counted_reads):
    path = make_docx_package(tmp_path / "plan.docx", word_document("<w:p><w:r><w:t>first draft</w:t></w:r></w:p>"))
    cache = DocumentTextCache()
    size, mtime = stat_of(path)
    assert "first draft" in cache.read(path, size, mtime, LIMITS).text
    assert "first draft" in cache.read(path, size, mtime, LIMITS).text
    assert len(counted_reads) == 1
    make_docx_package(path, word_document("<w:p><w:r><w:t>second draft is longer</w:t></w:r></w:p>"))
    os.utime(path, (mtime + 30, mtime + 30))
    new_size, new_mtime = stat_of(path)
    assert "second draft" in cache.read(path, new_size, new_mtime, LIMITS).text
    assert len(counted_reads) == 2


def test_cold_reads_can_be_refused_and_cached_text_is_still_returned(tmp_path, counted_reads):
    path = make_docx_package(tmp_path / "plan.docx", word_document("<w:p><w:r><w:t>cached words</w:t></w:r></w:p>"))
    cache = DocumentTextCache()
    size, mtime = stat_of(path)
    assert cache.read(path, size, mtime, LIMITS, cold_ok=False) is None
    assert counted_reads == []
    cache.read(path, size, mtime, LIMITS)
    assert cache.read(path, size, mtime, LIMITS, cold_ok=False).text == "cached words"


def test_file_level_failures_are_remembered_so_they_are_not_retried(tmp_path, counted_reads):
    broken = tmp_path / "broken.docx"
    broken.write_text("not a zip", encoding="utf-8")
    cache = DocumentTextCache()
    size, mtime = stat_of(broken)
    assert cache.read(broken, size, mtime, LIMITS).status == "error"
    assert cache.read(broken, size, mtime, LIMITS).status == "error"
    assert len(counted_reads) == 1


def test_eviction_respects_entry_and_character_budgets():
    by_entries = DocumentTextCache(max_entries=2, max_chars=1000)
    for index in range(3):
        by_entries.put(by_entries.key_for(Path(f"/d/{index}.docx"), 1, 1.0), doc_text(f"/d/{index}.docx", "x"))
    assert len(by_entries) == 2 and by_entries.get(by_entries.key_for(Path("/d/0.docx"), 1, 1.0)) is None
    by_chars = DocumentTextCache(max_entries=10, max_chars=10)
    by_chars.put(by_chars.key_for(Path("/d/a.docx"), 1, 1.0), doc_text("/d/a.docx", "123456"))
    by_chars.put(by_chars.key_for(Path("/d/b.docx"), 1, 1.0), doc_text("/d/b.docx", "123456"))
    assert len(by_chars) == 1 and by_chars.chars == 6


def test_retain_under_keeps_only_paths_inside_the_roots_and_not_name_prefix_siblings():
    cache = DocumentTextCache()
    for name in ("/a/proj/one.docx", "/a/project/two.docx", "/a/other/three.docx", "/a/proj"):
        cache.put(cache.key_for(Path(name), 1, 1.0), doc_text(name))
    removed = cache.retain_under([Path("/a/proj")])
    assert removed == 2
    assert cache.get(cache.key_for(Path("/a/proj/one.docx"), 1, 1.0)) is not None
    assert cache.get(cache.key_for(Path("/a/proj"), 1, 1.0)) is not None
    assert cache.get(cache.key_for(Path("/a/project/two.docx"), 1, 1.0)) is None
