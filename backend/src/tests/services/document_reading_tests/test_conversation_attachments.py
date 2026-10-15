import pytest

from api.services.conversation.document_processing_service import DocumentProcessingService
from .document_fixtures import make_pptx, make_xlsx


@pytest.mark.asyncio
async def test_local_provider_receives_spreadsheet_and_deck_text(tmp_path):
    sheet = make_xlsx(tmp_path / "budget.xlsx", [("Q3", [["Region", "Revenue"], ["West", 1200]])])
    deck = make_pptx(tmp_path / "deck.pptx", [(["Renewal timeline slide"], None)])
    result = await DocumentProcessingService().process_files_for_model([str(sheet), str(deck)], "Summarize these", "local")
    assert "R2: West | 1200" in result["content"] and "Renewal timeline slide" in result["content"]
    assert "could not extract" not in result["content"]


@pytest.mark.asyncio
async def test_anthropic_provider_prepends_office_text_instead_of_dropping_it(tmp_path):
    sheet = make_xlsx(tmp_path / "budget.xlsx", [("Q3", [["Region", "Revenue"], ["West", 1200]])])
    result = await DocumentProcessingService().process_files_for_model([str(sheet)], "Summarize", "anthropic")
    assert result["method"] == "text_prepend"
    assert "--- budget.xlsx ---" in result["content"] and "R2: West | 1200" in result["content"]


@pytest.mark.asyncio
async def test_unreadable_office_file_is_reported_not_raised(tmp_path):
    broken = tmp_path / "broken.xlsx"
    broken.write_text("not a zip", encoding="utf-8")
    result = await DocumentProcessingService().process_files_for_model([str(broken)], "Summarize", "local")
    assert "could not extract text content" in result["content"]
