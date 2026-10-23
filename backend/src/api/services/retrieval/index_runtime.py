"""Non-blocking lifecycle for the derived retrieval FAISS sidecar."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from api.dependencies import get_sqlite_knowledge_service
from api.services.retrieval.indexer import RetrievalIndexer
from api.services.retrieval.registry import build_default_retrieval_registry

logger = logging.getLogger(__name__)


@dataclass
class RetrievalIndexRuntimeStatus:
    is_running: bool = False
    last_completed_at: Optional[str] = None
    last_error: Optional[str] = None
    last_reasons: list[str] = field(default_factory=list)


class RetrievalIndexRuntime:
    def __init__(self, indexer: RetrievalIndexer) -> None:
        self._indexer = indexer
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._rerun_requested = False
        self._pending_reasons: list[str] = []
        self._status = RetrievalIndexRuntimeStatus()

    async def start(self) -> None:
        self.request_reconciliation("startup")

    async def stop(self) -> None:
        task = self._task
        if task is not None and not task.done():
            await task

    def request_reconciliation(self, reason: str) -> None:
        self._pending_reasons.append(reason)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run_reconciliations(),
                name="retrieval-index-runtime",
            )
        else:
            self._rerun_requested = True

    async def reconcile_after_narrative_pass(self) -> None:
        self.request_reconciliation("narrative_pass_complete")
        task = self._task
        if task is not None and not task.done():
            await task

    def get_status(self) -> RetrievalIndexRuntimeStatus:
        return self._status

    async def _run_reconciliations(self) -> None:
        async with self._lock:
            self._status.is_running = True
            try:
                while True:
                    reasons = list(self._pending_reasons)
                    self._pending_reasons.clear()
                    self._rerun_requested = False
                    self._status.last_reasons = reasons
                    try:
                        result = await asyncio.to_thread(self._indexer.rebuild_if_stale)
                        self._status.last_completed_at = datetime.now(timezone.utc).isoformat()
                        self._status.last_error = None
                        logger.info(
                            "Retrieval index reconciliation complete (%s): %s",
                            ", ".join(reasons) or "unspecified",
                            result,
                        )
                    except Exception as exc:
                        self._status.last_error = str(exc)[:2000]
                        logger.exception(
                            "Retrieval index reconciliation failed (%s)",
                            ", ".join(reasons) or "unspecified",
                        )
                        break
                    if not self._rerun_requested:
                        break
            finally:
                self._status.is_running = False
                self._task = None


_runtime_singleton: Optional[RetrievalIndexRuntime] = None


def get_retrieval_index_runtime() -> RetrievalIndexRuntime:
    global _runtime_singleton
    if _runtime_singleton is None:
        knowledge = get_sqlite_knowledge_service()
        registry = build_default_retrieval_registry()
        indexer = RetrievalIndexer(knowledge.db_path, registry)
        _runtime_singleton = RetrievalIndexRuntime(indexer)
    return _runtime_singleton
