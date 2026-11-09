"""Checklist routes: the user's view of, and edits to, a chain's durable checklist."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_work.checklist_records import (
    MAX_NOTES_CHARS,
)
from api.dependencies import get_sqlite_knowledge_service
from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import AgentChecklistService

logger = logging.getLogger(__name__)

router = APIRouter()

RECEIPT_LIMIT = 20


class ChecklistItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=400)
    detail: str = ""
    required: bool = False
    status: str = "pending"
    waiting_on: str = ""
    refs: List[Dict[str, Any]] = Field(default_factory=list)


class ChecklistItemPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Optional[int] = None
    title: Optional[str] = None
    detail: Optional[str] = None
    status: Optional[str] = None
    required: Optional[bool] = None
    note: Optional[str] = None
    waiting_on: Optional[str] = None
    recheck_at: Optional[str] = None
    event_text: Optional[str] = None


class ChecklistArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool = True


class ChecklistCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed: bool = True


class ChecklistNotesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=200000)
    expected_revision: Optional[int] = None


async def _root_task_id(knowledge_service: SQLiteKnowledgeService, task_id: str) -> str:
    """Any task of a chain resolves to the chain's root, which owns the checklist."""
    record = await knowledge_service.agent_task_service.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"AgentTask {task_id} not found")
    return str(getattr(record, "root_task_id", None) or record.id)


async def _write_session(service: AgentChecklistService, root_task_id: str) -> Dict[str, Any]:
    session = await service.session_for_root(root_task_id, create=True)
    if session is None:
        raise HTTPException(status_code=404, detail="No checklist is available for this task.")
    return session


def _conflict(current: Dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "This changed while you were editing it. The latest version is shown.", "current": current},
    )


async def _payload(service: AgentChecklistService, root_task_id: str) -> Dict[str, Any]:
    session = await service.session_for_root(root_task_id, create=False)
    empty_notes = {"content": "", "revision": 0, "updated_by": None, "updated_at": None, "carried_from_task_id": None}
    if session is None:
        return {
            "root_task_id": root_task_id, "exists": False, "closed_at": None, "items": [],
            "counts": {"total": 0, "done": 0, "open": 0, "waiting_user": 0, "waiting_external": 0, "required_open": 0},
            "notes": empty_notes, "notes_max_chars": MAX_NOTES_CHARS,
        }
    snapshot = await service.snapshot(session["id"], include_archived=True)
    return {
        "root_task_id": root_task_id, "exists": True, "closed_at": snapshot["closed_at"], "items": snapshot["items"],
        "counts": snapshot["counts"], "notes": snapshot["notes"], "notes_max_chars": MAX_NOTES_CHARS,
    }


def _ids(root_task_id: str) -> Dict[str, Any]:
    return {"root_task_id": root_task_id, "agent_task_id": root_task_id}


@router.get("/{agent_task_id}/checklist", summary="Get the checklist of a task chain")
async def get_checklist(
    agent_task_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> Dict[str, Any]:
    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    return await _payload(AgentChecklistService(knowledge_service), root_task_id)


@router.get("/{agent_task_id}/checklist/items/{item_id}/log", summary="Step log and captured actions for one checklist item")
async def get_checklist_item_log(
    agent_task_id: str = Path(...),
    item_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> Dict[str, Any]:
    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    service = AgentChecklistService(knowledge_service)
    session = await service.session_for_root(root_task_id, create=False)
    item = await knowledge_service.agent_checklist_repository.get_item(session["id"], item_id) if session else None
    if item is None:
        raise HTTPException(status_code=404, detail="That checklist item no longer exists.")
    events = await service.step_log(session["id"], item_id)
    captured: List[Dict[str, Any]] = []
    if item.get("work_item_id"):
        receipts = await knowledge_service.agent_work_receipt_repository.get_receipts(
            session_id=session["id"], item_id=item["work_item_id"], limit=RECEIPT_LIMIT, newest_first=True,
        )
        captured = [
            {key: receipt[key] for key in ("service", "method", "execution_state", "verification_status", "material_write", "created_at")}
            for receipt in receipts
        ]
    return {"item_id": item_id, "events": events, "captured": captured}


@router.post("/{agent_task_id}/checklist/items", summary="Add a checklist item as the user")
async def add_checklist_item(
    body: ChecklistItemCreateRequest,
    agent_task_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> Dict[str, Any]:
    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    service = AgentChecklistService(knowledge_service)
    session = await _write_session(service, root_task_id)
    try:
        result = await knowledge_service.agent_checklist_repository.add_item(
            session_id=session["id"], origin="user", actor="user", title=body.title, detail=body.detail,
            required=body.required, status=body.status, waiting_on=body.waiting_on, refs=body.refs,
            agent_task_id=root_task_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result.get("rejected"):
        raise HTTPException(status_code=409, detail=result["rejected"])
    if result.get("created"):
        await service.publish(session["id"], _ids(root_task_id))
    return {"created": bool(result.get("created")), "duplicate": bool(result.get("duplicate")), "item": result["item"]}


@router.patch("/{agent_task_id}/checklist/items/{item_id}", summary="Edit a checklist item as the user")
async def patch_checklist_item(
    body: ChecklistItemPatchRequest,
    agent_task_id: str = Path(...),
    item_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
):
    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    service = AgentChecklistService(knowledge_service)
    session = await service.session_for_root(root_task_id, create=False)
    if session is None:
        raise HTTPException(status_code=404, detail="That checklist item no longer exists.")
    changes = body.model_dump(exclude_unset=True)
    expected_revision = changes.pop("expected_revision", None)
    event_text = changes.pop("event_text", None) or ""
    try:
        result = await knowledge_service.agent_checklist_repository.update_item(
            session_id=session["id"], item_id=item_id, changes=changes, expected_revision=expected_revision,
            actor="user", agent_task_id=root_task_id, event_text=event_text,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="That checklist item no longer exists.")
    if result.get("conflict"):
        return _conflict(result["current"])
    if result.get("changed"):
        await service.publish(session["id"], _ids(root_task_id))
    return {"item": result["item"], "changed": bool(result.get("changed"))}


@router.post("/{agent_task_id}/checklist/items/{item_id}/archive", summary="Archive or restore a checklist item")
async def archive_checklist_item(
    body: ChecklistArchiveRequest,
    agent_task_id: str = Path(...),
    item_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> Dict[str, Any]:
    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    service = AgentChecklistService(knowledge_service)
    session = await service.session_for_root(root_task_id, create=False)
    item = (
        await knowledge_service.agent_checklist_repository.set_archived(
            session_id=session["id"], item_id=item_id, archived=body.archived, actor="user", agent_task_id=root_task_id,
        )
        if session
        else None
    )
    if item is None:
        raise HTTPException(status_code=404, detail="That checklist item no longer exists.")
    await service.publish(session["id"], _ids(root_task_id))
    return {"item": item}


@router.post("/{agent_task_id}/checklist/close", summary="Close or reopen the checklist")
async def close_checklist(
    body: ChecklistCloseRequest,
    agent_task_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> Dict[str, Any]:
    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    service = AgentChecklistService(knowledge_service)
    session = await _write_session(service, root_task_id)
    result = await knowledge_service.agent_checklist_repository.set_closed(session["id"], body.closed)
    await service.publish(session["id"], _ids(root_task_id))
    return {"closed_at": result["closed_at"]}


@router.put("/{agent_task_id}/checklist/notes", summary="Replace the checklist notes as the user")
async def put_checklist_notes(
    body: ChecklistNotesRequest,
    agent_task_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
):
    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    service = AgentChecklistService(knowledge_service)
    session = await _write_session(service, root_task_id)
    result = await knowledge_service.agent_checklist_notes_repository.set_notes(
        session["id"], body.content, actor="user", expected_revision=body.expected_revision,
    )
    if result.get("conflict"):
        return _conflict(result["current"])
    if result.get("rejected"):
        raise HTTPException(status_code=422, detail=result["error"])
    if result.get("changed"):
        await service.publish(session["id"], _ids(root_task_id))
    return {"notes": result["notes"]}


@router.post("/{agent_task_id}/checklist/items/{item_id}/todo", summary="Offer a checklist item as a candidate To-Do")
async def offer_checklist_item_as_todo(
    agent_task_id: str = Path(...),
    item_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> Dict[str, Any]:
    """The To-Do stays a candidate until the user accepts it in the To-Do workspace; nothing is created as open."""
    from api.dependencies import get_todo_service

    root_task_id = await _root_task_id(knowledge_service, agent_task_id)
    service = AgentChecklistService(knowledge_service)
    session = await service.session_for_root(root_task_id, create=False)
    item = await knowledge_service.agent_checklist_repository.get_item(session["id"], item_id) if session else None
    if item is None:
        raise HTTPException(status_code=404, detail="That checklist item no longer exists.")
    description = "\n\n".join(part for part in (item["detail"], f"Waiting on: {item['waiting_on']}" if item["waiting_on"] else "") if part)
    detail = await get_todo_service().create_todo_from_agent_tool(
        title=item["title"][:240], description=description, agent_task_id=root_task_id,
        tool_call_id=f"checklist-{item['id']}", excerpt=description[:500], status="candidate",
    )
    await knowledge_service.agent_checklist_repository.add_item_event(
        session_id=session["id"], item_id=item_id, kind="todo_offered", actor="user", text=f"To-Do {detail.id}",
        agent_task_id=root_task_id,
    )
    return {"todo_id": detail.id, "status": detail.status}
