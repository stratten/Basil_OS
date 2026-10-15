import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph.discovery_handoff import build_discovery_handoff
from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval import (
    file_find_orchestrator,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_models import ContentEncoding
from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_retrieval_service import (
    FileRetrievalService,
)
from .document_fixtures import make_pdf, make_pptx, make_xlsx


@pytest.mark.asyncio
async def test_base64_read_of_a_pdf_keeps_the_payload_and_adds_extracted_text(tmp_path):
    path = make_pdf(tmp_path / "agenda.pdf", ["Agenda item vendor renewal"])
    content = await FileRetrievalService().read_file_content(str(path), ContentEncoding.BASE64)
    assert content.content_type == ContentEncoding.BASE64 and content.base64_content
    assert "[Page 1]\nAgenda item vendor renewal" in content.extracted_text


@pytest.mark.asyncio
async def test_extracted_text_read_of_a_spreadsheet_returns_text_not_base64(tmp_path):
    path = make_xlsx(tmp_path / "budget.xlsx", [("Q3", [["Region", "Revenue"], ["West", 1200]])])
    content = await FileRetrievalService().read_file_content(str(path), ContentEncoding.EXTRACTED_TEXT)
    assert content.content_type == ContentEncoding.EXTRACTED_TEXT
    assert content.extraction_method == "document_reader:xlsx"
    assert "R2: West | 1200" in content.extracted_text and content.base64_content is None


@pytest.mark.asyncio
async def test_scanned_pdf_falls_back_to_base64_when_no_text_is_found(tmp_path):
    path = make_pdf(tmp_path / "scan.pdf", [""])
    content = await FileRetrievalService().read_file_content(str(path), ContentEncoding.EXTRACTED_TEXT)
    assert content.content_type == ContentEncoding.BASE64 and content.base64_content
    assert not content.extracted_text


@pytest.mark.asyncio
async def test_text_and_legacy_files_are_unchanged_by_the_reader(tmp_path):
    plain = tmp_path / "notes.txt"
    plain.write_text("plain words", encoding="utf-8")
    legacy = tmp_path / "old.doc"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0 legacy")
    service = FileRetrievalService()
    text_content = await service.read_file_content(str(plain), ContentEncoding.BASE64)
    legacy_content = await service.read_file_content(str(legacy), ContentEncoding.BASE64)
    assert text_content.extracted_text is None
    assert legacy_content.extracted_text is None and legacy_content.base64_content


@pytest.mark.asyncio
async def test_prepared_deck_reaches_the_discovery_handoff_with_its_text(tmp_path):
    path = make_pptx(tmp_path / "deck.pptx", [(["Renewal timeline slide"], ["Mention the discount"])])
    prepared = await file_find_orchestrator.prepare_path(FileRetrievalService(), str(path))
    assert prepared["result_kind"] == "prepared" and "Renewal timeline slide" in prepared["extracted_text"]
    step = (SimpleNamespace(tool="file_service_prepare_file_by_path"), json.dumps({"result": prepared}))
    handoff = build_discovery_handoff([step], [])
    assert handoff is not None
    assert "Mention the discount" in handoff.prepared_files[0]["extracted_text"]
