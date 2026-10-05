"""Application boundary for the To-Do domain: transition authority,
worker reconciliation, and producer entry points."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from .models import (
    TodoAgentStatusSummary,
    TodoItemDetail,
    TodoItemSummary,
    TodoWorkerLaunchResponse,
    TodoWorkspaceHydration,
    is_terminal_todo_status,
    normalize_todo_priority,
)
from .records import agent_task_to_work_attempt
from .repository import (
    TodoIdempotencyConflict,
    TodoReferenceNotFound,
    TodoRepository,
    TodoRevisionConflict,
)

logger = logging.getLogger(__name__)

_ACTIVE_AGENT_TASK_STATUSES = frozenset({
    "capturing", "routing", "processing", "awaiting_user_input",
    "awaiting_provider_delegation", "awaiting_delegated_agents",
    "needs_clarification", "paused",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TodoConflictError(Exception):
    def __init__(self, todo_id: str, detail: TodoItemDetail):
        super().__init__(f"Conflict on To-Do {todo_id}")
        self.todo_id = todo_id
        self.detail = detail


class TodoNotFoundError(Exception):
    def __init__(self, todo_id: str):
        super().__init__(f"To-Do {todo_id} not found")
        self.todo_id = todo_id


class TodoTransitionError(Exception):
    def __init__(self, message: str, detail: Optional[TodoItemDetail] = None):
        super().__init__(message)
        self.detail = detail


class TodoService:
    def __init__(self, *, repository: TodoRepository, agent_task_service: Any):
        self.repository = repository
        self.agent_task_service = agent_task_service

    # === Hydration and listing ===

    async def get_workspace_hydration(
        self,
        *,
        query: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        sort_by: Literal["created_at", "updated_at", "due_at", "title", "status", "priority"] = "created_at",
        sort_direction: Optional[Literal["asc", "desc"]] = None,
    ) -> TodoWorkspaceHydration:
        hydration = await self.repository.get_todo_workspace_hydration(
            query=query,
            statuses=statuses,
            limit=limit,
            cursor=cursor,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
        await self._attach_agent_statuses(hydration.items)
        return hydration

    async def _attach_agent_statuses(self, items: List[TodoItemSummary]) -> None:
        if not items:
            return
        status_by_id = await self.agent_task_service.list_latest_agent_task_status_by_origins(
            "todo", [item.id for item in items],
        )
        for item in items:
            raw = status_by_id.get(item.id)
            item.agent_status = TodoAgentStatusSummary(**raw) if raw else None

    async def get_agent_statuses_for_ids(self, todo_ids: List[str]) -> Dict[str, Optional[TodoAgentStatusSummary]]:
        """Lightweight bulk re-fetch used by the sidebar's live WebSocket refresh
        (`GET /api/v1/todos/agent-status`) without re-running the full sort/filter query."""
        status_by_id = await self.agent_task_service.list_latest_agent_task_status_by_origins("todo", todo_ids)
        return {
            todo_id: TodoAgentStatusSummary(**status_by_id[todo_id]) if todo_id in status_by_id else None
            for todo_id in todo_ids
        }

    async def list_item_summaries(
        self,
        *,
        status: Optional[str],
        limit: int,
        cursor: Optional[str],
        sort_by: Literal["created_at", "updated_at"] = "created_at",
    ):
        return await self.repository.list_todo_item_summaries(
            status=status,
            limit=limit,
            cursor=cursor,
            sort_by=sort_by,
        )

    async def get_item_detail(self, todo_id: str) -> TodoItemDetail:
        detail = await self.repository.get_todo_item_detail(todo_id)
        if detail is None:
            raise TodoNotFoundError(todo_id)
        detail.worker_attempts = [
            agent_task_to_work_attempt(agent_task)
            for agent_task in await self.agent_task_service.list_agent_tasks_by_origin("todo", todo_id, True)
        ]
        detail.attention.needs_attention = any(attempt.attention for attempt in detail.worker_attempts)
        if detail.attention.needs_attention:
            detail.attention.reason = "A worker task needs your input or clarification."
        return detail

    # === Manual and producer creation ===

    async def create_manual_todo(
        self, *, title: str, description: str, notes: str, responsibility: str, priority: str,
        due_at: Optional[str], idempotency_key: Optional[str], payload_for_hash: Dict[str, Any],
    ) -> TodoItemDetail:
        payload_hash = _hash_payload(payload_for_hash) if idempotency_key else None
        try:
            detail, _created = await self.repository.create_todo_item_with_source(
                title=title, description=description, notes=notes, responsibility=responsibility,
                priority=normalize_todo_priority(priority), due_at=due_at, status="open",
                created_by_kind="user", created_by_id=None, idempotency_key=idempotency_key,
                idempotency_payload_hash=payload_hash, source_kind=None, source_id=None,
                source_locator=None, source_excerpt="",
            )
            return detail
        except TodoIdempotencyConflict as exc:
            raise TodoTransitionError(str(exc)) from exc

    async def create_todo_from_agent_tool(
        self, *, title: str, description: str, agent_task_id: str, tool_call_id: str, excerpt: str,
        status: str = "open",
    ) -> TodoItemDetail:
        detail, _created = await self.repository.create_todo_item_with_source(
            title=title, description=description, notes="", responsibility="agent", priority="normal",
            due_at=None, status=status, created_by_kind="agent", created_by_id=agent_task_id,
            idempotency_key=None, idempotency_payload_hash=None,
            source_kind="agent_task_tool", source_id=f"{agent_task_id}:{tool_call_id}",
            source_locator={"agent_task_id": agent_task_id, "tool_call_id": tool_call_id}, source_excerpt=excerpt,
        )
        return detail

    async def promote_meeting_proposal_to_todo(
        self, *, meeting_id: str, filename: str, proposal_id: str, title: str, description: str, excerpt: str,
    ) -> TodoItemDetail:
        normalized_title = _bound_meeting_proposal_title(title)
        detail, _created = await self.repository.create_todo_item_with_source(
            title=normalized_title, description=description, notes="", responsibility="unspecified", priority="normal",
            due_at=None, status="open", created_by_kind="user", created_by_id=None,
            idempotency_key=None, idempotency_payload_hash=None,
            source_kind="meeting_analysis_proposal", source_id=f"{meeting_id}:{filename}:{proposal_id}",
            source_locator={"meeting_id": meeting_id, "filename": filename, "proposal_id": proposal_id},
            source_excerpt=excerpt,
        )
        return detail

    # === User transitions ===

    async def accept_candidate(self, todo_id: str, expected_revision: int) -> TodoItemDetail:
        await self._assert_status_and_revision(todo_id, expected_revision, {"candidate"})
        return await self._transition(todo_id, expected_revision, {"status": "open"}, "accepted", "user", None)

    async def dismiss_candidate(self, todo_id: str, expected_revision: int) -> TodoItemDetail:
        await self._assert_status_and_revision(todo_id, expected_revision, {"candidate"})
        return await self._transition(todo_id, expected_revision, {"status": "dismissed"}, "dismissed", "user", None)

    async def reopen(self, todo_id: str, expected_revision: int) -> TodoItemDetail:
        await self._assert_status_and_revision(todo_id, expected_revision, {"completed", "dismissed", "canceled"})
        return await self._transition(
            todo_id,
            expected_revision,
            {"status": "open", "completed_at": None},
            "reopened",
            "user",
            None,
        )

    async def cancel(self, todo_id: str, expected_revision: int) -> TodoItemDetail:
        await self._assert_status_and_revision(todo_id, expected_revision, {"open", "in_progress"})
        return await self._transition(todo_id, expected_revision, {"status": "canceled"}, "canceled", "user", None)

    async def delete_todo_item(self, todo_id: str, expected_revision: int) -> None:
        detail = await self.get_item_detail(todo_id)
        active_workers = await self.agent_task_service.list_agent_tasks_by_origin("todo", todo_id, False)
        root_status_by_id = await self.agent_task_service.list_latest_agent_task_status_by_origins("todo", [todo_id])
        active_origin_task = root_status_by_id.get(todo_id, {}).get("is_active") is True
        if active_workers or active_origin_task:
            raise TodoTransitionError(
                "Cannot delete while an originating Paprika task or its follow-up is active.",
                detail=detail,
            )
        try:
            await self.repository.delete_todo_item_with_expected_revision(
                todo_id=todo_id,
                expected_revision=expected_revision,
            )
        except TodoRevisionConflict as exc:
            raise TodoConflictError(todo_id, await self.get_item_detail(todo_id)) from exc

    async def complete(self, todo_id: str, expected_revision: int) -> TodoItemDetail:
        detail = await self._assert_status_and_revision(
            todo_id,
            expected_revision,
            {"open", "in_progress", "ready_for_review"},
        )
        active_workers = await self.agent_task_service.list_agent_tasks_by_origin("todo", todo_id, False)
        if active_workers:
            raise TodoTransitionError(
                "Cannot complete while a directly sourced Paprika task is active.", detail=detail,
            )
        return await self._transition(
            todo_id,
            expected_revision,
            {"status": "completed", "completed_at": detail.completed_at or _utc_now_iso()},
            "completed",
            "user",
            None,
        )

    async def update_fields(self, todo_id: str, expected_revision: int, fields: Dict[str, Any]) -> TodoItemDetail:
        allowed_fields = {"title", "description", "responsibility", "priority", "due_at", "completed_at"}
        clean_fields = {
            key: value
            for key, value in fields.items()
            if key in allowed_fields and (value is not None or key in {"due_at", "completed_at"})
        }
        if not clean_fields:
            raise TodoTransitionError("At least one mutable field is required.")
        if "priority" in clean_fields:
            clean_fields["priority"] = normalize_todo_priority(clean_fields["priority"])
        if "completed_at" in clean_fields:
            detail = await self.get_item_detail(todo_id)
            if detail.status != "completed":
                raise TodoTransitionError("Completed date can only be changed for a completed To-Do.", detail=detail)
        return await self._transition(todo_id, expected_revision, clean_fields, "updated", "user", None)

    async def replace_notes(self, todo_id: str, expected_revision: int, notes: str) -> TodoItemDetail:
        try:
            detail = await self.repository.replace_todo_item_notes_with_expected_revision(
                todo_id=todo_id, notes=notes, expected_revision=expected_revision, actor_kind="user", actor_id=None,
            )
            return await self._hydrate_detail(detail)
        except TodoRevisionConflict as exc:
            latest = await self.get_item_detail(todo_id)
            raise TodoConflictError(todo_id, latest) from exc

    async def add_reference(
        self,
        todo_id: str,
        path: str,
        expected_revision: Optional[int] = None,
        actor_agent_task_id: Optional[str] = None,
    ) -> TodoItemDetail:
        normalized_path = _normalize_reference_path(path)
        if expected_revision is None:
            expected_revision = (await self.get_item_detail(todo_id)).revision
        try:
            detail = await self.repository.add_todo_reference_with_expected_revision(
                todo_id=todo_id,
                path=normalized_path,
                expected_revision=expected_revision,
                actor_kind="agent" if actor_agent_task_id else "user",
                actor_id=actor_agent_task_id,
            )
            return await self._hydrate_detail(detail)
        except TodoRevisionConflict as exc:
            latest = await self.get_item_detail(todo_id)
            raise TodoConflictError(todo_id, latest) from exc

    async def remove_reference(
        self,
        todo_id: str,
        reference_id: str,
        expected_revision: int,
    ) -> TodoItemDetail:
        try:
            detail = await self.repository.remove_todo_reference_with_expected_revision(
                todo_id=todo_id,
                reference_id=reference_id,
                expected_revision=expected_revision,
                actor_kind="user",
                actor_id=None,
            )
            return await self._hydrate_detail(detail)
        except TodoRevisionConflict as exc:
            latest = await self.get_item_detail(todo_id)
            raise TodoConflictError(todo_id, latest) from exc
        except TodoReferenceNotFound as exc:
            raise TodoTransitionError(str(exc)) from exc

    @staticmethod
    def worker_handoff(item: TodoItemDetail) -> Dict[str, Any]:
        source_agent_task_ids: List[str] = []
        source_excerpts: Dict[str, str] = {}
        for source in item.sources:
            if source.created_by_kind != "agent" or not isinstance(source.source_locator, dict):
                continue
            agent_task_id = source.source_locator.get("agent_task_id")
            if isinstance(agent_task_id, str) and agent_task_id and agent_task_id not in source_agent_task_ids:
                source_agent_task_ids.append(agent_task_id)
                if source.source_excerpt:
                    source_excerpts[agent_task_id] = source.source_excerpt
        return {
            "source_agent_task_ids": source_agent_task_ids,
            "source_excerpts": source_excerpts,
            "reference_paths": list(dict.fromkeys(reference.path for reference in item.references)),
        }

    # === Workspace-manager scoped mutation ===

    async def append_workspace_manager_note(self, todo_id: str, note_markdown: str, manager_agent_task_id: str) -> TodoItemDetail:
        detail = await self.repository.append_todo_item_note(
            todo_id=todo_id, note_markdown=note_markdown, actor_kind="agent", actor_id=manager_agent_task_id,
        )
        return await self._hydrate_detail(detail)

    async def launch_todo_worker(
        self, *, todo_id: str, expected_revision: int, launcher: Any,
    ) -> TodoWorkerLaunchResponse:
        """`launcher` is `TodoAgentTaskBridge.launch_todo_item_agent_task`, injected
        by the caller to avoid a service->bridge import cycle."""
        detail = await self.get_item_detail(todo_id)
        if detail.revision != expected_revision:
            raise TodoConflictError(todo_id, detail)
        if detail.status == "candidate":
            raise TodoTransitionError("Cannot launch a worker for a candidate; accept it first.", detail=detail)
        if is_terminal_todo_status(detail.status):
            raise TodoTransitionError("Cannot launch a worker for a terminal To-Do.", detail=detail)
        result = await launcher(todo_id=todo_id)
        if not result.get("success", False):
            raise TodoTransitionError(result.get("error", "To-Do worker submission failed"), detail=detail)
        agent_task_id = result.get("agent_task_id")
        if not isinstance(agent_task_id, str) or not agent_task_id.strip():
            raise TodoTransitionError("To-Do worker submission did not return a Paprika task ID.", detail=detail)
        return TodoWorkerLaunchResponse(
            item=await self.get_item_detail(todo_id),
            agent_task_id=agent_task_id,
        )

    async def mark_worker_launched(
        self, todo_id: str, expected_revision: int, agent_task_id: str,
    ) -> TodoItemDetail:
        return await self._transition(
            todo_id,
            expected_revision,
            {"status": "in_progress"},
            "worker_launched",
            "agent",
            agent_task_id,
            {"status": "in_progress", "agent_task_id": agent_task_id},
        )

    # === Worker reconciliation ===

    async def reconcile_todo_from_worker_tasks(self, todo_id: str) -> Optional[TodoItemDetail]:
        try:
            detail = await self.get_item_detail(todo_id)
        except TodoNotFoundError:
            return None
        if is_terminal_todo_status(detail.status):
            return detail

        workers = await self.agent_task_service.list_agent_tasks_by_origin("todo", todo_id, True)
        if not workers:
            return detail
        statuses = [worker.status for worker in workers]
        any_active = any(status in _ACTIVE_AGENT_TASK_STATUSES for status in statuses)
        any_completed = any(status == "completed" for status in statuses)

        if any_active:
            if detail.status == "open":
                return await self._transition(todo_id, detail.revision, {"status": "in_progress"}, "worker_active", "system", None)
            return detail
        if any_completed:
            return await self._transition(todo_id, detail.revision, {"status": "ready_for_review"}, "worker_completed", "system", None)
        return detail

    async def reconcile_all_nonterminal_todo_workers(self) -> int:
        if hasattr(self.agent_task_service, "list_agent_task_origin_ids_by_origin_type"):
            seen_todo_ids = set(
                await self.agent_task_service.list_agent_task_origin_ids_by_origin_type("todo")
            )
        else:
            workers = await self.agent_task_service.list_nonterminal_agent_tasks_by_origin_type("todo")
            seen_todo_ids = {worker.origin_id for worker in workers if worker.origin_id}
        for todo_id in seen_todo_ids:
            await self.reconcile_todo_from_worker_tasks(todo_id)
        return len(seen_todo_ids)

    # === Internal helpers ===

    async def _transition(
        self, todo_id: str, expected_revision: int, fields: Dict[str, Any], event_kind: str,
        actor_kind: str, actor_id: Optional[str], event_payload: Optional[Dict[str, Any]] = None,
    ) -> TodoItemDetail:
        try:
            detail = await self.repository.update_todo_item_with_expected_revision(
                todo_id=todo_id, expected_revision=expected_revision, fields=fields,
                event_kind=event_kind, actor_kind=actor_kind, actor_id=actor_id, event_payload=event_payload,
            )
            return await self._hydrate_detail(detail)
        except TodoRevisionConflict as exc:
            latest = await self.get_item_detail(todo_id)
            raise TodoConflictError(todo_id, latest) from exc

    async def _assert_status_and_revision(
        self, todo_id: str, expected_revision: int, allowed_statuses: set[str],
    ) -> TodoItemDetail:
        detail = await self.get_item_detail(todo_id)
        if detail.revision != expected_revision:
            raise TodoConflictError(todo_id, detail)
        if detail.status not in allowed_statuses:
            expected = ", ".join(sorted(allowed_statuses))
            raise TodoTransitionError(
                f"Cannot apply this action while the To-Do is {detail.status}; expected one of: {expected}.",
                detail=detail,
            )
        return detail

    async def _hydrate_detail(self, detail: TodoItemDetail) -> TodoItemDetail:
        detail.worker_attempts = [
            agent_task_to_work_attempt(agent_task)
            for agent_task in await self.agent_task_service.list_agent_tasks_by_origin("todo", detail.id, True)
        ]
        return detail


def _bound_meeting_proposal_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise TodoTransitionError("Meeting proposal title must not be blank.")
    if len(normalized) <= 240:
        return normalized
    return normalized[:240]


def _hash_payload(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_reference_path(path: str) -> str:
    if not isinstance(path, str):
        raise TodoTransitionError("Reference path must be a string.")
    trimmed = path.strip()
    if "\x00" in trimmed or not trimmed or len(trimmed) > 4096 or not os.path.isabs(trimmed):
        raise TodoTransitionError(
            "Reference path must be a nonblank absolute path of at most 4096 characters without NUL bytes."
        )
    return os.path.normpath(trimmed)
