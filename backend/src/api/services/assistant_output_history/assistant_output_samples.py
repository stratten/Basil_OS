"""Writing-sample state and saving for Assistant History rows."""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from api.core.knowledge.personalization.session_sample_context import (
    EDITABLE_SAMPLE_CONTEXT_TYPES,
    map_session_context_type,
)
from api.core.knowledge.personalization_models import ContextType, SourceType


def _candidate_contents(detail: Dict[str, Any]) -> List[str]:
    refinements = detail.get("refinements") or []
    candidates = [detail.get("output_text") or ""]
    candidates += [refinement.get("output") or "" for refinement in refinements if isinstance(refinement, dict)]
    return [candidate for candidate in candidates if candidate]


async def attach_sample_state(detail: Dict[str, Any], personalization) -> Dict[str, Any]:
    """Add ``sample_context_type`` and ``saved_sample`` to a History detail payload."""
    sample_context = map_session_context_type(detail.get("context_type"))
    detail["sample_context_type"] = sample_context.value if sample_context else None
    sample = await personalization.find_sample_for_assistant_output(detail["id"], _candidate_contents(detail))
    detail["saved_sample"] = (
        {"id": sample.id, "content": sample.content, "context_type": ContextType(sample.context_type).value}
        if sample
        else None
    )
    return detail


async def save_assistant_output_as_sample(
    detail: Dict[str, Any],
    content: str,
    requested_context_type: Optional[str],
    personalization,
) -> Dict[str, Any]:
    """Save History output text as a writing sample linked to its History row."""
    if not content.strip():
        raise HTTPException(status_code=400, detail="Writing sample content cannot be empty")

    context_type = map_session_context_type(detail.get("context_type"))
    if context_type is None:
        try:
            context_type = ContextType(requested_context_type) if requested_context_type else None
        except ValueError:
            context_type = None
        if context_type not in EDITABLE_SAMPLE_CONTEXT_TYPES:
            raise HTTPException(status_code=400, detail="Choose a writing context for this sample")

    source_type = (
        SourceType.ASSISTANT_SESSION_ACCEPTED
        if detail.get("output_type") == "assistant_session"
        else SourceType.SUGGESTION_ACCEPTED
    )
    sample = await personalization.add_writing_sample(
        content=content,
        source_type=source_type,
        context_type=context_type,
        recipient=detail.get("recipient"),
        app_name=detail.get("app_name"),
        assistant_output_id=detail["id"],
    )
    return {
        "status": "saved",
        "sample_id": sample.id,
        "content": sample.content,
        "context_type": ContextType(sample.context_type).value,
    }
