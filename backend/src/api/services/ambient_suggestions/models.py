"""Typed models for ambient suggestions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

AmbientCapability = Literal["assistant_session", "agent_task"]
AmbientMode = Literal["suggestion_only", "auto_execute"]
SuggestionOutcome = Literal["suggested", "accepted", "rejected", "dismissed", "auto_executed"]
AmbientPrimaryActivity = Literal[
    "editing_code",
    "reviewing_logs",
    "reading_message",
    "writing_document",
    "browsing",
    "using_basil_ui",
    "other",
    "unknown",
]
AmbientEvidenceSource = Literal["app_name", "window_title", "ocr_text", "basil_ui", "unknown"]
AmbientSuggestionType = Literal[
    "none",
    "draft_reply",
    "complete_partial_reply",
    "explain_error",
    "summarize_visible_code",
    "draft_test",
    "review_visible_change",
    "complete_section",
    "tighten_requirements",
    "summarize_section",
    "extract_action_items",
    "summarize_page",
    "compare_options",
    "extract_notes",
]


class AmbientContextEnvelope(BaseModel):
    capture_id: str
    timestamp: datetime
    app_name: str
    window_title: str
    image_path: Optional[str] = None
    ocr_text: str = ""
    structured_context: Dict[str, Any] = Field(default_factory=dict)
    content_fingerprint: str


class AmbientRecentSuggestionContext(BaseModel):
    created_at: datetime
    outcome: SuggestionOutcome
    application: str
    window_title: str
    content_fingerprint: str
    capability: AmbientCapability
    suggestion_type: str
    title: str
    summary: str
    proposed_request: Optional[str] = None


class AmbientRecentActivitySpan(BaseModel):
    started_at: datetime
    ended_at: datetime
    app_name: str
    window_title: str
    capture_count: int = Field(ge=1)
    activity_ids: List[str] = Field(default_factory=list)
    text_excerpts: List[str] = Field(default_factory=list)


class AmbientEvaluationRequest(BaseModel):
    capture_id: str
    captured_at: datetime
    application: str
    window_title: str
    ocr_excerpt: str
    ocr_char_count: int = Field(ge=0)
    structured_context: Dict[str, Any] = Field(default_factory=dict)
    content_fingerprint: str
    recent_suggestion_types: List[str] = Field(default_factory=list)
    previously_rejected: bool = False
    recent_suggestions: List[AmbientRecentSuggestionContext] = Field(default_factory=list)
    recent_activity_spans: List[AmbientRecentActivitySpan] = Field(default_factory=list)
    allowed_capabilities: List[AmbientCapability] = Field(default_factory=lambda: ["assistant_session"])
    minimum_confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class AmbientEvaluationGrounding(BaseModel):
    application: str
    window_title: str
    visible_excerpt: str


class AmbientEvaluationResponse(BaseModel):
    should_suggest: bool = False
    no_suggestion_reason: Optional[str] = None
    capability: Optional[AmbientCapability] = None
    suggestion_type: AmbientSuggestionType = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    primary_activity: AmbientPrimaryActivity = "unknown"
    visible_context_summary: str = ""
    evidence: List[str] = Field(default_factory=list)
    evidence_sources: List[AmbientEvidenceSource] = Field(default_factory=list)
    title: str = ""
    summary: str = ""
    details: Optional[str] = None
    proposed_request: Optional[str] = None
    instruction: Optional[str] = None
    grounding: Optional[AmbientEvaluationGrounding] = None
    auto_execute_eligible: bool = False

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "AmbientEvaluationResponse":
        if not self.should_suggest:
            self.capability = None
            self.suggestion_type = "none"
            self.confidence = 0.0
            self.primary_activity = "unknown"
            self.visible_context_summary = ""
            self.evidence = []
            self.evidence_sources = []
            self.title = ""
            self.summary = ""
            self.details = None
            self.proposed_request = None
            self.instruction = None
            self.grounding = None
            self.auto_execute_eligible = False
            return self

        missing = []
        if not self.capability:
            missing.append("capability")
        if self.suggestion_type == "none":
            missing.append("suggestion_type")
        if self.primary_activity == "unknown":
            missing.append("primary_activity")
        if not self.visible_context_summary.strip():
            missing.append("visible_context_summary")
        if not self.evidence:
            missing.append("evidence")
        if not self.title.strip():
            missing.append("title")
        if not self.summary.strip():
            missing.append("summary")
        if not (self.proposed_request or "").strip():
            missing.append("proposed_request")
        if not (self.instruction or "").strip():
            missing.append("instruction")
        if not self.grounding:
            missing.append("grounding")
        elif not self.grounding.application.strip() or not self.grounding.window_title.strip() or not self.grounding.visible_excerpt.strip():
            missing.append("grounding")
        if missing:
            raise ValueError(f"Suggested Ambient response missing required fields: {', '.join(sorted(set(missing)))}")
        return self

    def to_payload(self) -> "AmbientSuggestionPayload":
        if not self.should_suggest:
            return AmbientSuggestionPayload(should_suggest=False, confidence=0.0)
        assert self.capability is not None
        assert self.instruction is not None
        assert self.grounding is not None
        context_text = (
            f"App: {self.grounding.application}\n"
            f"Window: {self.grounding.window_title}\n"
            f"Visible excerpt:\n{self.grounding.visible_excerpt}"
        )
        return AmbientSuggestionPayload(
            should_suggest=True,
            capability=self.capability,
            suggestion_type=self.suggestion_type,
            confidence=self.confidence,
            title=self.title,
            summary=self.summary,
            details=self.details,
            proposed_request=self.proposed_request,
            instruction=self.instruction,
            context_text=context_text,
            auto_execute_eligible=self.auto_execute_eligible,
        )


class AmbientSuggestionPayload(BaseModel):
    should_suggest: bool = False
    capability: Optional[AmbientCapability] = None
    suggestion_type: str = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    title: str = ""
    summary: str = ""
    details: Optional[str] = None
    proposed_request: Optional[str] = None
    instruction: Optional[str] = None
    context_text: Optional[str] = None
    auto_execute_eligible: bool = False


class AmbientSuggestionRecord(BaseModel):
    suggestion_id: str
    created_at: datetime
    content_fingerprint: str
    source_identifier: Optional[str] = None
    app_name: str
    window_title: str
    capability: AmbientCapability
    suggestion_type: str
    title: str
    summary: str
    details: Optional[str] = None
    proposed_request: Optional[str] = None
    instruction: str
    context_text: str
    confidence: float
    outcome: SuggestionOutcome = "suggested"
    auto_execute_eligible: bool = False
