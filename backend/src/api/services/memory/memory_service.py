"""Higher-level operations for Basil's working memory files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from api.services.memory.memory_store import (
    BOOTSTRAP_MEMORY_FILES,
    MEMORY_FILE_LIMITS_BYTES,
    MemoryDocument,
    MemorySearchResult,
    MemoryStore,
    get_memory_store,
)


DEFAULT_MEMORY_CONTEXT_BUDGET_TOKENS = 2500


@dataclass(frozen=True)
class MemoryAppendOutcome:
    """Result of an append-like memory operation."""

    document: MemoryDocument
    changed: bool
    reason: str


@dataclass(frozen=True)
class MemoryPromotionOutcome:
    """Result of promoting a memory entry between managed files."""

    source_document: MemoryDocument
    target_document: MemoryDocument
    changed: bool
    reason: str


@dataclass(frozen=True)
class MemoryContextSegment:
    """A prompt-facing memory segment with rough token telemetry."""

    file_name: str
    content: str
    estimated_tokens: int
    truncated: bool


@dataclass(frozen=True)
class MemoryContextBundle:
    """Priority-ordered memory content prepared for prompt injection."""

    segments: List[MemoryContextSegment]
    estimated_tokens: int


class MemoryService:
    """Application-level interface for safe working-memory operations."""

    def __init__(self, store: Optional[MemoryStore] = None) -> None:
        self.store = store or get_memory_store()

    def read_memory_file(self, file_name: str) -> MemoryDocument:
        """Read a managed memory file."""
        return self.store.read_memory_file(file_name)

    def list_memory_documents(self) -> List[MemoryDocument]:
        """List all managed working-memory files."""
        return self.store.list_memory_documents()

    def append_memory_entry(self, file_name: str, entry: str) -> MemoryAppendOutcome:
        """Append a sanitized memory entry unless it already exists."""
        sanitized_entry = self._sanitize_memory_entry(entry)
        existing_document = self.store.read_memory_file(file_name)
        if not sanitized_entry:
            return MemoryAppendOutcome(
                document=existing_document,
                changed=False,
                reason="empty_entry",
            )

        if self._contains_equivalent_entry(existing_document.content, sanitized_entry):
            return MemoryAppendOutcome(
                document=existing_document,
                changed=False,
                reason="duplicate_entry",
            )

        updated_document = self.store.append_to_memory_file(file_name, sanitized_entry)
        return MemoryAppendOutcome(
            document=updated_document,
            changed=True,
            reason="appended",
        )

    def replace_memory_file(self, file_name: str, content: str) -> MemoryDocument:
        """Replace a managed memory file with sanitized content."""
        sanitized_content = self._sanitize_memory_document(content)
        return self.store.write_memory_file(file_name, sanitized_content)

    def promote_memory_entry(
        self,
        *,
        source_file_name: str,
        target_file_name: str,
        entry: str,
    ) -> MemoryPromotionOutcome:
        """Move one matching entry from a source file into a target file."""
        sanitized_entry = self._sanitize_memory_entry(entry)
        source_document = self.store.read_memory_file(source_file_name)
        target_document = self.store.read_memory_file(target_file_name)

        if not sanitized_entry:
            return MemoryPromotionOutcome(
                source_document=source_document,
                target_document=target_document,
                changed=False,
                reason="empty_entry",
            )

        if not self._contains_equivalent_entry(source_document.content, sanitized_entry):
            return MemoryPromotionOutcome(
                source_document=source_document,
                target_document=target_document,
                changed=False,
                reason="entry_missing_from_source",
            )

        append_outcome = self.append_memory_entry(target_file_name, sanitized_entry)
        updated_source_content = self._remove_first_equivalent_entry(
            source_document.content,
            sanitized_entry,
        )
        updated_source_document = self.store.write_memory_file(
            source_file_name,
            updated_source_content,
        )
        return MemoryPromotionOutcome(
            source_document=updated_source_document,
            target_document=append_outcome.document,
            changed=True,
            reason="promoted" if append_outcome.changed else "removed_source_duplicate",
        )

    def search_memory(self, query: str, *, max_results: int = 20) -> List[MemorySearchResult]:
        """Search managed memory files and user overflow markdown files."""
        return self.store.search_memory_files(query, max_results=max_results)

    def build_memory_context_bundle(
        self,
        *,
        budget_tokens: int = DEFAULT_MEMORY_CONTEXT_BUDGET_TOKENS,
    ) -> MemoryContextBundle:
        """Build a priority-ordered prompt memory bundle within a token budget."""
        remaining_tokens = budget_tokens
        segments: List[MemoryContextSegment] = []

        for file_name in ("essentials.md", "now.md", "recent.md"):
            document = self.store.read_memory_file(file_name)
            content = document.content.strip()
            estimated_tokens = self._estimate_token_count(content)
            truncated = False

            if estimated_tokens > remaining_tokens:
                content = self._truncate_text_to_estimated_tokens(content, remaining_tokens)
                estimated_tokens = self._estimate_token_count(content)
                truncated = True

            if content:
                segments.append(
                    MemoryContextSegment(
                        file_name=file_name,
                        content=content,
                        estimated_tokens=estimated_tokens,
                        truncated=truncated,
                    )
                )
                remaining_tokens -= estimated_tokens

            if remaining_tokens <= 0:
                break

        return MemoryContextBundle(
            segments=segments,
            estimated_tokens=sum(segment.estimated_tokens for segment in segments),
        )

    def get_memory_file_caps(self) -> Dict[str, int]:
        """Return hard byte caps for managed memory files."""
        return dict(MEMORY_FILE_LIMITS_BYTES)

    def _sanitize_memory_document(self, content: str) -> str:
        sanitized_lines = [
            self._sanitize_memory_line(line)
            for line in content.replace("\x00", "").splitlines()
        ]
        return "\n".join(sanitized_lines).strip() + ("\n" if sanitized_lines else "")

    def _sanitize_memory_entry(self, entry: str) -> str:
        sanitized = self._sanitize_memory_document(entry).strip()
        return sanitized

    def _sanitize_memory_line(self, line: str) -> str:
        return re.sub(r"[ \t]+", " ", line).strip()

    def _contains_equivalent_entry(self, content: str, entry: str) -> bool:
        normalized_entry = self._normalize_for_deduplication(entry)
        return any(
            self._normalize_for_deduplication(line) == normalized_entry
            for line in content.splitlines()
        )

    def _remove_first_equivalent_entry(self, content: str, entry: str) -> str:
        normalized_entry = self._normalize_for_deduplication(entry)
        removed = False
        retained_lines: List[str] = []
        for line in content.splitlines():
            if not removed and self._normalize_for_deduplication(line) == normalized_entry:
                removed = True
                continue
            retained_lines.append(line)
        return "\n".join(retained_lines).strip() + ("\n" if retained_lines else "")

    def _normalize_for_deduplication(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    def _estimate_token_count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def _truncate_text_to_estimated_tokens(self, text: str, budget_tokens: int) -> str:
        if budget_tokens <= 0:
            return ""
        target_chars = budget_tokens * 4
        if len(text) <= target_chars:
            return text
        return text[:target_chars].rstrip()


_memory_service_singleton: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """Return the process-wide working-memory service."""
    global _memory_service_singleton
    if _memory_service_singleton is None:
        _memory_service_singleton = MemoryService()
    return _memory_service_singleton
