"""Request/response models for the Skill Reconciliation Workspace routes.

These mirror the in-memory dataclasses in ``reconciliation_session`` so the
routes can validate the session/action payloads FastAPI serializes to the web
app. Snapshot bodies stay as loose dicts because the underlying records evolve
independently and the workspace only renders them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProposedActionModel(BaseModel):
    """A single model-produced reconciliation proposal and its decision."""

    id: str
    kind: str
    source_candidate_ids: List[str] = Field(default_factory=list)
    target_skill_slug: Optional[str] = None
    rationale: str = ""
    merged_title: Optional[str] = None
    merged_when_to_use: Optional[str] = None
    merged_triggers: List[str] = Field(default_factory=list)
    merged_procedure_markdown: Optional[str] = None
    merged_expected_result: Optional[str] = None
    merged_source_task_ids: List[str] = Field(default_factory=list)
    decision: str = "pending"
    user_edited: Optional[Dict[str, Any]] = None


class SessionSnapshotModel(BaseModel):
    """The captured skill state a session is reconciling."""

    captured_at: str
    pending_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    saved_skills: List[Dict[str, Any]] = Field(default_factory=list)
    min_observations: int = 2


class ReconciliationSessionModel(BaseModel):
    """Full session payload for hydrate/commit responses."""

    id: str
    status: str
    created_at: str
    updated_at: str
    snapshot: SessionSnapshotModel
    actions: List[ProposedActionModel] = Field(default_factory=list)
    progress: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
    commit_report: Optional[Dict[str, Any]] = None


class ReconciliationStatusModel(BaseModel):
    """Lightweight lock-state summary (no snapshot) for Settings."""

    active: bool
    session_id: Optional[str] = None
    status: Optional[str] = None
    pending_count: int = 0
    action_count: int = 0


class ActionEditFields(BaseModel):
    """Optional user overrides applied over the model's merged fields."""

    title: Optional[str] = None
    when_to_use: Optional[str] = None
    triggers: Optional[List[str]] = None
    procedure_markdown: Optional[str] = None
    expected_result: Optional[str] = None
    source_task_ids: Optional[List[str]] = None


class ActionDecisionRequest(BaseModel):
    """Accept/reject a proposed action, optionally with edited merged fields."""

    decision: str = Field(description="One of 'accepted', 'rejected', 'pending'.")
    edited: Optional[ActionEditFields] = None
