"""The evidence ledger: every excerpt a tool shows the investigator gets an id, and only ids the ledger knows can be cited."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Optional, Tuple

from ..models import FileCitation
from .models import MAX_EVIDENCE_ENTRIES, MAX_EXCERPT_CHARS

EvidenceKind = Literal["file", "record"]


@dataclass(frozen=True)
class EvidenceEntry:
    id: str
    kind: EvidenceKind
    path: str
    line_start: int
    line_end: int
    excerpt: str


def record_path(source_kind: str, source_id: str) -> str:
    """The citation path used for a Basil record, for example ``basil:meeting:2026-01-01_x``."""
    return f"basil:{source_kind}:{source_id}"


class EvidenceLedger:
    def __init__(self, max_entries: int = MAX_EVIDENCE_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: List[EvidenceEntry] = []
        self._by_key: Dict[Tuple[str, int, int], EvidenceEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, kind: EvidenceKind, path: str, line_start: int, line_end: int, excerpt: str) -> Optional[EvidenceEntry]:
        """Record an excerpt; the same location returns the existing entry and a full ledger returns ``None``."""
        key = (path, line_start, line_end)
        existing = self._by_key.get(key)
        if existing is not None:
            return existing
        if len(self._entries) >= self._max_entries:
            return None
        entry = EvidenceEntry(
            id=f"e{len(self._entries) + 1}",
            kind=kind,
            path=path,
            line_start=line_start,
            line_end=line_end,
            excerpt=excerpt[:MAX_EXCERPT_CHARS],
        )
        self._entries.append(entry)
        self._by_key[key] = entry
        return entry

    def entries(self) -> List[EvidenceEntry]:
        return list(self._entries)

    def get(self, evidence_id: str) -> Optional[EvidenceEntry]:
        return next((entry for entry in self._entries if entry.id == evidence_id), None)

    def render(self, max_chars: int) -> str:
        """Prompt text for the conclusion call; whole entries only."""
        blocks: List[str] = []
        used = 0
        for entry in self._entries:
            safe_text = entry.excerpt.replace("</evidence", "<\\/evidence")
            block = f'<evidence id="{entry.id}" path="{entry.path}" lines="{entry.line_start}-{entry.line_end}">\n{safe_text}\n</evidence>'
            if blocks and used + len(block) > max_chars:
                break
            if not blocks and len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block) + 1
        return "\n".join(blocks)

    def citations(self, evidence_ids: Iterable[str]) -> List[FileCitation]:
        """Resolve model-chosen ids into citations; unknown and repeated ids are dropped."""
        resolved: List[FileCitation] = []
        seen = set()
        for raw in evidence_ids:
            entry = self.get(str(raw).strip())
            if entry is None or entry.id in seen:
                continue
            seen.add(entry.id)
            resolved.append(FileCitation(path=entry.path, line_start=entry.line_start, line_end=entry.line_end, excerpt=entry.excerpt[:240]))
        return resolved
