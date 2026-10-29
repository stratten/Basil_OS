"""Cascade deletion for activity-capture records and derived screen data."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)

logger = logging.getLogger(__name__)

_MAX_ERROR_LEN = 500
_MAX_ERROR_ITEMS = 20

_CAPTURE_SELECT = """
SELECT a.id, a.timestamp, a.zettel_id, path.value AS screenshot_path
FROM activities a
JOIN activity_metadata marker
  ON marker.activity_id = a.id AND marker.key = 'automatic_capture'
LEFT JOIN activity_metadata path
  ON path.activity_id = a.id AND path.key = 'screenshot_path'
"""


@dataclass(frozen=True)
class ActivityCaptureDeletionResult:
    activity_rows_deleted: int = 0
    zettel_rows_deleted: int = 0
    files_deleted: int = 0
    bytes_freed: int = 0
    file_errors: tuple[str, ...] = ()
    post_commit_errors: tuple[str, ...] = ()

    @property
    def is_partial(self) -> bool:
        return bool(self.file_errors or self.post_commit_errors)

    @property
    def records_deleted(self) -> int:
        return self.activity_rows_deleted

    @property
    def derived_entries_deleted(self) -> int:
        return self.zettel_rows_deleted


def _bound_errors(errors: Iterable[str]) -> tuple[str, ...]:
    return tuple(str(item)[:_MAX_ERROR_LEN] for item in list(errors)[:_MAX_ERROR_ITEMS])


def _placeholders(count: int) -> str:
    return ",".join("?" * count)


class ActivityCaptureDataLifecycleService:
    """Delete capture activities, derived Zettel rows, and screenshot files."""

    def __init__(self, db_path: str, retrieval_runtime: Any, materializer: Any) -> None:
        self.db_path = db_path
        self.retrieval_runtime = retrieval_runtime
        self.materializer = materializer

    async def delete_all(self) -> ActivityCaptureDeletionResult:
        return await self._delete_with_filter(None, None)

    async def delete_activity_ids(
        self,
        activity_ids: Sequence[str],
    ) -> ActivityCaptureDeletionResult:
        """Delete explicitly selected capture activities through the lifecycle path."""
        selected_ids = list(dict.fromkeys(activity_id for activity_id in activity_ids if activity_id))
        if not selected_ids:
            return ActivityCaptureDeletionResult()

        def _select() -> list[sqlite3.Row]:
            placeholders = _placeholders(len(selected_ids))
            query = f"""
SELECT a.id, a.timestamp, a.zettel_id, path.value AS screenshot_path
FROM activities a
LEFT JOIN activity_metadata path
  ON path.activity_id = a.id AND path.key = 'screenshot_path'
WHERE a.id IN ({placeholders})
ORDER BY a.timestamp ASC, a.id ASC
"""
            with get_sync_connection(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(query, selected_ids).fetchall()

        rows = await asyncio.to_thread(_select)
        if not rows:
            return ActivityCaptureDeletionResult()
        return await self._delete_rows(rows)

    async def delete_older_than(self, cutoff: datetime) -> ActivityCaptureDeletionResult:
        return await self._delete_with_filter(cutoff.isoformat(), None)

    async def trim_to_storage_limit(self, max_storage_mb: int) -> ActivityCaptureDeletionResult:
        byte_limit = max_storage_mb * 1024 * 1024

        def _select() -> list[sqlite3.Row]:
            with get_sync_connection(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(_CAPTURE_SELECT + " ORDER BY a.timestamp ASC, a.id ASC").fetchall()
            candidates: list[tuple[str, str, Optional[str], Optional[str], int]] = []
            total_bytes = 0
            for row in rows:
                path = row["screenshot_path"]
                size = 0
                if path and os.path.exists(path):
                    size = os.path.getsize(path)
                total_bytes += size
                candidates.append((row["id"], row["timestamp"], row["zettel_id"], path, size))
            if total_bytes <= byte_limit:
                return []
            selected_ids: list[str] = []
            running = total_bytes
            for activity_id, _ts, _zid, _path, size in candidates:
                if running <= byte_limit:
                    break
                selected_ids.append(activity_id)
                running -= size
            if not selected_ids:
                return []
            placeholders = _placeholders(len(selected_ids))
            with get_sync_connection(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(
                    _CAPTURE_SELECT + f" WHERE a.id IN ({placeholders}) ORDER BY a.timestamp ASC, a.id ASC",
                    selected_ids,
                ).fetchall()

        rows = await asyncio.to_thread(_select)
        if not rows:
            return ActivityCaptureDeletionResult()
        return await self._delete_rows(rows)

    async def _delete_with_filter(
        self,
        cutoff_iso: Optional[str],
        _unused: Optional[int],
    ) -> ActivityCaptureDeletionResult:
        def _select() -> list[sqlite3.Row]:
            query = _CAPTURE_SELECT
            params: list[Any] = []
            if cutoff_iso is not None:
                query += " WHERE a.timestamp < ?"
                params.append(cutoff_iso)
            query += " ORDER BY a.timestamp ASC, a.id ASC"
            with get_sync_connection(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(query, params).fetchall()

        rows = await asyncio.to_thread(_select)
        if not rows:
            return ActivityCaptureDeletionResult()
        return await self._delete_rows(rows)

    async def _delete_rows(self, rows: Sequence[sqlite3.Row]) -> ActivityCaptureDeletionResult:
        activity_ids = [str(row["id"]) for row in rows]
        screenshot_paths = {
            str(row["screenshot_path"])
            for row in rows
            if row["screenshot_path"]
        }
        zettel_ids = {
            str(row["zettel_id"])
            for row in rows
            if row["zettel_id"]
        }

        def _mutate() -> tuple[int, int]:
            with get_sync_connection(self.db_path) as conn:
                try:
                    zettel_list = sorted(zettel_ids)
                    activity_list = activity_ids
                    path_list = sorted(screenshot_paths)
                    if activity_list:
                        ph = _placeholders(len(activity_list))
                        conn.execute(
                            f"UPDATE assistant_outputs SET activity_id = NULL WHERE activity_id IN ({ph})",
                            activity_list,
                        )
                    if path_list:
                        ph = _placeholders(len(path_list))
                        conn.execute(
                            f"UPDATE assistant_outputs SET screen_capture_path = NULL "
                            f"WHERE screen_capture_path IN ({ph})",
                            path_list,
                        )
                    if zettel_list and activity_list:
                        zph = _placeholders(len(zettel_list))
                        aph = _placeholders(len(activity_list))
                        conn.execute(
                            f"UPDATE activities SET zettel_id = NULL "
                            f"WHERE zettel_id IN ({zph}) AND id NOT IN ({aph})",
                            [*zettel_list, *activity_list],
                        )
                    zettel_deleted = 0
                    if zettel_list:
                        zph = _placeholders(len(zettel_list))
                        conn.execute(
                            f"DELETE FROM zettel_search_fts WHERE entry_id IN ({zph})",
                            zettel_list,
                        )
                        conn.execute(
                            f"DELETE FROM retrieval_documents WHERE document_id IN ({zph})",
                            zettel_list,
                        )
                        cursor = conn.execute(
                            f"DELETE FROM zettel_entries WHERE id IN ({zph}) AND source_kind = 'screen_block'",
                            zettel_list,
                        )
                        zettel_deleted = cursor.rowcount
                    if activity_list:
                        aph = _placeholders(len(activity_list))
                        conn.execute(
                            f"DELETE FROM activity_metadata WHERE activity_id IN ({aph})",
                            activity_list,
                        )
                        cursor = conn.execute(
                            f"DELETE FROM activities WHERE id IN ({aph})",
                            activity_list,
                        )
                        activities_deleted = cursor.rowcount
                    else:
                        activities_deleted = 0
                    conn.commit()
                    return activities_deleted, zettel_deleted
                except Exception:
                    conn.rollback()
                    raise

        activities_deleted, zettel_deleted = await asyncio.to_thread(_mutate)

        file_errors: list[str] = []
        files_deleted = 0
        bytes_freed = 0
        for path in screenshot_paths:
            try:
                file_path = Path(path)
                if file_path.is_file():
                    size = file_path.stat().st_size
                    file_path.unlink()
                    files_deleted += 1
                    bytes_freed += size
            except OSError as exc:
                file_errors.append(f"{path}: {exc}")

        post_commit_errors: list[str] = []
        try:
            await asyncio.to_thread(
                lambda: self.materializer.run_pass(enabled_kinds={"screen_block"})
            )
        except Exception as exc:
            post_commit_errors.append(f"screen_block recard: {exc}")
            logger.error("Screen-block recard failed after capture deletion", exc_info=True)

        try:
            self.retrieval_runtime.request_reconciliation("activity_capture_deletion")
        except Exception as exc:
            post_commit_errors.append(f"retrieval reconciliation: {exc}")
            logger.error("Retrieval reconciliation request failed", exc_info=True)

        return ActivityCaptureDeletionResult(
            activity_rows_deleted=activities_deleted,
            zettel_rows_deleted=zettel_deleted,
            files_deleted=files_deleted,
            bytes_freed=bytes_freed,
            file_errors=_bound_errors(file_errors),
            post_commit_errors=_bound_errors(post_commit_errors),
        )
