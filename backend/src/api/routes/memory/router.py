"""Routes for inspecting and editing Basil working memory."""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services.memory.intelligence_scheduler import get_memory_intelligence_scheduler
from api.services.memory.memory_service import get_memory_service
from api.services.memory.proposal_store import get_proposal_store
from api.services.memory.memory_store import (
    MemoryFileBackpressureError,
    MemoryFileNotFoundError,
)
from api.services.skills.reconciliation import reconciliation_gate
from api.services.skills.skill_service import get_skill_service
from api.services.skills.skill_store import (
    SKILL_BODY_CAP_BYTES,
    SkillBackpressureError,
    SkillNotFoundError,
)


router = APIRouter(prefix="/memory", tags=["memory"])


def _reject_if_reconciliation_active() -> None:
    """Raise HTTP 409 when a reconciliation workspace owns the skill state.

    While a workspace window is open the pending skill-candidate queue and saved
    skills are frozen so the session can reconcile a stable snapshot. Manual
    mutations and the run-now sweep are blocked until it closes.
    """
    if reconciliation_gate.is_active():
        raise HTTPException(
            status_code=409,
            detail={"message": reconciliation_gate.RECONCILIATION_ACTIVE_MESSAGE},
        )


class MemoryDocumentResponse(BaseModel):
    file_name: str
    content: str
    size_bytes: int
    cap_bytes: int | None = None


class MemoryDocumentListResponse(BaseModel):
    documents: List[MemoryDocumentResponse]


class MemoryDocumentUpdateRequest(BaseModel):
    content: str = Field(description="Replacement markdown content for the managed memory file.")


class MemorySearchResponseItem(BaseModel):
    file_name: str
    line_number: int
    line: str


class MemorySearchResponse(BaseModel):
    results: List[MemorySearchResponseItem]


class MemoryCapsResponse(BaseModel):
    caps: Dict[str, int]


class MemoryRunNowResponse(BaseModel):
    memory_proposals_added: int
    skill_candidates_added: int
    errors: List[str]


class MemoryPromotionResponseItem(BaseModel):
    id: str
    target_file_name: str
    entry: str
    why: str | None = None
    confidence: str | None = None
    source: str
    created_at: str
    status: str


class MemoryPromotionListResponse(BaseModel):
    proposals: List[MemoryPromotionResponseItem]


class MemoryPromotionApprovalRequest(BaseModel):
    edited_entry: str | None = None
    target_file_name: str | None = None


class SkillResponseItem(BaseModel):
    slug: str
    title: str
    body: str
    when_to_use: str
    triggers: List[str]
    size_bytes: int
    cap_bytes: int
    last_used: str | None = None
    observation_count: int = 1
    version: int = 1


class SkillCatalogResponseItem(BaseModel):
    slug: str
    title: str
    when_to_use: str
    triggers: List[str]
    size_bytes: int
    cap_bytes: int
    last_used: str | None = None
    observation_count: int = 1
    version: int = 1


class SkillListResponse(BaseModel):
    skills: List[SkillCatalogResponseItem]


class SkillUpdateRequest(BaseModel):
    title: str
    body: str
    when_to_use: str
    triggers: List[str] = Field(default_factory=list)


class SkillCandidateResponseItem(BaseModel):
    id: str
    title: str
    when_to_use: str
    triggers: List[str]
    procedure_markdown: str
    expected_result: str
    source_task_ids: List[str]
    source: str
    created_at: str
    status: str
    enhances_skill_slug: str | None = None
    observation_count: int = 1
    approved_skill_slug: str | None = None


class SkillCandidateListResponse(BaseModel):
    candidates: List[SkillCandidateResponseItem]


class SkillCandidateApprovalRequest(BaseModel):
    title: str | None = None
    when_to_use: str | None = None
    triggers: List[str] | None = None
    procedure_markdown: str | None = None


@router.get("/", response_model=MemoryDocumentListResponse)
async def list_memory_documents() -> MemoryDocumentListResponse:
    """List all managed working-memory documents."""
    memory_service = get_memory_service()
    return MemoryDocumentListResponse(
        documents=[
            _document_to_response(document)
            for document in memory_service.list_memory_documents()
        ]
    )


@router.get("/caps", response_model=MemoryCapsResponse)
async def get_memory_caps() -> MemoryCapsResponse:
    """Return managed memory hard caps in bytes."""
    return MemoryCapsResponse(caps=get_memory_service().get_memory_file_caps())


@router.post("/run-now", response_model=MemoryRunNowResponse)
async def run_memory_intelligence_now() -> MemoryRunNowResponse:
    """Run the enabled memory and skill intelligence sweep immediately."""
    _reject_if_reconciliation_active()
    result = await get_memory_intelligence_scheduler().run_now()
    return MemoryRunNowResponse(
        memory_proposals_added=result.memory_proposals_added,
        skill_candidates_added=result.skill_candidates_added,
        errors=result.errors,
    )


@router.get("/promotions", response_model=MemoryPromotionListResponse)
async def list_pending_memory_promotions() -> MemoryPromotionListResponse:
    """List pending user-reviewable working-memory promotion proposals."""
    proposals = get_proposal_store().list_pending_memory_proposals()
    return MemoryPromotionListResponse(
        proposals=[
            _memory_proposal_to_response(proposal)
            for proposal in proposals
        ]
    )


@router.post("/promotions/{proposal_id}/approve", response_model=MemoryPromotionResponseItem)
async def approve_memory_promotion(
    proposal_id: str,
    request: MemoryPromotionApprovalRequest,
) -> MemoryPromotionResponseItem:
    """Approve a pending memory promotion, optionally with edited text."""
    try:
        proposal_store = get_proposal_store()
        proposal = proposal_store.get_memory_proposal(proposal_id)
        entry = request.edited_entry if request.edited_entry is not None else proposal.entry
        target_file_name = request.target_file_name or proposal.target_file_name
        if request.edited_entry is not None or request.target_file_name is not None:
            proposal = proposal_store.update_memory_proposal_entry(
                proposal_id,
                target_file_name=target_file_name,
                entry=entry,
            )
        get_memory_service().append_memory_entry(
            proposal.target_file_name,
            entry,
        )
        proposal = proposal_store.mark_memory_proposal_status(proposal_id, "approved")
        return _memory_proposal_to_response(proposal)
    except MemoryFileBackpressureError as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "message": str(exc),
                "file_name": exc.file_name,
                "cap_bytes": exc.cap_bytes,
                "attempted_bytes": exc.attempted_bytes,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/promotions/{proposal_id}/decline", response_model=MemoryPromotionResponseItem)
async def decline_memory_promotion(proposal_id: str) -> MemoryPromotionResponseItem:
    """Decline a pending memory promotion."""
    try:
        proposal = get_proposal_store().mark_memory_proposal_status(proposal_id, "declined")
        return _memory_proposal_to_response(proposal)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/skill-candidates", response_model=SkillCandidateListResponse)
async def list_pending_skill_candidates() -> SkillCandidateListResponse:
    """List pending user-reviewable skill candidates."""
    return SkillCandidateListResponse(
        candidates=[
            _skill_candidate_to_response(candidate)
            for candidate in get_proposal_store().list_pending_skill_candidates()
        ]
    )


@router.post("/skill-candidates/{candidate_id}/approve", response_model=SkillCandidateResponseItem)
async def approve_skill_candidate(
    candidate_id: str,
    request: SkillCandidateApprovalRequest,
) -> SkillCandidateResponseItem:
    """Approve a pending skill candidate, optionally with edited fields."""
    _reject_if_reconciliation_active()
    try:
        proposal_store = get_proposal_store()
        candidate = proposal_store.get_skill_candidate(candidate_id)
        skill_service = get_skill_service()
        if candidate.status == "approved":
            if candidate.approved_skill_slug:
                try:
                    skill_service.load_skill(
                        candidate.approved_skill_slug,
                        mark_used=False,
                    )
                except SkillNotFoundError:
                    pass
                else:
                    return _skill_candidate_to_response(candidate)
            raise HTTPException(
                status_code=409,
                detail={"message": "This skill candidate has already been reviewed."},
            )
        if candidate.status != "pending":
            raise HTTPException(
                status_code=409,
                detail={"message": "This skill candidate has already been reviewed."},
            )
        if any(
            value is not None
            for value in (
                request.title,
                request.when_to_use,
                request.triggers,
                request.procedure_markdown,
            )
        ):
            candidate = proposal_store.update_skill_candidate(
                candidate_id,
                title=request.title or candidate.title,
                when_to_use=request.when_to_use or candidate.when_to_use,
                triggers=request.triggers if request.triggers is not None else candidate.triggers,
                procedure_markdown=request.procedure_markdown or candidate.procedure_markdown,
            )
        skill = skill_service.save_skill(
            title=candidate.title,
            body=candidate.procedure_markdown,
            when_to_use=candidate.when_to_use,
            triggers=candidate.triggers,
            source_task_ids=candidate.source_task_ids,
            slug=candidate.enhances_skill_slug,
            creation_origin_key=f"skill-candidate:{candidate_id}",
        )
        try:
            candidate = proposal_store.mark_skill_candidate_approved(candidate_id, skill.slug)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"message": "This skill candidate has already been reviewed."},
            ) from exc
        return _skill_candidate_to_response(candidate)
    except SkillBackpressureError as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "message": str(exc),
                "slug": exc.slug,
                "cap_bytes": exc.cap_bytes,
                "attempted_bytes": exc.attempted_bytes,
            },
        ) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/skill-candidates/{candidate_id}/decline", response_model=SkillCandidateResponseItem)
async def decline_skill_candidate(candidate_id: str) -> SkillCandidateResponseItem:
    """Decline a pending skill candidate."""
    _reject_if_reconciliation_active()
    try:
        candidate = get_proposal_store().mark_skill_candidate_status(candidate_id, "declined")
        return _skill_candidate_to_response(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/skills", response_model=SkillListResponse)
async def list_skills() -> SkillListResponse:
    """List saved user-approved skills."""
    return SkillListResponse(
        skills=[
            _skill_catalog_entry_to_response(skill)
            for skill in get_skill_service().list_catalog_entries()
        ]
    )


@router.get("/skills/{slug}", response_model=SkillResponseItem)
async def get_skill(slug: str) -> SkillResponseItem:
    """Read a saved skill."""
    try:
        return _skill_record_to_response(get_skill_service().load_skill(slug, mark_used=False))
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/skills/{slug}", response_model=SkillResponseItem)
async def update_skill(slug: str, request: SkillUpdateRequest) -> SkillResponseItem:
    """Update a saved skill body and metadata."""
    _reject_if_reconciliation_active()
    try:
        skill = get_skill_service().save_skill(
            slug=slug,
            title=request.title,
            body=request.body,
            when_to_use=request.when_to_use,
            triggers=request.triggers,
        )
        return _skill_record_to_response(skill)
    except SkillBackpressureError as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "message": str(exc),
                "slug": exc.slug,
                "cap_bytes": exc.cap_bytes,
                "attempted_bytes": exc.attempted_bytes,
            },
        ) from exc


@router.delete("/skills/{slug}")
async def delete_skill(slug: str) -> Dict[str, bool]:
    """Delete a saved skill."""
    _reject_if_reconciliation_active()
    if not get_skill_service().delete_skill(slug):
        raise HTTPException(status_code=404, detail=f"Skill '{slug}' was not found.")
    return {"deleted": True}


@router.get("/search", response_model=MemorySearchResponse)
async def search_memory(query: str, max_results: int = 20) -> MemorySearchResponse:
    """Search managed working memory and user overflow markdown files."""
    results = get_memory_service().search_memory(query, max_results=max_results)
    return MemorySearchResponse(
        results=[
            MemorySearchResponseItem(
                file_name=result.file_name,
                line_number=result.line_number,
                line=result.line,
            )
            for result in results
        ]
    )


@router.get("/{file_name}", response_model=MemoryDocumentResponse)
async def get_memory_document(file_name: str) -> MemoryDocumentResponse:
    """Read one managed working-memory document."""
    try:
        document = get_memory_service().read_memory_file(file_name)
        return _document_to_response(document)
    except MemoryFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{file_name}", response_model=MemoryDocumentResponse)
async def update_memory_document(
    file_name: str,
    request: MemoryDocumentUpdateRequest,
) -> MemoryDocumentResponse:
    """Replace one managed working-memory document."""
    try:
        document = get_memory_service().replace_memory_file(file_name, request.content)
        return _document_to_response(document)
    except MemoryFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MemoryFileBackpressureError as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "message": str(exc),
                "file_name": exc.file_name,
                "cap_bytes": exc.cap_bytes,
                "attempted_bytes": exc.attempted_bytes,
            },
        ) from exc


def _document_to_response(document) -> MemoryDocumentResponse:
    return MemoryDocumentResponse(
        file_name=document.file_name,
        content=document.content,
        size_bytes=document.size_bytes,
        cap_bytes=document.cap_bytes,
    )


def _memory_proposal_to_response(proposal) -> MemoryPromotionResponseItem:
    return MemoryPromotionResponseItem(
        id=proposal.id,
        target_file_name=proposal.target_file_name,
        entry=proposal.entry,
        why=proposal.why,
        confidence=proposal.confidence,
        source=proposal.source,
        created_at=proposal.created_at,
        status=proposal.status,
    )


def _skill_record_to_response(skill) -> SkillResponseItem:
    source_task_ids = [
        task_id for task_id in skill.metadata.get("source_task_ids", []) if task_id
    ]
    return SkillResponseItem(
        slug=skill.slug,
        title=str(skill.metadata.get("title") or skill.slug),
        body=skill.body,
        when_to_use=str(skill.metadata.get("when_to_use") or ""),
        triggers=[
            str(trigger)
            for trigger in skill.metadata.get("triggers", [])
            if isinstance(trigger, str)
        ],
        size_bytes=skill.size_bytes,
        cap_bytes=skill.cap_bytes,
        last_used=skill.metadata.get("last_used"),
        observation_count=int(skill.metadata.get("observation_count") or len(source_task_ids) or 1),
        version=int(skill.metadata.get("version") or 1),
    )


def _skill_catalog_entry_to_response(skill) -> SkillCatalogResponseItem:
    return SkillCatalogResponseItem(
        slug=skill.slug,
        title=skill.title,
        when_to_use=skill.when_to_use,
        triggers=skill.triggers,
        size_bytes=skill.size_bytes,
        cap_bytes=SKILL_BODY_CAP_BYTES,
        last_used=skill.last_used,
        observation_count=skill.observation_count,
        version=skill.version,
    )


def _skill_candidate_to_response(candidate) -> SkillCandidateResponseItem:
    return SkillCandidateResponseItem(
        id=candidate.id,
        title=candidate.title,
        when_to_use=candidate.when_to_use,
        triggers=candidate.triggers,
        procedure_markdown=candidate.procedure_markdown,
        expected_result=candidate.expected_result,
        source_task_ids=candidate.source_task_ids,
        source=candidate.source,
        created_at=candidate.created_at,
        status=candidate.status,
        enhances_skill_slug=candidate.enhances_skill_slug,
        observation_count=candidate.observation_count,
        approved_skill_slug=candidate.approved_skill_slug,
    )
