"""Best-effort text for Pages and Numbers packages (and Keynote) from their embedded PDF preview."""

from __future__ import annotations

from .archive import ArchiveGuard
from .models import DocumentReadError, ReadContext, STATUS_UNSUPPORTED
from .pdf_reader import read_pdf_pages

PREVIEW_MEMBER = "QuickLook/Preview.pdf"


def read_iwork_preview(data: bytes, context: ReadContext) -> None:
    """iWork stores content in a proprietary format, so only a bundled PDF preview can be read, and it may cover just the first page."""
    with ArchiveGuard(data, context.limits) as guard:
        member = guard.find_case_insensitive(PREVIEW_MEMBER)
        if member is None:
            raise DocumentReadError(
                STATUS_UNSUPPORTED,
                "This iWork file has no readable text preview. Export it to PDF or Word, Excel or PowerPoint format to read it.",
            )
        preview = guard.read(member)
    if preview is None:
        raise DocumentReadError(STATUS_UNSUPPORTED, "This iWork file has no readable text preview.")
    read_pdf_pages(preview, context)
    context.method = "iwork_preview"
    context.detail = "Text comes from the embedded preview, which may cover only the first page."
