"""Application-level service for saved Basil skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.services.memory.proposal_store import union_preserving_order
from api.services.skills.skill_store import (
    SkillNotFoundError,
    SkillRecord,
    SkillStore,
    get_skill_store,
)


@dataclass(frozen=True)
class SkillSearchResult:
    slug: str
    title: str
    when_to_use: str
    triggers: List[str]
    score: int


class SkillService:
    """High-level API for saving, loading, and discovering reusable skills."""

    def __init__(self, store: Optional[SkillStore] = None) -> None:
        self.store = store or get_skill_store()

    def save_skill(
        self,
        *,
        title: str,
        body: str,
        when_to_use: str,
        triggers: Optional[List[str]] = None,
        source_task_ids: Optional[List[str]] = None,
        slug: Optional[str] = None,
        notes: Optional[str] = None,
        creation_origin_key: Optional[str] = None,
    ) -> SkillRecord:
        """Save or update a user-approved markdown skill.

        Enhancement-aware: when ``slug`` refers to an existing skill the incoming
        ``source_task_ids`` are unioned with the stored set (so the observation
        counter never drops), ``observation_count`` is recomputed as the distinct
        count, and ``version`` is bumped only when the body actually changes.
        Accumulated ``last_used``/``success_count``/``load_count`` are preserved
        (they merge through from existing metadata since we do not overwrite
        them). New skills start at ``version`` 1.
        """
        if slug is None and creation_origin_key is not None:
            normalized_sources = union_preserving_order(None, list(source_task_ids or []))
            return self.store.save_new_skill_once(
                title=title.strip() or "skill",
                body=body,
                metadata={
                    "title": title.strip() or "skill",
                    "when_to_use": when_to_use.strip(),
                    "triggers": [trigger.strip() for trigger in (triggers or []) if trigger.strip()],
                    "source_task_ids": normalized_sources,
                    "observation_count": len(normalized_sources),
                    "version": 1,
                    "last_used": None,
                    "success_count": 0,
                },
                creation_origin_key=creation_origin_key,
                notes=notes,
            )[0]

        if slug:
            with self.store._exclusive_lock():
                try:
                    existing = self.store.read_skill(slug)
                except SkillNotFoundError:
                    existing = None
                metadata: Dict[str, Any] = {
                    "title": title.strip() or slug,
                    "when_to_use": when_to_use.strip(),
                    "triggers": [trigger.strip() for trigger in (triggers or []) if trigger.strip()],
                }
                if existing is not None:
                    merged_sources = union_preserving_order(
                        [str(task_id) for task_id in existing.metadata.get("source_task_ids", []) if task_id],
                        list(source_task_ids or []),
                    )
                    body_changed = body.strip() != existing.body.strip()
                    current_version = int(existing.metadata.get("version") or 1)
                    metadata["source_task_ids"] = merged_sources
                    metadata["observation_count"] = len(merged_sources)
                    metadata["version"] = current_version + (1 if body_changed else 0)
                else:
                    normalized_sources = union_preserving_order(None, list(source_task_ids or []))
                    metadata["source_task_ids"] = normalized_sources
                    metadata["observation_count"] = len(normalized_sources)
                    metadata["version"] = 1
                    metadata["last_used"] = None
                    metadata["success_count"] = 0
                return self.store._save_skill_unlocked(
                    slug=slug,
                    body=body,
                    metadata=metadata,
                    notes=notes,
                )

        skill_slug = self.store.generate_skill_slug(title)
        metadata: Dict[str, Any] = {
            "title": title.strip() or skill_slug,
            "when_to_use": when_to_use.strip(),
            "triggers": [trigger.strip() for trigger in (triggers or []) if trigger.strip()],
        }
        normalized_sources = union_preserving_order(None, list(source_task_ids or []))
        metadata["source_task_ids"] = normalized_sources
        metadata["observation_count"] = len(normalized_sources)
        metadata["version"] = 1
        metadata["last_used"] = None
        metadata["success_count"] = 0

        return self.store.save_skill(
            slug=skill_slug,
            body=body,
            metadata=metadata,
            notes=notes,
        )

    def record_skill_observation(
        self,
        slug: str,
        *,
        source_task_ids: Optional[List[str]] = None,
    ) -> SkillRecord:
        """Register a new observation of a saved skill without changing content.

        Unions the observing task ids into the skill's ``source_task_ids`` and
        recomputes ``observation_count``. The body and ``version`` are left
        untouched (this reflects a recurrence sighting, not a content edit). The
        union makes this idempotent: re-observing the same task is a no-op.
        """
        record = self.store.read_skill(slug)
        merged_sources = union_preserving_order(
            [str(task_id) for task_id in record.metadata.get("source_task_ids", []) if task_id],
            list(source_task_ids or []),
        )
        return self.store.update_skill_metadata(
            slug,
            {
                "source_task_ids": merged_sources,
                "observation_count": len(merged_sources),
            },
        )

    def load_skill(self, slug: str, *, mark_used: bool = True) -> SkillRecord:
        """Load a skill body and optionally update usage metadata."""
        record = self.store.read_skill(slug)
        if mark_used:
            return self.store.update_skill_metadata(
                slug,
                {
                    "last_used": datetime.now(timezone.utc).isoformat(),
                    "load_count": int(record.metadata.get("load_count") or 0) + 1,
                },
            )
        return record

    def list_skills(self) -> List[SkillRecord]:
        """List all saved skills."""
        return self.store.list_skills()

    def delete_skill(self, slug: str) -> bool:
        """Delete a saved skill."""
        return self.store.delete_skill(slug)

    def search_skills(self, query: str, *, max_results: int = 10) -> List[SkillSearchResult]:
        """Search saved skills by slug, title, triggers, and body text."""
        normalized_terms = self._terms(query)
        if not normalized_terms:
            return []

        results: List[SkillSearchResult] = []
        for record in self.store.list_skills():
            title = str(record.metadata.get("title") or record.slug)
            when_to_use = str(record.metadata.get("when_to_use") or "")
            triggers = [
                str(trigger)
                for trigger in record.metadata.get("triggers", [])
                if isinstance(trigger, str)
            ]
            searchable_text = " ".join([record.slug, title, when_to_use, *triggers, record.body]).casefold()
            score = sum(searchable_text.count(term) for term in normalized_terms)
            if score > 0:
                results.append(
                    SkillSearchResult(
                        slug=record.slug,
                        title=title,
                        when_to_use=when_to_use,
                        triggers=triggers,
                        score=score,
                    )
                )

        return sorted(results, key=lambda result: result.score, reverse=True)[:max_results]

    def list_catalog_entries(self):
        """Return metadata-only catalog entries (slug, title, when_to_use, triggers)."""
        return self.store.list_skill_catalog_entries()

    def build_skill_catalog_lines(self) -> List[str]:
        """Build compact catalog lines for system-prompt availability."""
        lines: List[str] = []
        for record in self.store.list_skill_catalog_entries():
            lines.append(f"- {record.slug}: {record.title} — {record.when_to_use}")
        return lines

    def record_skill_success(self, slug: str) -> SkillRecord:
        """Increment a saved skill's success counter."""
        record = self.store.read_skill(slug)
        return self.store.update_skill_metadata(
            slug,
            {"success_count": int(record.metadata.get("success_count") or 0) + 1},
        )

    def _terms(self, query: str) -> List[str]:
        return [
            term.casefold()
            for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", query)
            if len(term) > 1
        ]


_skill_service_singleton: Optional[SkillService] = None


def get_skill_service() -> SkillService:
    """Return the process-wide skill service."""
    global _skill_service_singleton
    if _skill_service_singleton is None:
        _skill_service_singleton = SkillService()
    return _skill_service_singleton
