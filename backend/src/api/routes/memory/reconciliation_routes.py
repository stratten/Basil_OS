"""Skill Reconciliation Workspace API.

A dedicated router (prefix ``/memory/reconciliation``) for the transactional
staging workspace: start/hydrate a session, record per-action decisions, and
commit or discard. Kept separate from ``router.py`` (already large) and included
alongside the memory router in the central registry.

Lock semantics: ``POST /session`` activates the freeze gate; ``POST
/session/discard`` (fired when the workspace window closes) releases it and drops
the in-memory session. ``POST /session/commit`` applies accepted decisions but
intentionally leaves the gate active until the window closes.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.routes.memory.reconciliation_models import (
    ActionDecisionRequest,
    ProposedActionModel,
    ReconciliationSessionModel,
    ReconciliationStatusModel,
)
from api.services.skills.reconciliation import reconciliation_gate
from api.services.skills.reconciliation.reconciliation_commit import commit_active_session
from api.services.skills.reconciliation.reconciliation_engine import (
    get_reconciliation_engine,
)
from api.services.skills.reconciliation.reconciliation_session import (
    DECISION_ACCEPTED,
    DECISION_PENDING,
    DECISION_REJECTED,
    get_reconciliation_session_store,
)


router = APIRouter(prefix="/memory/reconciliation", tags=["memory", "reconciliation"])

_VALID_DECISIONS = {DECISION_ACCEPTED, DECISION_REJECTED, DECISION_PENDING}


@router.post("/session", response_model=ReconciliationSessionModel)
async def start_reconciliation_session() -> ReconciliationSessionModel:
    """Start a session: snapshot state, freeze capture, and begin analysis."""
    if reconciliation_gate.is_active():
        raise HTTPException(
            status_code=409,
            detail={"message": "A reconciliation session is already active."},
        )
    try:
        session = await get_reconciliation_engine().start_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)}) from exc
    return ReconciliationSessionModel.model_validate(session.to_dict())


@router.get("/session", response_model=ReconciliationSessionModel)
async def get_reconciliation_session() -> ReconciliationSessionModel:
    """Return the active session so a mounting webview can hydrate."""
    session = get_reconciliation_session_store().load()
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "No reconciliation session is active."},
        )
    return ReconciliationSessionModel.model_validate(session.to_dict())


@router.get("/session/status", response_model=ReconciliationStatusModel)
async def get_reconciliation_status() -> ReconciliationStatusModel:
    """Lightweight lock-state summary for Settings (no snapshot payload)."""
    session = get_reconciliation_session_store().load()
    if session is None:
        return ReconciliationStatusModel(active=False)
    return ReconciliationStatusModel(
        active=True,
        session_id=session.id,
        status=session.status,
        pending_count=len(session.snapshot.pending_candidates),
        action_count=len(session.actions),
    )


@router.post(
    "/session/actions/{action_id}/decision",
    response_model=ProposedActionModel,
)
async def decide_reconciliation_action(
    action_id: str,
    request: ActionDecisionRequest,
) -> ProposedActionModel:
    """Accept/reject a proposed action, optionally with edited merged fields."""
    if request.decision not in _VALID_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Unsupported decision '{request.decision}'."},
        )
    edited = None
    if request.edited is not None:
        edited = {
            key: value
            for key, value in request.edited.model_dump().items()
            if value is not None
        }
    try:
        action = get_reconciliation_session_store().set_action_decision(
            action_id,
            request.decision,
            user_edited=edited or None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc)}) from exc
    return ProposedActionModel.model_validate(action.to_dict())


@router.post("/session/commit", response_model=ReconciliationSessionModel)
async def commit_reconciliation_session() -> ReconciliationSessionModel:
    """Apply accepted decisions to the live stores; leaves the gate active."""
    try:
        commit_active_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)}) from exc
    session = get_reconciliation_session_store().load()
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "No reconciliation session is active."},
        )
    return ReconciliationSessionModel.model_validate(session.to_dict())


@router.post("/session/discard")
async def discard_reconciliation_session() -> dict:
    """Release the gate and drop the session (fired on window close). Idempotent."""
    reconciliation_gate.deactivate()
    get_reconciliation_session_store().clear()
    return {"discarded": True}
