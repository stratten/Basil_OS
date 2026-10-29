"""PDF text extraction through pypdf, bounded by page count, characters and a deadline."""

from __future__ import annotations

import io

from .models import DocumentReadError, ReadContext, STATUS_ENCRYPTED, STATUS_ERROR


def read_pdf_pages(data: bytes, context: ReadContext) -> None:
    """Append ``[Page N]`` blocks of extracted text to the context; scanned pages contribute nothing."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise DocumentReadError(STATUS_ENCRYPTED, "The PDF is password-protected.")
        pages = reader.pages
        page_count = len(pages)
    except DocumentReadError:
        raise
    except Exception as error:
        raise DocumentReadError(STATUS_ERROR, f"The PDF could not be read ({type(error).__name__}).") from error
    context.method = "pypdf"
    for index in range(page_count):
        if index >= context.limits.max_pdf_pages:
            context.accumulator.truncated = True
            break
        if context.out_of_time():
            break
        try:
            text = (pages[index].extract_text() or "").strip()
        except Exception:
            text = ""
        context.units = index + 1
        if text and not context.accumulator.add_line(f"[Page {index + 1}]\n{text}"):
            break
