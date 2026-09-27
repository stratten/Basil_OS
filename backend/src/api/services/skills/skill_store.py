"""Filesystem store for Basil's user-approved reusable skills."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from api.core.config.api_settings import settings


SKILL_BODY_CAP_BYTES = 2 * 1024
SKILL_FILE_NAME = "SKILL.md"
SKILL_NOTES_FILE_NAME = "notes.md"
SKILL_METADATA_FILE_NAME = "metadata.json"


class SkillStoreError(Exception):
    """Base exception for skill storage failures."""


class SkillNotFoundError(SkillStoreError):
    """Raised when a skill slug does not exist."""


class SkillBackpressureError(SkillStoreError):
    """Raised when a skill body exceeds the SKILL.md cap."""

    def __init__(self, slug: str, cap_bytes: int, attempted_bytes: int) -> None:
        super().__init__(
            f"{slug}/{SKILL_FILE_NAME} would exceed its {cap_bytes} byte cap "
            f"({attempted_bytes} bytes attempted)."
        )
        self.slug = slug
        self.cap_bytes = cap_bytes
        self.attempted_bytes = attempted_bytes


@dataclass(frozen=True)
class SkillRecord:
    slug: str
    body: str
    metadata: Dict[str, Any]
    path: Path
    size_bytes: int
    cap_bytes: int = SKILL_BODY_CAP_BYTES


@dataclass(frozen=True)
class SkillCatalogEntry:
    """Metadata-only skill catalog row used for prompt availability."""

    slug: str
    title: str
    when_to_use: str
    triggers: List[str]
    size_bytes: int
    updated_at: str
    last_used: Optional[str]
    observation_count: int
    version: int


class SkillStore:
    """Low-level folder store for user-approved skill procedures."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self.skills_dir = skills_dir or settings.STORAGE_DIR / "memory" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._catalog_cache_signature: Optional[Tuple[int, Tuple[Tuple[str, int], ...]]] = None
        self._catalog_cache_records: List[SkillCatalogEntry] = []

    def generate_skill_slug(self, title: str) -> str:
        """Generate a stable-ish filesystem-safe skill slug from a title."""
        return self._generate_skill_slug_unlocked(title)

    def save_new_skill_once(
        self,
        *,
        title: str,
        body: str,
        metadata: Dict[str, Any],
        creation_origin_key: str,
        notes: Optional[str] = None,
    ) -> Tuple[SkillRecord, bool]:
        """Create a skill once for a durable origin key."""
        with self._exclusive_lock():
            existing = self.find_skill_by_creation_origin_key(creation_origin_key)
            if existing is not None:
                return existing, False
            slug = self._generate_skill_slug_unlocked(title)
            return (
                self._save_skill_unlocked(
                    slug=slug,
                    body=body,
                    metadata={**metadata, "creation_origin_key": creation_origin_key},
                    notes=notes,
                ),
                True,
            )

    def find_skill_by_creation_origin_key(self, creation_origin_key: str) -> Optional[SkillRecord]:
        """Return the skill previously created for one durable origin key."""
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir() or not (skill_dir / SKILL_METADATA_FILE_NAME).exists():
                continue
            metadata = self._read_metadata(skill_dir.name)
            if metadata.get("creation_origin_key") == creation_origin_key:
                return self.read_skill(skill_dir.name)
        return None

    def _generate_skill_slug_unlocked(self, title: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        if not base:
            base = "skill"
        candidate = base
        suffix = 2
        while self._skill_dir(candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def save_skill(
        self,
        *,
        slug: str,
        body: str,
        metadata: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> SkillRecord:
        """Create or replace a skill after enforcing the SKILL.md body cap."""
        with self._exclusive_lock():
            return self._save_skill_unlocked(
                slug=slug,
                body=body,
                metadata=metadata,
                notes=notes,
            )

    def _save_skill_unlocked(
        self,
        *,
        slug: str,
        body: str,
        metadata: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> SkillRecord:
        safe_slug = self._sanitize_slug(slug)
        encoded_size = len(body.encode("utf-8"))
        if encoded_size > SKILL_BODY_CAP_BYTES:
            raise SkillBackpressureError(safe_slug, SKILL_BODY_CAP_BYTES, encoded_size)

        skill_dir = self._skill_dir(safe_slug)
        skill_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        existing_metadata = self._read_metadata(safe_slug) if skill_dir.exists() else {}
        next_metadata = {
            **existing_metadata,
            **(metadata or {}),
            "slug": safe_slug,
            "updated_at": now,
            "created_at": existing_metadata.get("created_at") or now,
        }
        self._write_file_atomic(skill_dir / SKILL_FILE_NAME, body.strip() + "\n")
        self._write_json_atomic(skill_dir / SKILL_METADATA_FILE_NAME, next_metadata)
        if notes is not None:
            self._write_file_atomic(skill_dir / SKILL_NOTES_FILE_NAME, notes.strip() + "\n")
        self._invalidate_catalog_cache()
        return self.read_skill(safe_slug)

    def read_skill(self, slug: str) -> SkillRecord:
        """Read a saved skill by slug."""
        safe_slug = self._sanitize_slug(slug)
        skill_dir = self._skill_dir(safe_slug)
        skill_path = skill_dir / SKILL_FILE_NAME
        if not skill_path.exists():
            raise SkillNotFoundError(f"Skill '{safe_slug}' was not found.")
        body = skill_path.read_text(encoding="utf-8")
        return SkillRecord(
            slug=safe_slug,
            body=body,
            metadata=self._read_metadata(safe_slug),
            path=skill_path,
            size_bytes=len(body.encode("utf-8")),
        )

    def list_skills(self) -> List[SkillRecord]:
        """Enumerate saved skills sorted by most recently updated."""
        records: List[SkillRecord] = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if skill_dir.is_dir() and (skill_dir / SKILL_FILE_NAME).exists():
                records.append(self.read_skill(skill_dir.name))
        return sorted(
            records,
            key=lambda record: str(record.metadata.get("updated_at", "")),
            reverse=True,
        )

    def list_skill_catalog_entries(self) -> List[SkillCatalogEntry]:
        """Enumerate saved skills using metadata only, without reading SKILL.md."""
        signature = self._catalog_signature()
        if (
            self._catalog_cache_signature == signature
            and self._catalog_cache_records is not None
        ):
            return list(self._catalog_cache_records)

        entries: List[SkillCatalogEntry] = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir() or not (skill_dir / SKILL_FILE_NAME).exists():
                continue
            metadata = self._read_metadata(skill_dir.name)
            if not metadata:
                continue
            triggers = [
                str(trigger)
                for trigger in metadata.get("triggers", [])
                if isinstance(trigger, str)
            ]
            entries.append(
                SkillCatalogEntry(
                    slug=str(metadata.get("slug") or skill_dir.name),
                    title=str(metadata.get("title") or skill_dir.name),
                    when_to_use=str(metadata.get("when_to_use") or "Use when relevant."),
                    triggers=triggers,
                    size_bytes=(skill_dir / SKILL_FILE_NAME).stat().st_size
                    if (skill_dir / SKILL_FILE_NAME).exists()
                    else 0,
                    updated_at=str(metadata.get("updated_at") or ""),
                    last_used=(
                        str(metadata.get("last_used"))
                        if metadata.get("last_used") is not None
                        else None
                    ),
                    observation_count=int(
                        metadata.get("observation_count")
                        or len(metadata.get("source_task_ids") or [])
                        or 1
                    ),
                    version=int(metadata.get("version") or 1),
                )
            )

        records = sorted(entries, key=lambda entry: entry.updated_at, reverse=True)
        self._catalog_cache_signature = signature
        self._catalog_cache_records = records
        return list(records)

    def delete_skill(self, slug: str) -> bool:
        """Delete a saved skill folder."""
        with self._exclusive_lock():
            safe_slug = self._sanitize_slug(slug)
            skill_dir = self._skill_dir(safe_slug)
            if not skill_dir.exists():
                return False
            for path in skill_dir.iterdir():
                if path.is_file():
                    path.unlink()
            skill_dir.rmdir()
            self._invalidate_catalog_cache()
            return True

    def update_skill_metadata(self, slug: str, updates: Dict[str, Any]) -> SkillRecord:
        """Merge metadata updates for a saved skill."""
        with self._exclusive_lock():
            safe_slug = self._sanitize_slug(slug)
            self.read_skill(safe_slug)
            metadata = self._read_metadata(safe_slug)
            metadata.update(updates)
            metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_json_atomic(self._skill_dir(safe_slug) / SKILL_METADATA_FILE_NAME, metadata)
            self._invalidate_catalog_cache()
            return self.read_skill(safe_slug)

    def _skill_dir(self, slug: str) -> Path:
        return self.skills_dir / self._sanitize_slug(slug)

    def _sanitize_slug(self, slug: str) -> str:
        safe_slug = re.sub(r"[^a-z0-9-]+", "-", slug.casefold()).strip("-")
        if not safe_slug or safe_slug in {".", ".."}:
            raise ValueError("Skill slug must contain at least one alphanumeric character.")
        return safe_slug

    def _read_metadata(self, slug: str) -> Dict[str, Any]:
        metadata_path = self._skill_dir(slug) / SKILL_METADATA_FILE_NAME
        if not metadata_path.exists():
            return {}
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _catalog_signature(self) -> Tuple[int, Tuple[Tuple[str, int], ...]]:
        directory_mtime = self.skills_dir.stat().st_mtime_ns if self.skills_dir.exists() else 0
        metadata_mtimes: List[Tuple[str, int]] = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            metadata_path = skill_dir / SKILL_METADATA_FILE_NAME
            metadata_mtimes.append(
                (
                    skill_dir.name,
                    metadata_path.stat().st_mtime_ns if metadata_path.exists() else 0,
                )
            )
        return directory_mtime, tuple(metadata_mtimes)

    def _invalidate_catalog_cache(self) -> None:
        self._catalog_cache_signature = None
        self._catalog_cache_records = []

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        lock_path = self.skills_dir / ".skill-store.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        self._write_file_atomic(path, json.dumps(payload, indent=2, sort_keys=True))

    def _write_file_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary = Path(temporary_path)
            if temporary.exists():
                temporary.unlink()


_skill_store_singleton: Optional[SkillStore] = None


def get_skill_store() -> SkillStore:
    """Return the process-wide skill store."""
    global _skill_store_singleton
    if _skill_store_singleton is None:
        _skill_store_singleton = SkillStore()
    return _skill_store_singleton
