"""Single entry point that turns a PDF, Word, Excel, PowerPoint or iWork file into bounded plain text."""

from __future__ import annotations

import logging
import os
import stat
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Union

from .iwork_reader import read_iwork_preview
from .models import (
    DEFAULT_LIMITS,
    Deadline,
    DocumentReadError,
    DocumentReadLimits,
    DocumentText,
    ReadContext,
    STATUS_DEADLINE,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_NO_TEXT,
    STATUS_OK,
    STATUS_TOO_LARGE,
    STATUS_UNSUPPORTED,
    TextAccumulator,
)
from .ooxml_readers import read_docx, read_pptx, read_xlsx
from .pdf_reader import read_pdf_pages

logger = logging.getLogger(__name__)

_KIND_BY_SUFFIX: Dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".pptx": "pptx",
    ".pages": "iwork",
    ".numbers": "iwork",
    ".key": "iwork",
}
LEGACY_SUFFIXES = frozenset({".doc", ".xls", ".ppt"})
DOCUMENT_EXTENSIONS = frozenset(_KIND_BY_SUFFIX)
_PREVIEW_ONLY_KINDS = frozenset({"pdf", "iwork"})
_READERS: Dict[str, Callable[[bytes, ReadContext], None]] = {
    "pdf": read_pdf_pages,
    "docx": read_docx,
    "xlsx": read_xlsx,
    "pptx": read_pptx,
    "iwork": read_iwork_preview,
}


def is_document_path(path: Union[str, "os.PathLike[str]"]) -> bool:
    """True for file types this reader can attempt, judged by extension only."""
    return os.path.splitext(os.fspath(path))[1].lower() in DOCUMENT_EXTENSIONS


def _read_bytes(path: str, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DocumentReadError(STATUS_ERROR, "The file could not be opened.") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise DocumentReadError(STATUS_ERROR, "Only regular files can be read.")
        if info.st_size > max_bytes:
            raise DocumentReadError(STATUS_TOO_LARGE, f"The file is larger than {max_bytes // 1_000_000} MB.")
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with handle:
            data = handle.read(max_bytes + 1)
    except OSError as error:
        raise DocumentReadError(STATUS_ERROR, "The file could not be read.") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(data) > max_bytes:
        raise DocumentReadError(STATUS_TOO_LARGE, f"The file is larger than {max_bytes // 1_000_000} MB.")
    return data


def _check_signature(kind: str, data: bytes) -> None:
    if kind == "pdf":
        if b"%PDF" not in data[:1024]:
            raise DocumentReadError(STATUS_ERROR, "The file does not look like a PDF.")
    elif data[:2] != b"PK":
        raise DocumentReadError(STATUS_ERROR, "The file does not look like a document package.")


def _failure(path: str, kind: str, status: str, detail: str, method: str = "") -> DocumentText:
    return DocumentText(path=path, kind=kind, status=status, method=method, detail=detail)


def read_document_text(
    path: Union[str, "os.PathLike[str]"],
    limits: DocumentReadLimits = DEFAULT_LIMITS,
    *,
    deadline_seconds: Optional[float] = None,
    clock: Callable[[], float] = time.monotonic,
) -> DocumentText:
    """Read ``path`` into bounded text; never raises, and reports problems through ``status`` and ``detail``."""
    path_text = os.fspath(path)
    suffix = os.path.splitext(path_text)[1].lower()
    kind = _KIND_BY_SUFFIX.get(suffix)
    if kind is None:
        if suffix in LEGACY_SUFFIXES:
            detail = "This is a legacy binary Office format. Save it as .docx, .xlsx or .pptx to read it."
        else:
            detail = "This file type is not a supported document."
        return _failure(path_text, suffix.lstrip("."), STATUS_UNSUPPORTED, detail)
    context = ReadContext(limits, TextAccumulator(limits.max_chars), Deadline(deadline_seconds, clock))
    try:
        data = _read_bytes(path_text, limits.max_bytes)
        _check_signature(kind, data)
        _READERS[kind](data, context)
    except DocumentReadError as error:
        return _failure(path_text, kind, error.status, error.detail, context.method)
    except Exception as error:
        logger.debug("Document read failed for %s", path_text, exc_info=True)
        return _failure(path_text, kind, STATUS_ERROR, f"The document could not be read ({type(error).__name__}).", context.method)
    text = context.accumulator.text()
    detail = context.detail
    if context.deadline_hit:
        status = STATUS_DEADLINE
        detail = "Reading stopped at the time limit, so the text is partial."
    elif not text.strip():
        status = STATUS_NO_TEXT if kind in _PREVIEW_ONLY_KINDS else STATUS_EMPTY
        detail = "No extractable text was found; a scanned or image-only file would need OCR." if kind in _PREVIEW_ONLY_KINDS else "The document has no text."
    else:
        status = STATUS_OK
    truncated = context.accumulator.truncated
    if truncated and text.strip():
        text = f"{text}\n[Text truncated at {limits.max_chars} characters]"
    return DocumentText(
        path=path_text,
        kind=kind,
        status=status,
        text=text if text.strip() else "",
        truncated=truncated,
        method=context.method,
        units=context.units,
        detail=detail,
    )
