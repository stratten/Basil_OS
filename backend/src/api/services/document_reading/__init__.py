"""Shared reader that extracts bounded plain text from PDF, Word, Excel, PowerPoint and iWork files."""

from .cache import DocumentTextCache
from .models import (
    AGENT_DEADLINE_SECONDS,
    AGENT_LIMITS,
    COMPANION_LIMITS,
    CONVERSATION_LIMITS,
    DEFAULT_LIMITS,
    FINAL_STATUSES,
    DocumentReadLimits,
    DocumentText,
)
from .reader import DOCUMENT_EXTENSIONS, is_document_path, read_document_text

__all__ = [
    "AGENT_DEADLINE_SECONDS",
    "AGENT_LIMITS",
    "COMPANION_LIMITS",
    "CONVERSATION_LIMITS",
    "DEFAULT_LIMITS",
    "DOCUMENT_EXTENSIONS",
    "DocumentReadLimits",
    "DocumentText",
    "DocumentTextCache",
    "FINAL_STATUSES",
    "is_document_path",
    "read_document_text",
]
