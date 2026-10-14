"""Result type for context retrieval, with prompt rendering and citation resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .models import FileCitation

CITATION_EXCERPT_CHARS = 240


@dataclass(frozen=True)
class ContextExcerpt:
    id: str
    root_id: str
    path: str
    line_start: int
    line_end: int
    text: str
    score: float


@dataclass
class ContextPack:
    excerpts: List[ContextExcerpt] = field(default_factory=list)
    queries: List[str] = field(default_factory=list)
    scanned_files: int = 0
    duration_ms: int = 0
    budget_exhausted: bool = False

    @property
    def hit_count(self) -> int:
        return len(self.excerpts)

    @property
    def is_empty(self) -> bool:
        return not self.excerpts

    def paths(self) -> List[str]:
        seen: Dict[str, None] = {}
        for excerpt in self.excerpts:
            seen.setdefault(excerpt.path, None)
        return list(seen)

    def by_id(self) -> Dict[str, ContextExcerpt]:
        return {excerpt.id: excerpt for excerpt in self.excerpts}

    def render(self, max_chars: int) -> str:
        """Prompt text for the pack; whole excerpts only, never cut mid-excerpt."""
        blocks: List[str] = []
        used = 0
        for excerpt in self.excerpts:
            safe_text = excerpt.text.replace("</excerpt", "<\\/excerpt")
            block = (
                f'<excerpt id="{excerpt.id}" path="{excerpt.path}" lines="{excerpt.line_start}-{excerpt.line_end}">\n'
                f"{safe_text}\n</excerpt>"
            )
            if blocks and used + len(block) > max_chars:
                break
            if not blocks and len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block) + 1
        return "\n".join(blocks)

    def citations(self, ids: Iterable[str]) -> List[FileCitation]:
        """Resolve excerpt ids chosen by the model into citations; unknown ids are dropped."""
        lookup = self.by_id()
        resolved: List[FileCitation] = []
        seen = set()
        for excerpt_id in ids:
            excerpt = lookup.get(str(excerpt_id))
            if excerpt is None or excerpt.id in seen:
                continue
            seen.add(excerpt.id)
            resolved.append(
                FileCitation(
                    path=excerpt.path,
                    line_start=excerpt.line_start,
                    line_end=excerpt.line_end,
                    excerpt=excerpt.text[:CITATION_EXCERPT_CHARS],
                )
            )
        return resolved
