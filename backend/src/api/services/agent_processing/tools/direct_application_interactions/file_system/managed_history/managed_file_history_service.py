"""Managed file-change history: the transaction orchestrator.

Wraps LocalTextFileWriter with durable pre/post-image snapshots, a
content-addressed blob store, drift detection, retention, and rollback --
without changing the writer's own validation, atomicity, or result contract.
Ineligible paths (see eligibility.py) bypass all of this and call the writer
directly, so agent write capability is never affected by this package.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.managed_file_history.repository import (
    ManagedFileHistoryRepository,
)
from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)

from ..text_file_write import LocalTextFileWriter
from .blob_store import ManagedHistoryBlobStore
from .bounds import (
    MAX_CHANGE_BYTES,
    MAX_STORE_BYTES,
    MAX_TASK_BYTES,
    MAX_VERSION_AGE_DAYS,
    MAX_VERSIONS_PER_FILE,
)
from .eligibility import evaluate_eligibility


class ManagedFileHistoryService:
    """Coordinate managed writes and restores for eligible text-file paths."""

    def __init__(
        self,
        *,
        db_path: str,
        blob_store: ManagedHistoryBlobStore,
        text_writer: LocalTextFileWriter,
    ) -> None:
        self._repository = ManagedFileHistoryRepository(db_path)
        self._blob_store = blob_store
        self._text_writer = text_writer

    async def apply_managed_write(
        self,
        *,
        root_task_id: str,
        agent_task_id: str,
        path: str,
        content: str,
        mode: str,
        expected_sha256: Optional[str] = None,
        origin: str = "model",
    ) -> dict[str, Any]:
        target = Path(path).expanduser()
        if mode not in {"create", "overwrite", "append"}:
            return await self._text_writer.write_text_file(
                path=path, content=content, mode=mode, expected_sha256=expected_sha256,
            )
        eligibility = evaluate_eligibility(target)
        if not eligibility.eligible:
            return await self._text_writer.write_text_file(
                path=path, content=content, mode=mode, expected_sha256=expected_sha256,
            )

        canonical_path = str(target.resolve())
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_CHANGE_BYTES:
            return self._bounds_failure(path, "The change exceeds the 10MB per-change managed history bound.")

        head = await asyncio.to_thread(self._repository.get_head, canonical_path)
        current_bytes = target.read_bytes() if target.exists() else None
        current_digest = sha256(current_bytes).hexdigest() if current_bytes is not None else None

        if current_bytes is not None and len(current_bytes) > MAX_CHANGE_BYTES:
            return self._bounds_failure(
                path,
                "The existing file exceeds the 10MB managed history snapshot bound.",
            )
        if mode == "create" and expected_sha256 is not None:
            return await self._text_writer.write_text_file(
                path=canonical_path, content=content, mode=mode, expected_sha256=expected_sha256,
            )
        if mode != "create" and expected_sha256 is not None and current_digest != expected_sha256:
            return await self._text_writer.write_text_file(
                path=canonical_path, content=content, mode=mode, expected_sha256=expected_sha256,
            )

        task_bytes = await asyncio.to_thread(self._repository.sum_task_bytes, agent_task_id)
        pending_snapshot_bytes = len(current_bytes) if current_bytes is not None else 0
        predicted_post_image_bytes = (
            pending_snapshot_bytes + len(encoded)
            if mode == "append"
            else len(encoded)
        )
        if task_bytes + pending_snapshot_bytes + predicted_post_image_bytes > MAX_TASK_BYTES:
            return self._bounds_failure(path, "This task has exceeded the 50MB per-task managed history bound.")

        total_bytes = await asyncio.to_thread(self._repository.sum_total_store_bytes)
        if total_bytes + pending_snapshot_bytes + predicted_post_image_bytes > MAX_STORE_BYTES:
            return self._bounds_failure(path, "Managed history storage has reached its 2GB total bound.")

        if mode == "create":
            if current_bytes is not None or head is not None:
                return {
                    "success": False,
                    "error": "A managed file already exists at this path; use overwrite or append.",
                    "error_type": "already_exists",
                }
            expected_precondition = None
        else:
            expected_precondition = expected_sha256 or (
                head["current_sha256"] if head is not None else current_digest
            )

        pre_image_sha256 = pre_image_size = None
        if current_bytes is not None:
            pre_image_sha256, pre_image_size = await asyncio.to_thread(self._blob_store.put, current_bytes)
            await asyncio.to_thread(self._repository.upsert_blob_ref, pre_image_sha256, pre_image_size)

        change = await asyncio.to_thread(
            self._repository.prepare_change,
            root_task_id=root_task_id,
            agent_task_id=agent_task_id,
            canonical_path=canonical_path,
            operation=mode,
            origin=origin,
            pre_image_sha256=pre_image_sha256,
            pre_image_size_bytes=pre_image_size,
            expected_precondition_sha256=expected_precondition,
        )

        if mode != "create" and head is not None and current_digest != head["current_sha256"]:
            await self._finalize_unapplied_change(
                change_id=change["id"],
                pre_image_sha256=pre_image_sha256,
                state="conflicted",
                error_message="The file was modified outside managed history; refusing to overwrite silently.",
            )
            return {
                "success": False,
                "error": "The file was modified outside managed history; refusing to overwrite silently.",
                "error_type": "managed_history_drift",
            }

        write_result = await self._text_writer.write_text_file(
            path=canonical_path, content=content, mode=mode, expected_sha256=expected_precondition,
        )
        if not write_result.get("success"):
            await self._finalize_unapplied_change(
                change_id=change["id"],
                pre_image_sha256=pre_image_sha256,
                state="failed",
                error_message=str(write_result.get("error") or "Managed write failed."),
            )
            return write_result

        post_image_sha256: str | None = None
        post_image_referenced = False
        try:
            post_image_bytes = await asyncio.to_thread(target.read_bytes)
            post_image_sha256, post_image_size = await asyncio.to_thread(self._blob_store.put, post_image_bytes)
            await asyncio.to_thread(self._repository.upsert_blob_ref, post_image_sha256, post_image_size)
            post_image_referenced = True
            await asyncio.to_thread(
                self._repository.mark_applied_and_upsert_head,
                change_id=change["id"],
                canonical_path=canonical_path,
                post_image_sha256=post_image_sha256,
                post_image_size_bytes=post_image_size,
            )
        except Exception as error:
            await self._finalize_unapplied_change(
                change_id=change["id"],
                pre_image_sha256=pre_image_sha256,
                post_image_sha256=post_image_sha256 if post_image_referenced else None,
                state="failed",
                error_message=f"Managed write could not persist its post-write snapshot: {error}",
            )
            raise
        await asyncio.to_thread(self._prune_retention_sync, canonical_path)
        await asyncio.to_thread(self._purge_pending_blobs_sync)
        return write_result

    async def restore_version(
        self,
        *,
        root_task_id: str,
        canonical_path: str,
        restores_change_id: str,
        agent_task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        target_version = await asyncio.to_thread(self._repository.get_change, restores_change_id)
        if (
            target_version is None
            or target_version["canonical_path"] != canonical_path
            or target_version["root_task_id"] != root_task_id
            or target_version["state"] not in ("applied", "reverted")
            or not target_version["post_image_sha256"]
        ):
            return {"success": False, "error": "The requested version was not found or cannot be restored."}

        head = await asyncio.to_thread(self._repository.get_head, canonical_path)
        if head is None:
            return {"success": False, "error": "No managed history head is recorded for this path."}

        target = Path(canonical_path)
        current_bytes = target.read_bytes() if target.exists() else b""
        current_digest = sha256(current_bytes).hexdigest()
        if current_digest != head["current_sha256"]:
            return {
                "success": False,
                "error": "The file was modified outside managed history; refusing to restore.",
                "error_type": "managed_history_drift",
            }

        restored_bytes = await asyncio.to_thread(self._blob_store.get, target_version["post_image_sha256"])
        restored_text = restored_bytes.decode("utf-8")
        displaced_change_id = head["current_change_id"]

        pre_image_sha256, pre_image_size = await asyncio.to_thread(self._blob_store.put, current_bytes)
        await asyncio.to_thread(self._repository.upsert_blob_ref, pre_image_sha256, pre_image_size)

        effective_agent_task_id = agent_task_id or root_task_id
        change = await asyncio.to_thread(
            self._repository.prepare_change,
            root_task_id=root_task_id,
            agent_task_id=effective_agent_task_id,
            canonical_path=canonical_path,
            operation="rollback",
            origin="user",
            pre_image_sha256=pre_image_sha256,
            pre_image_size_bytes=pre_image_size,
            expected_precondition_sha256=head["current_sha256"],
            restores_change_id=restores_change_id,
        )

        write_result = await self._text_writer.write_text_file(
            path=canonical_path, content=restored_text, mode="overwrite", expected_sha256=head["current_sha256"],
        )
        if not write_result.get("success"):
            await self._finalize_unapplied_change(
                change_id=change["id"],
                pre_image_sha256=pre_image_sha256,
                state="failed",
                error_message=str(write_result.get("error") or "Managed restore failed."),
            )
            return write_result

        post_image_sha256: str | None = None
        post_image_referenced = False
        try:
            post_image_bytes = await asyncio.to_thread(target.read_bytes)
            post_image_sha256, post_image_size = await asyncio.to_thread(self._blob_store.put, post_image_bytes)
            await asyncio.to_thread(self._repository.upsert_blob_ref, post_image_sha256, post_image_size)
            post_image_referenced = True
            await asyncio.to_thread(
                self._repository.mark_applied_and_upsert_head,
                change_id=change["id"],
                canonical_path=canonical_path,
                post_image_sha256=post_image_sha256,
                post_image_size_bytes=post_image_size,
                displaced_change_id=displaced_change_id,
            )
        except Exception as error:
            await self._finalize_unapplied_change(
                change_id=change["id"],
                pre_image_sha256=pre_image_sha256,
                post_image_sha256=post_image_sha256 if post_image_referenced else None,
                state="failed",
                error_message=f"Managed restore could not persist its post-write snapshot: {error}",
            )
            raise
        await asyncio.to_thread(self._prune_retention_sync, canonical_path)
        await asyncio.to_thread(self._purge_pending_blobs_sync)
        await self._record_restore_ledger_event(
            root_task_id=root_task_id,
            canonical_path=canonical_path,
            restores_change_id=restores_change_id,
            change_id=change["id"],
        )
        return {
            "success": True,
            "change_id": change["id"],
            "canonical_path": canonical_path,
            "restored_from_change_id": restores_change_id,
        }

    async def list_versions(self, canonical_path: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._repository.list_retained_versions,
            str(Path(canonical_path).expanduser().resolve()),
        )

    async def get_version_content(self, change_id: str) -> dict[str, Any]:
        change = await asyncio.to_thread(self._repository.get_change, change_id)
        if (
            change is None
            or change["state"] not in ("applied", "reverted")
            or not change["post_image_sha256"]
        ):
            return {"success": False, "error": "The requested version was not found."}
        if (change["post_image_size_bytes"] or 0) > MAX_CHANGE_BYTES:
            return {
                "success": True,
                "change_id": change_id,
                "canonical_path": change["canonical_path"],
                "content": None,
                "truncated": True,
                "byte_size": change["post_image_size_bytes"],
            }
        content_bytes = await asyncio.to_thread(self._blob_store.get, change["post_image_sha256"])
        return {
            "success": True,
            "change_id": change_id,
            "canonical_path": change["canonical_path"],
            "content": content_bytes.decode("utf-8"),
            "truncated": False,
            "byte_size": change["post_image_size_bytes"],
        }

    def _prune_retention_sync(self, canonical_path: str) -> None:
        head = self._repository.get_head(canonical_path)
        if head is None:
            return
        versions = self._repository.list_retained_versions(canonical_path)
        now = datetime.utcnow()
        kept_count = 0
        for version in versions:
            if version["id"] == head["current_change_id"]:
                continue
            age_days = (now - datetime.fromisoformat(version["created_at"])).days
            if kept_count < MAX_VERSIONS_PER_FILE - 1 and age_days <= MAX_VERSION_AGE_DAYS:
                kept_count += 1
                continue
            for digest in filter(None, (version["pre_image_sha256"], version["post_image_sha256"])):
                self._repository.decrement_blob_ref(digest)
            self._repository.delete_change_row(version["id"])

    def _purge_pending_blobs_sync(self) -> None:
        for blob in self._repository.list_blobs_pending_purge():
            self._blob_store.delete(blob["sha256"])
            self._repository.purge_blob_row(blob["sha256"])

    async def _record_restore_ledger_event(
        self,
        *,
        root_task_id: str,
        canonical_path: str,
        restores_change_id: str,
        change_id: str,
    ) -> None:
        from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
        from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
            AgentWorkLedgerService,
        )

        envelope = MaterialOperationEnvelope(
            receipts=(
                MaterialOperationReceipt(
                    entity=LedgerEntityReference(
                        entity_type="file",
                        source_system="managed_file_history",
                        source_scope={"host_scope": "local"},
                        external_id=canonical_path,
                    ),
                    requested_effect={
                        "operation": "rollback",
                        "restores_change_id": restores_change_id,
                    },
                    execution_state="succeeded",
                    observed_postcondition={"change_id": change_id},
                    verification_status="verified",
                    evidence={"restored_by": "user", "canonical_path": canonical_path},
                ),
            ),
        )
        await AgentWorkLedgerService(
            SQLiteKnowledgeService(db_path=self._repository.db_path)
        ).capture_tool_result(
            context={"root_task_id": root_task_id, "agent_task_id": root_task_id},
            service="managed_file_history",
            method="restore_version",
            parameters={"canonical_path": canonical_path, "restores_change_id": restores_change_id},
            result=envelope.to_tool_result_fields(),
            evidence_source="user_initiated_restore",
        )

    async def _finalize_unapplied_change(
        self,
        *,
        change_id: str,
        pre_image_sha256: str | None,
        post_image_sha256: str | None = None,
        state: str,
        error_message: str,
    ) -> None:
        transition = (
            self._repository.mark_conflicted
            if state == "conflicted"
            else self._repository.mark_failed
        )
        await asyncio.to_thread(transition, change_id, error_message)
        if pre_image_sha256 is not None:
            await asyncio.to_thread(self._repository.decrement_blob_ref, pre_image_sha256)
        if post_image_sha256 is not None:
            await asyncio.to_thread(self._repository.decrement_blob_ref, post_image_sha256)
        if pre_image_sha256 is not None or post_image_sha256 is not None:
            await asyncio.to_thread(self._purge_pending_blobs_sync)

    @staticmethod
    def _bounds_failure(path: str, message: str) -> dict[str, Any]:
        return {"success": False, "error": message, "error_type": "managed_history_bounds_exceeded", "file_path": path}
