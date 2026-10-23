"""Prompts used to reconcile complete multi-chunk meeting analyses."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .meeting_analysis_coverage import TranscriptChunk
from .meeting_analysis_models import AnalysisMode


def build_chunk_analysis_instruction(mode: AnalysisMode, chunk: TranscriptChunk) -> str:
    """Tell a mode prompt its source is one bounded portion of a meeting."""
    return (
        f"\n\nCHUNK COVERAGE:\nThis is chunk {chunk.index} of {chunk.total}, covering "
        f"transcript segments {chunk.first_segment_index} through {chunk.last_segment_index}. "
        "Analyze only evidence in this chunk. Do not claim that you reviewed the whole meeting."
    )


def build_reduction_prompt(
    *,
    mode: AnalysisMode,
    chunk_results: List[Any],
    meeting_metadata: Dict[str, Any],
    custom_instructions: Optional[str],
) -> str:
    """Build a model-readable synthesis of every validated chunk response."""
    serialized = json.dumps(
        [_json_value(result) for result in chunk_results],
        ensure_ascii=False,
        indent=2,
    )
    metadata = "\n".join(
        f"- {key}: {value}"
        for key, value in meeting_metadata.items()
        if value not in (None, "", [], {})
        and key not in {"identity_block", "capability_digest"}
    )
    output_instruction = _output_instruction(mode)
    custom = (
        f"\n\nADDITIONAL USER INSTRUCTIONS:\n{custom_instructions}"
        if custom_instructions
        else ""
    )
    return f"""You are reconciling a complete meeting analysis.

MEETING CONTEXT:
{metadata or "- No additional metadata"}

Every transcript chunk has been reviewed. Combine the chunk-level findings below
into one complete result. Deduplicate only findings that describe the same event;
retain distinct findings, especially those from later chunks. Do not invent
evidence, timestamps, speakers, or outcomes.

CHUNK RESULTS:
{serialized}

{output_instruction}{custom}
"""


def _output_instruction(mode: AnalysisMode) -> str:
    if mode == AnalysisMode.SUGGESTED_ACTIONS:
        return (
            'Return one JSON object with an "items" array matching the chunk response contract. '
            "Classify findings by meeting outcome, not by individual checklist statement. "
            "Consolidate related chunk findings into one outcome-level candidate when they "
            "serve the same deliverable, system change, recipient, deadline, or workstream. "
            'Retain only records with disposition "todo_candidate"; do not return completed, '
            "resolved, informational, or non-actionable findings. For every retained "
            "candidate, union source_action_item_indexes without duplicates in chronological "
            "order and set source_action_item_index to the first retained index or null. "
            'Preserve execution_mode as "todo_only" or "agent_assisted". Use "agent_assisted" '
            "when Basil can safely make useful initial progress after approval, including "
            "research, drafting, planning, organizing information, inspecting available files, "
            "or working through a listed connection; missing follow-up details belong in "
            "missing_information rather than forcing todo_only. Use todo_only only when Basil "
            "cannot productively begin any part of the outcome. "
            "For every retained proposal, copy each source_context transcript line verbatim from "
            "the chunk results; never summarize, paraphrase, correct, or generate quote text. "
            "When evidence from multiple chunk results jointly informs one proposal, join only "
            "their unchanged source_context lines with newline characters in chronological order. "
            "Set source_timestamp to the timestamp in seconds of the first retained line. Preserve "
            "source_speaker only when every retained line has the same exact speaker label; "
            "otherwise set source_speaker to null."
        )
    if mode in {
        AnalysisMode.ACTION_ITEMS,
        AnalysisMode.DECISIONS,
        AnalysisMode.QUESTIONS,
    }:
        return (
            'Return one JSON object with an "items" array matching the '
            "chunk response contract."
        )
    if mode == AnalysisMode.SENTIMENT:
        return (
            'Return one JSON object with an "analysis" value matching the '
            "sentiment response contract."
        )
    if mode == AnalysisMode.SUMMARY:
        return (
            'Return one JSON object with the reconciled Markdown summary '
            'in "markdown".'
        )
    return (
        'Return one JSON object with the complete custom analysis in "content".'
    )


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value
