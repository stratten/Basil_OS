"""The one import service behind both Settings and the setup assistant.

Review is by batch: preview parses and counts, and nothing is written until commit names the categories to keep. Dated and undated items become final zettel entries tagged with an import batch id, so a whole import can be undone. Stable facts are not written directly. They are queued as memory-file proposals so the user still approves each one in Pending Memory Proposals.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .chunking import clean_text, split_into_chunks
from .jobs import STAGE_LOADING, ImportJob, ImportJobs
from .model_access import ImportModelLike
from .models import (
    CATEGORIES,
    CATEGORY_STABLE_FACT,
    MAX_IMPORT_CHARS,
    ImportEmptyError,
    ImportItem,
    ImportTooLargeError,
    ParsedImport,
)
from .profile import ProfileDraft, build_profile_draft
from .profile_store import PROFILE_FILES, restore_profile, write_profile
from .store import BatchSummary, list_batches, undo_batch, write_items
from .structuring import ImportModelError, structure_import

logger = logging.getLogger(__name__)

# Loads the reasoning model an import reads with. Settings and setup pass different loaders, so one service serves both.
ModelLoader = Callable[[], Awaitable[ImportModelLike]]

PREVIEW_TTL_SECONDS = 3600
MAX_CACHED_PREVIEWS = 8
SAMPLES_PER_CATEGORY = 5
STABLE_FACT_TARGET_FILE = "user.md"
LABEL_MAX_CHARS = 80


class PreviewExpiredError(LookupError):
    """The preview is gone, either because it expired or because the backend restarted."""


class UnknownBatchError(LookupError):
    """No import batch has that id."""


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


class ContextImportService:
    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any],
        proposal_store_factory: Callable[[], Any],
        memory_service_factory: Callable[[], Any],
        clock: Callable[[], float] = time.monotonic,
        jobs: Optional[ImportJobs] = None,
        backup_dir: Optional[Path] = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._proposal_store_factory = proposal_store_factory
        self._memory_service_factory = memory_service_factory
        self._clock = clock
        self._previews: "OrderedDict[str, tuple[float, str, ParsedImport]]" = OrderedDict()
        self._profile_drafts: "OrderedDict[str, tuple[float, str, Dict[str, Any]]]" = OrderedDict()
        self._jobs = jobs or ImportJobs(clock=clock)
        self._backup_dir = backup_dir
        self._lock = threading.Lock()

    @property
    def jobs(self) -> ImportJobs:
        return self._jobs

    @staticmethod
    def _validated_text(text: str) -> str:
        cleaned = clean_text(text)
        if not cleaned:
            raise ImportEmptyError("There is nothing to import. Paste some text or choose a file.")
        if len(cleaned) > MAX_IMPORT_CHARS:
            raise ImportTooLargeError(
                f"That text is {len(cleaned):,} characters, and one import can be up to {MAX_IMPORT_CHARS:,}. Split it and import the parts one at a time."
            )
        return cleaned

    async def _load_model_for(self, job: ImportJob, load_model: ModelLoader) -> ImportModelLike:
        """Load the model for ``job``, saying so while a large one loads, and let the model report its writing progress to the job."""
        job.set_stage(STAGE_LOADING, "Getting the model ready.")
        model = await self._load_model(load_model)
        if hasattr(model, "on_activity"):
            model.on_activity = job.note_activity
        if hasattr(model, "on_thinking"):
            model.on_thinking = job.note_thinking
        return model

    @staticmethod
    async def _load_model(load_model: ModelLoader) -> ImportModelLike:
        try:
            return await load_model()
        except Exception as exc:
            logger.warning("Could not load the model for a context import: %s", exc)
            raise ImportModelError("I couldn't start the model for this import. Check that it is downloaded or that your account or key works, then try again.") from exc

    def start_records_job(self, text: str, filename: str, label: str, load_model: ModelLoader) -> Dict[str, Any]:
        """Start reading ``text`` into memory records. The finished job's result is the same preview ``commit`` takes."""
        cleaned = self._validated_text(text)
        total = len(split_into_chunks(cleaned))

        async def run(job: ImportJob) -> Dict[str, Any]:
            model = await self._load_model_for(job, load_model)
            parsed = await structure_import(model, cleaned, on_progress=job.report, is_canceled=job.is_canceled)
            return self.register_preview(parsed, filename, label)

        job = self._jobs.start("records", " ".join((label or filename or "Pasted text").split())[:LABEL_MAX_CHARS], total, run)
        return {"job_id": job.job_id, "chunks_total": total}

    def start_profile_job(self, text: str, filename: str, label: str, load_model: ModelLoader) -> Dict[str, Any]:
        """Start reading ``text`` into a reviewable rewrite of essentials.md and user.md. Nothing is written until ``commit_profile``."""
        from api.services.memory.memory_store import MEMORY_FILE_LIMITS_BYTES

        cleaned = self._validated_text(text)
        total = len(split_into_chunks(cleaned))
        clean_label = " ".join((label or filename or "Pasted text").split())[:LABEL_MAX_CHARS]
        caps = {name: MEMORY_FILE_LIMITS_BYTES[name] for name in PROFILE_FILES}

        async def run(job: ImportJob) -> Dict[str, Any]:
            model = await self._load_model_for(job, load_model)
            memory = self._memory_service_factory()
            essentials = memory.read_memory_file("essentials.md").content
            user = memory.read_memory_file("user.md").content
            draft = await build_profile_draft(
                model,
                cleaned,
                current_essentials=essentials,
                current_user=user,
                essentials_cap=caps["essentials.md"],
                user_cap=caps["user.md"],
                on_progress=job.report,
                is_canceled=job.is_canceled,
            )
            return self._register_profile_draft(clean_label, draft, {"essentials.md": essentials, "user.md": user}, caps)

        job = self._jobs.start("profile", clean_label, total, run)
        return {"job_id": job.job_id, "chunks_total": total}

    def _register_profile_draft(self, label: str, draft: ProfileDraft, current: Dict[str, str], caps: Dict[str, int]) -> Dict[str, Any]:
        draft_id = f"draft-{uuid.uuid4().hex[:12]}"
        payload = {
            "draft_id": draft_id,
            "label": label,
            "summary": draft.summary,
            "files": [
                {"name": "essentials.md", "current": current["essentials.md"], "proposed": draft.essentials_md, "cap_bytes": caps["essentials.md"]},
                {"name": "user.md", "current": current["user.md"], "proposed": draft.user_md, "cap_bytes": caps["user.md"]},
            ],
            "warnings": draft.warnings,
        }
        with self._lock:
            self._evict_expired()
            self._profile_drafts[draft_id] = (self._clock(), label, payload)
            while len(self._profile_drafts) > MAX_CACHED_PREVIEWS:
                self._profile_drafts.popitem(last=False)
        return payload

    def commit_profile(self, draft_id: str, essentials_md: str, user_md: str) -> Dict[str, Any]:
        """Write the person's reviewed text into essentials.md and user.md. A blank file text leaves that file unchanged."""
        from api.services.memory.memory_store import MEMORY_FILE_LIMITS_BYTES

        with self._lock:
            self._evict_expired()
            entry = self._profile_drafts.get(draft_id)
        if entry is None:
            raise PreviewExpiredError("This profile draft has expired. Choose the file or paste the text again.")
        _, label, _payload = entry
        result = write_profile(
            self._memory_service_factory(),
            self._backup_directory(),
            label=label,
            new_contents={"essentials.md": essentials_md, "user.md": user_md},
            caps={name: MEMORY_FILE_LIMITS_BYTES[name] for name in PROFILE_FILES},
        )
        with self._lock:
            self._profile_drafts.pop(draft_id, None)
        return result

    def undo_profile(self, backup_id: str) -> Dict[str, Any]:
        """Put essentials.md and user.md back the way they were before one profile import."""
        return restore_profile(self._memory_service_factory(), self._backup_directory(), backup_id)

    def _backup_directory(self) -> Path:
        if self._backup_dir is not None:
            return self._backup_dir
        from api.core.config.api_settings import settings

        return settings.STORAGE_DIR / "memory" / "import_backups"

    def register_preview(self, parsed: ParsedImport, filename: str = "", label: str = "") -> Dict[str, Any]:
        clean_label = " ".join((label or filename or "Pasted text").split())[:LABEL_MAX_CHARS]
        preview_id = f"preview-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._evict_expired()
            self._previews[preview_id] = (self._clock(), clean_label, parsed)
            while len(self._previews) > MAX_CACHED_PREVIEWS:
                self._previews.popitem(last=False)
        return self._preview_payload(preview_id, clean_label, parsed)

    def commit(self, preview_id: str, categories: Sequence[str]) -> Dict[str, Any]:
        chosen = list(dict.fromkeys(categories))
        unknown = [category for category in chosen if category not in CATEGORIES]
        if unknown:
            raise ValueError(f"Unknown categories: {', '.join(unknown)}.")
        with self._lock:
            self._evict_expired()
            entry = self._previews.get(preview_id)
        if entry is None:
            raise PreviewExpiredError("This import preview has expired. Choose the file or paste the text again.")
        _, label, parsed = entry
        selected = [item for item in parsed.items if item.category in chosen]
        batch_id = f"import-{uuid.uuid4().hex[:12]}"
        stream_items = [item for item in selected if item.category != CATEGORY_STABLE_FACT]
        fact_items = [item for item in selected if item.category == CATEGORY_STABLE_FACT]

        written = {"added": 0, "already_present": 0}
        if stream_items:
            with self._connection_factory() as conn:
                written = write_items(conn, batch_id=batch_id, label=label, items=stream_items)
                conn.commit()
        proposals = self._queue_stable_facts(fact_items, label)
        with self._lock:
            self._previews.pop(preview_id, None)
        return {
            "batch_id": batch_id if written["added"] else None,
            "label": label,
            "entries_added": written["added"],
            "entries_already_present": written["already_present"],
            "proposals_queued": proposals["queued"],
            "proposals_already_known": proposals["already_known"],
            "memory_file_warning": proposals["warning"],
        }

    def list_batches(self) -> List[Dict[str, Any]]:
        with self._connection_factory() as conn:
            batches: List[BatchSummary] = list_batches(conn)
        return [
            {"batch_id": batch.batch_id, "imported_at": batch.imported_at, "label": batch.label, "entry_count": batch.entry_count}
            for batch in batches
        ]

    def undo(self, batch_id: str) -> Dict[str, Any]:
        with self._connection_factory() as conn:
            removed = undo_batch(conn, batch_id)
            conn.commit()
        if removed == 0:
            raise UnknownBatchError("That import was not found. It may already have been undone.")
        return {"batch_id": batch_id, "entries_removed": removed}

    def _evict_expired(self) -> None:
        now = self._clock()
        for key in [key for key, (created, _, _) in self._previews.items() if now - created > PREVIEW_TTL_SECONDS]:
            self._previews.pop(key, None)
        for key in [key for key, (created, _, _) in self._profile_drafts.items() if now - created > PREVIEW_TTL_SECONDS]:
            self._profile_drafts.pop(key, None)

    def _preview_payload(self, preview_id: str, label: str, parsed: ParsedImport) -> Dict[str, Any]:
        counts = {category: 0 for category in CATEGORIES}
        samples: Dict[str, List[Dict[str, Optional[str]]]] = {category: [] for category in CATEGORIES}
        dates: List[str] = []
        for item in parsed.items:
            counts[item.category] += 1
            if item.occurred_at:
                dates.append(item.occurred_at)
            if len(samples[item.category]) < SAMPLES_PER_CATEGORY:
                samples[item.category].append({"title": item.title, "text": item.text[:300], "occurred_at": item.occurred_at, "section": item.section})
        return {
            "preview_id": preview_id,
            "label": label,
            "source_format": parsed.source_format,
            "total": len(parsed.items),
            "counts": counts,
            "samples": samples,
            "earliest": min(dates) if dates else None,
            "latest": max(dates) if dates else None,
            "warnings": parsed.warnings,
        }

    def _queue_stable_facts(self, facts: Sequence[ImportItem], label: str) -> Dict[str, Any]:
        if not facts:
            return {"queued": 0, "already_known": 0, "warning": None}
        from api.services.memory.memory_evaluator import MemoryProposal
        from api.services.memory.memory_store import MEMORY_FILE_LIMITS_BYTES

        memory = self._memory_service_factory()
        store = self._proposal_store_factory()
        known = {_normalize(memory.read_memory_file(name).content) for name in (STABLE_FACT_TARGET_FILE, "essentials.md")}
        known_text = " ".join(known)
        pending = {_normalize(record.entry) for record in store.list_pending_memory_proposals()}
        fresh: List[ImportItem] = []
        seen: set[str] = set()
        for fact in facts:
            normalized = _normalize(fact.text)
            if not normalized or normalized in seen or normalized in pending or normalized in known_text:
                continue
            seen.add(normalized)
            fresh.append(fact)
        proposals = [
            MemoryProposal(target_file=STABLE_FACT_TARGET_FILE, observation=fact.text, why=f"Imported from {label}.", confidence="high")
            for fact in fresh
        ]
        if proposals:
            store.enqueue_memory_proposals(proposals, source="import")
        warning = None
        cap = MEMORY_FILE_LIMITS_BYTES.get(STABLE_FACT_TARGET_FILE)
        if cap and fresh:
            current = memory.read_memory_file(STABLE_FACT_TARGET_FILE).size_bytes
            incoming = sum(len(fact.text.encode("utf-8")) + 3 for fact in fresh)
            if current + incoming > cap:
                warning = (
                    f"{STABLE_FACT_TARGET_FILE} holds about {cap // 1024} KB and has {max(cap - current, 0)} bytes free, but these {len(fresh)} facts need about {incoming}. "
                    "Approve the ones that matter most, or edit and shorten them. The rest stay available as searchable history if you import them as notes instead."
                )
        return {"queued": len(proposals), "already_known": len(facts) - len(fresh), "warning": warning}


_service: Optional[ContextImportService] = None


def get_context_import_service() -> ContextImportService:
    global _service
    if _service is None:
        from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
            get_sync_connection,
        )
        from api.dependencies import get_sqlite_knowledge_service
        from api.services.memory.memory_service import get_memory_service
        from api.services.memory.proposal_store import get_proposal_store

        _service = ContextImportService(
            connection_factory=lambda: get_sync_connection(get_sqlite_knowledge_service().db_path, operation_name="context_import"),
            proposal_store_factory=get_proposal_store,
            memory_service_factory=get_memory_service,
        )
    return _service
