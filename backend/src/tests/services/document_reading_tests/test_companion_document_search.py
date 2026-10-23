import os
from pathlib import Path

import pytest

from api.services.meeting_companion.context_search import ContextSearchService, RootRejected, SearchLimits, validate_root
from api.services.meeting_companion.context_service import ContextService
from .document_fixtures import make_pdf, make_xlsx, write_zip


def build_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "notes.md").write_text("General notes about the project.\n", encoding="utf-8")
    make_pdf(root / "vendor_renewal.pdf", ["Vendor renewal terms are net sixty days"])
    make_xlsx(root / "budget.xlsx", [("Q3", [["Region", "Revenue"], ["West", 1200]])])
    return root


def make_service(root: Path, **overrides) -> ContextSearchService:
    service = ContextSearchService(limits=SearchLimits(**overrides) if overrides else None)
    resolved, kind = validate_root(str(root), home=root.parent.parent)
    service.add_root("r1", resolved, kind, root.name)
    return service


def test_warmed_pdf_and_spreadsheet_are_searchable(tmp_path):
    service = make_service(build_project(tmp_path))
    assert service.warm_documents() == 2
    pdf_pack = service.search(["vendor renewal terms"])
    assert any(excerpt.path == "proj/vendor_renewal.pdf" and "net sixty days" in excerpt.text for excerpt in pdf_pack.excerpts)
    sheet_pack = service.search(["region revenue"])
    assert any(excerpt.path == "proj/budget.xlsx" for excerpt in sheet_pack.excerpts)


def test_table_cell_borders_do_not_break_a_multi_word_match(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "table.md").write_text("| Region | Revenue |\n| West | 1200 |\n", encoding="utf-8")
    pack = make_service(root).search(["region revenue"])
    assert any("| Region | Revenue |" in excerpt.text for excerpt in pack.excerpts)


def test_cold_document_is_read_only_when_its_name_matches_the_query(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    make_pdf(root / "contract.pdf", ["contract payment terms: net sixty"])
    service = make_service(root)
    unmatched = service.search(["payment terms"])
    assert unmatched.excerpts == [] and unmatched.scanned_files == 0
    matched = service.search(["contract payment terms"])
    assert any("net sixty" in excerpt.text for excerpt in matched.excerpts)


def test_edited_document_is_re_extracted_after_the_manifest_refresh(tmp_path):
    root = build_project(tmp_path)
    service = make_service(root, manifest_ttl_seconds=0.0)
    service.warm_documents()
    assert service.search(["vendor renewal terms"]).excerpts
    path = root / "vendor_renewal.pdf"
    before = path.stat().st_mtime
    make_pdf(path, ["Vendor renewal moved to quarterly invoicing instead"])
    os.utime(path, (before + 60, before + 60))
    updated = service.search(["vendor renewal quarterly invoicing"])
    assert any("quarterly invoicing" in excerpt.text for excerpt in updated.excerpts)
    assert not any("net sixty" in excerpt.text for excerpt in service.search(["vendor renewal terms"]).excerpts)


def test_detaching_a_root_drops_its_cached_document_text(tmp_path):
    service = make_service(build_project(tmp_path))
    service.warm_documents()
    assert len(service._documents) == 2
    service.remove_root("r1")
    assert len(service._documents) == 0


def test_warm_up_stops_when_the_root_is_detached_mid_run(tmp_path):
    service = make_service(build_project(tmp_path))
    original = service._documents.read
    calls = []

    def detaching_read(*args, **kwargs):
        calls.append(args[0].name)
        if len(calls) == 1:
            service.remove_root("r1")
        return original(*args, **kwargs)

    service._documents.read = detaching_read
    service.warm_documents()
    assert len(calls) == 1
    assert len(service._documents) == 0


def test_scanned_pdf_and_legacy_files_contribute_nothing_and_do_not_fail(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    make_pdf(root / "scan.pdf", [""])
    (root / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0 legacy contract words")
    (root / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0 legacy contract words")
    (root / "deck.key").write_bytes(b"-----BEGIN PRIVATE KEY----- contract words")
    service = make_service(root)
    assert service.warm_documents() == 0
    pack = service.search(["scan contract words"])
    assert pack.excerpts == []


def test_a_single_pdf_can_be_attached_but_a_private_key_cannot(tmp_path):
    pdf = make_pdf(tmp_path / "proj" / "brief.pdf", ["Brief text"])
    resolved, kind = validate_root(str(pdf), home=tmp_path.parent)
    assert kind == "file" and resolved == pdf.resolve()
    key = tmp_path / "proj" / "server.key"
    key.write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    with pytest.raises(RootRejected):
        validate_root(str(key), home=tmp_path.parent)


def test_a_corrupt_office_file_is_skipped_and_other_files_still_match(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    write_zip(root / "broken.xlsx", {"docProps/app.xml": "<x/>"})
    (root / "plain_notes.md").write_text("The vendor renewal checklist lives here.\n", encoding="utf-8")
    service = make_service(root)
    service.warm_documents()
    pack = service.search(["vendor renewal checklist"])
    assert [excerpt.path for excerpt in pack.excerpts] == ["proj/plain_notes.md"]


@pytest.mark.asyncio
async def test_rebuild_vocabulary_warms_the_document_cache_in_the_background_path(tmp_path):
    root = build_project(tmp_path)
    service = ContextService()
    resolved, kind = validate_root(str(root), home=root.parent.parent)
    service.attach_root("r1", resolved, kind, root.name)
    assert await service.rebuild_vocabulary() > 0
    assert len(service._search._documents) == 2
    lookup = await service.lookup("what are the vendor renewal terms")
    assert lookup is not None and any("net sixty days" in excerpt.text for excerpt in lookup.pack.excerpts)
