"""To-Do REST routes. Maps requests to `TodoService`; no SQL here."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ...dependencies import get_todo_service
from ...services.todos.agent_task_bridge import get_todo_agent_task_bridge
from ...services.todos.models import (
    AddTodoReferenceRequest,
    CreateTodoItemRequest,
    ExpectedRevisionRequest,
    LaunchTodoWorkerRequest,
    PromoteMeetingProposalRequest,
    RemoveTodoReferenceRequest,
    ReplaceTodoNotesRequest,
    TodoStatus,
    TodoWorkerLaunchResponse,
    UpdateTodoItemRequest,
)
from ...services.todos.service import TodoConflictError, TodoNotFoundError, TodoTransitionError

router = APIRouter(prefix="/api/v1/todos", tags=["todos"])


def _conflict(exc: TodoConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "item": exc.detail.model_dump()},
    )


TodoSortColumn = Literal["created_at", "updated_at", "due_at", "title", "status", "priority"]
TodoSortDirection = Literal["asc", "desc"]


@router.get("/workspace")
async def get_workspace(
    query: Optional[str] = Query(default=None, max_length=240),
    status: list[TodoStatus] = Query(default=[]),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    sort_by: TodoSortColumn = Query(default="created_at"),
    sort_direction: Optional[TodoSortDirection] = Query(default=None),
    todo_service=Depends(get_todo_service),
):
    try:
        return await todo_service.get_workspace_hydration(
            query=query,
            statuses=status,
            limit=limit,
            cursor=cursor,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agent-status")
async def get_agent_statuses(
    ids: str = Query(default=""),
    todo_service=Depends(get_todo_service),
):
    todo_ids = [todo_id for todo_id in ids.split(",") if todo_id]
    statuses = await todo_service.get_agent_statuses_for_ids(todo_ids)
    return {
        todo_id: summary.model_dump() if summary else None
        for todo_id, summary in statuses.items()
    }


@router.get("/items")
async def list_items(
    status: Optional[str] = Query(default=None),
    sort_by: Literal["created_at", "updated_at"] = Query(default="created_at"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    todo_service=Depends(get_todo_service),
):
    items, next_cursor = await todo_service.list_item_summaries(
        status=status,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
    )
    return {"items": [item.model_dump() for item in items], "next_cursor": next_cursor}


@router.get("/items/{todo_id}")
async def get_item(todo_id: str, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.get_item_detail(todo_id)
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items")
async def create_item(body: CreateTodoItemRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.create_manual_todo(
            title=body.title, description=body.description, notes=body.notes,
            responsibility=body.responsibility, priority=body.priority, due_at=body.due_at,
            idempotency_key=body.idempotency_key,
            payload_for_hash=body.model_dump(exclude={"idempotency_key"}),
        )
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.patch("/items/{todo_id}")
async def update_item(todo_id: str, body: UpdateTodoItemRequest, todo_service=Depends(get_todo_service)):
    fields = {
        field: getattr(body, field)
        for field in body.model_fields_set - {"expected_revision"}
    }
    try:
        return await todo_service.update_fields(todo_id, body.expected_revision, fields)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.put("/items/{todo_id}/notes")
async def replace_notes(todo_id: str, body: ReplaceTodoNotesRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.replace_notes(todo_id, body.expected_revision, body.notes)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.delete("/items/{todo_id}")
async def delete_item(todo_id: str, body: ExpectedRevisionRequest, todo_service=Depends(get_todo_service)):
    try:
        await todo_service.delete_todo_item(todo_id, body.expected_revision)
        return {"id": todo_id}
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items/{todo_id}/references")
async def add_reference(todo_id: str, body: AddTodoReferenceRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.add_reference(todo_id, body.path, body.expected_revision)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.delete("/items/{todo_id}/references/{reference_id}")
async def remove_reference(
    todo_id: str,
    reference_id: str,
    body: RemoveTodoReferenceRequest,
    todo_service=Depends(get_todo_service),
):
    try:
        return await todo_service.remove_reference(todo_id, reference_id, body.expected_revision)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items/{todo_id}/accept")
async def accept_item(todo_id: str, body: ExpectedRevisionRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.accept_candidate(todo_id, body.expected_revision)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items/{todo_id}/dismiss")
async def dismiss_item(todo_id: str, body: ExpectedRevisionRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.dismiss_candidate(todo_id, body.expected_revision)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items/{todo_id}/complete")
async def complete_item(todo_id: str, body: ExpectedRevisionRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.complete(todo_id, body.expected_revision)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items/{todo_id}/reopen")
async def reopen_item(todo_id: str, body: ExpectedRevisionRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.reopen(todo_id, body.expected_revision)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items/{todo_id}/cancel")
async def cancel_item(todo_id: str, body: ExpectedRevisionRequest, todo_service=Depends(get_todo_service)):
    try:
        return await todo_service.cancel(todo_id, body.expected_revision)
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/items/{todo_id}/workers", response_model=TodoWorkerLaunchResponse)
async def launch_worker(todo_id: str, body: LaunchTodoWorkerRequest, todo_service=Depends(get_todo_service)):
    bridge = get_todo_agent_task_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="To-Do worker bridge is not initialized")
    try:
        return await todo_service.launch_todo_worker(
            todo_id=todo_id, expected_revision=body.expected_revision,
            launcher=bridge.launch_todo_item_agent_task,
        )
    except TodoConflictError as exc:
        return _conflict(exc)
    except TodoTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail=f"To-Do {todo_id} not found")


@router.post("/meeting-proposals/promote")
async def promote_meeting_proposal(body: PromoteMeetingProposalRequest, todo_service=Depends(get_todo_service)):
    existing = await todo_service.repository.find_todo_by_source(
        source_kind="meeting_analysis_proposal",
        source_id=f"{body.meeting_id}:{body.filename}:{body.proposal_id}",
    )
    if existing is not None:
        return existing
    try:
        detail = await todo_service.promote_meeting_proposal_to_todo(
            meeting_id=body.meeting_id, filename=body.filename, proposal_id=body.proposal_id,
            title=body.source_task, description=body.suggested_agent_task,
            excerpt=body.source_context or body.why_basil_can_help,
        )
    except TodoTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        from ...routes.meetings.analysis_proposal_store import update_proposal_outcome

        update_proposal_outcome(body.meeting_id, body.filename, body.proposal_id, "added_to_todos", None, todo_id=detail.id)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Created To-Do %s but could not update meeting proposal projection", detail.id, exc_info=True,
        )
    return detail
