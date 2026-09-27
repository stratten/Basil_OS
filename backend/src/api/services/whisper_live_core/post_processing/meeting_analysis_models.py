"""
Data models for meeting analysis results.

Defines structured types for various analysis modes including action items,
decisions, questions/answers, sentiment, and custom analysis.
"""
import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AnalysisMode(str, Enum):
    """Available analysis modes for meeting transcripts."""
    ACTION_ITEMS = "action_items"
    SUGGESTED_ACTIONS = "suggested_actions"
    SUMMARY = "summary"
    DECISIONS = "decisions"
    QUESTIONS = "questions"
    SENTIMENT = "sentiment"
    CUSTOM = "custom"


class AnalysisContractModel(BaseModel):
    """Strict object produced directly by an analysis model."""

    model_config = ConfigDict(extra="forbid")


class ActionItem(AnalysisContractModel):
    """Represents a single action item extracted from the meeting."""
    task: str = Field(description="Description of the task or action item")
    assigned_to: Optional[str] = Field(default=None, description="Person assigned to the task")
    deadline: Optional[str] = Field(default=None, description="Deadline or due date if mentioned")
    priority: Optional[str] = Field(default=None, description="Priority level (high, medium, low)")
    context: str = Field(description="Relevant excerpt from transcript providing context")
    timestamp: float = Field(description="Timestamp in seconds when the action item was mentioned")
    speaker: Optional[str] = Field(default=None, description="Speaker who mentioned the action item")


class Decision(AnalysisContractModel):
    """Represents a key decision made during the meeting."""
    decision: str = Field(description="The decision that was made")
    rationale: Optional[str] = Field(default=None, description="Reasoning behind the decision")
    decided_by: Optional[str] = Field(default=None, description="Person or group who made the decision")
    timestamp: float = Field(description="Timestamp in seconds when the decision was made")
    context: str = Field(description="Relevant excerpt from transcript")
    impact: Optional[str] = Field(default=None, description="Expected impact or implications")


class QuestionAnswer(AnalysisContractModel):
    """Represents a question and its answer from the meeting."""
    question: str = Field(description="The question that was asked")
    answer: str = Field(description="The answer that was provided")
    asker: Optional[str] = Field(default=None, description="Person who asked the question")
    responder: Optional[str] = Field(default=None, description="Person who answered")
    timestamp: float = Field(description="Timestamp in seconds when the question was asked")
    context: str = Field(description="Full conversation excerpt")
    resolved: bool = Field(default=True, description="Whether the question was fully answered")


class SentimentAnalysis(AnalysisContractModel):
    """Sentiment analysis results for the meeting."""
    overall_sentiment: str = Field(description="Overall meeting sentiment (positive, neutral, negative)")
    sentiment_score: float = Field(description="Sentiment score from -1.0 (negative) to 1.0 (positive)")
    engagement_level: str = Field(description="Overall engagement level (high, medium, low)")
    
    # Per-speaker sentiment
    speaker_sentiments: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description="Sentiment breakdown per speaker"
    )
    
    # Key moments
    positive_moments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Most positive moments in the meeting"
    )
    negative_moments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Most negative or tense moments"
    )
    
    # Additional insights
    tone_indicators: Optional[List[str]] = Field(
        default=None,
        description="Key tone indicators observed (collaborative, contentious, formal, etc.)"
    )


class SuggestedActionDraft(AnalysisContractModel):
    """Model-owned portion of a suggested Basil follow-up."""

    source_action_item_indexes: List[int] = Field(default_factory=list)
    source_action_item_index: Optional[int] = None
    source_task: str
    source_context: Optional[str] = Field(
        default=None,
        description="One or more complete supporting transcript lines copied verbatim with their bracketed timestamps and speaker labels"
    )
    source_timestamp: Optional[float] = Field(
        default=None,
        description="Timestamp in seconds of the first verbatim source_context line"
    )
    source_speaker: Optional[str] = Field(
        default=None,
        description="Exact speaker label when every source_context line has the same speaker, otherwise null"
    )
    suggested_agent_task: str
    capability_type: str = "needs_clarification"
    confidence: float = 0.0
    why_basil_can_help: str
    missing_information: List[str] = Field(default_factory=list)
    requires_user_confirmation: bool = True
    disposition: Literal["todo_candidate", "completed_or_resolved", "non_actionable"]
    execution_mode: Literal["todo_only", "agent_assisted"] = "agent_assisted"


class MeetingActionProposal(BaseModel):
    """Represents a meeting-derived action Basil can help perform."""
    id: str = Field(description="Stable backend-generated identifier for this proposal")
    source_action_item_indexes: List[int] = Field(
        default_factory=list,
        description="Zero-based indexes of the action items consolidated into this proposal",
    )
    source_action_item_index: Optional[int] = Field(
        default=None,
        description="Zero-based index of the source action item, if derived from one"
    )
    source_task: str = Field(description="Original action item or transcript-derived task")
    source_context: Optional[str] = Field(
        default=None,
        description="One or more complete supporting transcript lines copied verbatim with their bracketed timestamps and speaker labels"
    )
    source_timestamp: Optional[float] = Field(
        default=None,
        description="Timestamp in seconds of the first verbatim source_context line"
    )
    source_speaker: Optional[str] = Field(
        default=None,
        description="Exact speaker label when every source_context line has the same speaker, otherwise null"
    )
    suggested_agent_task: str = Field(description="Exact agent task prompt Basil should submit if approved")
    capability_type: str = Field(
        description=(
            "Capability category such as email_draft, calendar_event, reminder, "
            "document_work, research, file_operation, automation, "
            "scheduled_agent_task, needs_clarification, or not_actionable"
        )
    )
    confidence: float = Field(description="Confidence from 0.0 to 1.0 that Basil can assist usefully")
    why_basil_can_help: str = Field(description="Short explanation of why Basil can help with this proposal")
    missing_information: List[str] = Field(
        default_factory=list,
        description="Information the user should provide before this can be executed safely"
    )
    requires_user_confirmation: bool = Field(
        default=True,
        description="Whether the proposal requires explicit user approval before action"
    )
    disposition: Literal["todo_candidate"] = "todo_candidate"
    execution_mode: Literal["todo_only", "agent_assisted"] = "agent_assisted"
    workspace_source: str = Field(
        default="meeting_analysis",
        description="Source namespace for future centralized agent workspace ingestion"
    )
    execution_status: str = Field(
        default="proposed",
        description="Local/workspace execution state: proposed, submitted, completed, failed, dismissed, or added_to_todos"
    )
    submitted_agent_task_id: Optional[str] = Field(
        default=None,
        description="Agent task id after this proposal is submitted for execution"
    )
    todo_id: Optional[str] = Field(
        default=None,
        description="Durable To-Do id after this proposal is promoted via /api/v1/todos/meeting-proposals/promote"
    )


class ActionItemsAnalysisResponse(AnalysisContractModel):
    items: List[ActionItem] = Field(default_factory=list)


class SuggestedActionsAnalysisResponse(AnalysisContractModel):
    items: List[SuggestedActionDraft] = Field(default_factory=list)


class SummaryAnalysisResponse(AnalysisContractModel):
    markdown: str


class DecisionsAnalysisResponse(AnalysisContractModel):
    items: List[Decision] = Field(default_factory=list)


class QuestionsAnalysisResponse(AnalysisContractModel):
    items: List[QuestionAnswer] = Field(default_factory=list)


class SentimentAnalysisResponse(AnalysisContractModel):
    analysis: SentimentAnalysis


class CustomAnalysisResponse(AnalysisContractModel):
    content: str


ANALYSIS_RESPONSE_MODELS: Dict[AnalysisMode, type[AnalysisContractModel]] = {
    AnalysisMode.ACTION_ITEMS: ActionItemsAnalysisResponse,
    AnalysisMode.SUGGESTED_ACTIONS: SuggestedActionsAnalysisResponse,
    AnalysisMode.SUMMARY: SummaryAnalysisResponse,
    AnalysisMode.DECISIONS: DecisionsAnalysisResponse,
    AnalysisMode.QUESTIONS: QuestionsAnalysisResponse,
    AnalysisMode.SENTIMENT: SentimentAnalysisResponse,
    AnalysisMode.CUSTOM: CustomAnalysisResponse,
}


def build_action_proposals(
    drafts: List[SuggestedActionDraft],
    *,
    meeting_id: str,
) -> List[MeetingActionProposal]:
    """Assign stable backend-owned fields after final reconciliation."""
    proposals: List[MeetingActionProposal] = []
    for draft in drafts:
        item = draft.model_dump(mode="python")
        if item["disposition"] != "todo_candidate":
            continue
        source_task = str(
            item.get("source_task") or item.get("suggested_agent_task") or ""
        ).strip()
        suggested_agent_task = str(
            item.get("suggested_agent_task") or source_task
        ).strip()
        if not source_task or not suggested_agent_task:
            continue
        source_action_item_indexes = list(
            dict.fromkeys(item.get("source_action_item_indexes") or [])
        )
        source_action_item_index = item.get("source_action_item_index")
        if not source_action_item_indexes and source_action_item_index is not None:
            source_action_item_indexes = [source_action_item_index]
        item["id"] = _stable_proposal_id(
            meeting_id,
            source_action_item_indexes,
            source_task,
            suggested_agent_task,
        )
        item["source_action_item_indexes"] = source_action_item_indexes
        item["source_action_item_index"] = (
            source_action_item_indexes[0] if source_action_item_indexes else None
        )
        item["source_task"] = source_task
        item["suggested_agent_task"] = suggested_agent_task
        item["confidence"] = _normalize_confidence(item.get("confidence", 0.0))
        item["workspace_source"] = "meeting_analysis"
        item["execution_status"] = "proposed"
        item["submitted_agent_task_id"] = None
        proposals.append(MeetingActionProposal(**item))
    return proposals


def _stable_proposal_id(
    meeting_id: str,
    source_action_item_indexes: List[int],
    source_task: str,
    suggested_agent_task: str,
) -> str:
    proposal_id_seed = "|".join(
        [
            meeting_id,
            json.dumps(source_action_item_indexes, separators=(",", ":")),
            source_task,
            suggested_agent_task,
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, proposal_id_seed))


def _normalize_confidence(raw_confidence: Any) -> float:
    try:
        return min(1.0, max(0.0, float(raw_confidence)))
    except (TypeError, ValueError):
        return 0.0


class AnalysisSafetyOmission(BaseModel):
    """A provider-refused transcript range excluded from one recovered mode."""

    mode: str
    start_timestamp: float
    end_timestamp: float
    segment_count: int
    provider: str
    refusal_category: Optional[str] = None
    refusal_explanation: Optional[str] = None
    recovery: str


class AnalysisModeFailure(BaseModel):
    """Durable terminal outcome for one requested analysis mode."""

    mode: str
    category: str
    message: str
    retryable: bool
    refusal_category: Optional[str] = None
    refusal_explanation: Optional[str] = None


class MeetingAnalysisResult(BaseModel):
    """Complete analysis results for a meeting."""
    meeting_id: str = Field(description="UUID of the meeting")
    analyzed_at: datetime = Field(description="When the analysis was performed")
    model_used: str = Field(description="LLM model used for analysis")
    fallback_model_used: Optional[str] = Field(
        default=None,
        description=(
            "Set only when the preferred reasoning model was unreachable before any "
            "analysis mode succeeded and this run automatically substituted the "
            "user-designated local fallback model; identical to model_used in that case."
        ),
    )
    requested_modes: List[str] = Field(default_factory=list)
    modes_analyzed: List[str] = Field(default_factory=list)
    failed_modes: List[AnalysisModeFailure] = Field(default_factory=list)
    safety_omissions: List[AnalysisSafetyOmission] = Field(default_factory=list)
    custom_instructions: Optional[str] = Field(default=None, description="Custom instructions provided by user")
    
    # Mode-specific results
    action_items: Optional[List[ActionItem]] = Field(default=None, description="Extracted action items")
    suggested_actions: Optional[List[MeetingActionProposal]] = Field(
        default=None,
        description="Agent-task proposals Basil can help perform from the meeting"
    )
    summary: Optional[str] = Field(default=None, description="Meeting summary")
    decisions: Optional[List[Decision]] = Field(default=None, description="Key decisions made")
    questions_answers: Optional[List[QuestionAnswer]] = Field(default=None, description="Q&A pairs")
    sentiment_analysis: Optional[SentimentAnalysis] = Field(default=None, description="Sentiment analysis")
    custom_analysis: Optional[str] = Field(default=None, description="Custom analysis based on user instructions")
    structured_output_enforcement: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Schema enforcement modes used by each completed analysis mode",
    )
    
    # Metadata
    transcript_duration: float = Field(description="Duration of the transcript in seconds")
    speaker_count: int = Field(description="Number of unique speakers identified")
    processing_time: float = Field(description="Time taken to perform the analysis in seconds")
    
    # Meeting metadata
    meeting_name: Optional[str] = Field(default=None, description="Name of the meeting")
    meeting_purpose: Optional[str] = Field(default=None, description="Purpose of the meeting")
    participants: Optional[List[str]] = Field(default=None, description="List of participants")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return self.model_dump(mode='json', exclude_none=False)
    
    def get_completed_modes(self) -> List[str]:
        """Get list of modes that produced results."""
        completed = []
        if self.action_items:
            completed.append(AnalysisMode.ACTION_ITEMS.value)
        if self.suggested_actions:
            completed.append(AnalysisMode.SUGGESTED_ACTIONS.value)
        if self.summary:
            completed.append(AnalysisMode.SUMMARY.value)
        if self.decisions:
            completed.append(AnalysisMode.DECISIONS.value)
        if self.questions_answers:
            completed.append(AnalysisMode.QUESTIONS.value)
        if self.sentiment_analysis:
            completed.append(AnalysisMode.SENTIMENT.value)
        if self.custom_analysis:
            completed.append(AnalysisMode.CUSTOM.value)
        return completed


class AnalysisProgress(BaseModel):
    """Progress information for ongoing analysis."""
    stage: str = Field(description="Current stage: loading, analyzing_{mode}, complete")
    stage_progress: float = Field(description="Progress within current stage (0.0 to 1.0)")
    overall_progress: float = Field(description="Overall progress (0.0 to 1.0)")
    current_mode: Optional[str] = Field(default=None, description="Current mode being analyzed")
    completed_modes: List[str] = Field(default_factory=list, description="Modes that have been completed")
    total_modes: int = Field(description="Total number of modes to analyze")
    message: str = Field(description="Human-readable status message")
    eta_seconds: float = Field(default=0.0, description="Estimated time remaining in seconds")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return self.model_dump(mode='json')
