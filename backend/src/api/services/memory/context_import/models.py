"""Data types and limits for importing a user's personal context."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional

SOURCE_KIND = "imported_context"
EVENT_TYPE = "imported_note"

CATEGORY_DATED = "dated"
CATEGORY_UNDATED = "undated"
CATEGORY_STABLE_FACT = "stable_fact"
CATEGORIES = (CATEGORY_DATED, CATEGORY_UNDATED, CATEGORY_STABLE_FACT)

# A model reads an import chunk by chunk, so the size is bounded by how long that takes: about 70 chunks of 6,000 characters.
MAX_IMPORT_CHARS = 400_000
MAX_ITEMS = 5000
MAX_ITEM_CHARS = 2000
# Matches the per-proposal limit on MemoryProposal.observation.
MAX_STABLE_FACT_CHARS = 240


class ImportTooLargeError(ValueError):
    """The submitted text is larger than one import may be."""


class ImportEmptyError(ValueError):
    """The submitted text held nothing that could be imported."""


@dataclass(frozen=True)
class ImportItem:
    category: str
    text: str
    title: str
    section: str = ""
    occurred_at: Optional[str] = None

    @property
    def item_id(self) -> str:
        """Deterministic id from the normalized content and date, so re-importing the same file adds nothing."""
        normalized = re.sub(r"\s+", " ", self.text).strip().lower()
        digest = hashlib.sha256(f"{self.occurred_at or ''}|{normalized}".encode("utf-8")).hexdigest()
        return digest[:32]


@dataclass
class ParsedImport:
    source_format: str
    items: List[ImportItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
