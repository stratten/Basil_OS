"""Turns one entry plus its source material into a narrative via a model.

Model access mirrors activity_summarizer.generate_activity_summary: resolve a
reasoning model through ModelUsageService, honoring an explicit model id, then
call generate_response. The reply must contain a JSON body matching
NarrativePayload and a narrative within MAX_NARRATIVE_CHARS; anything else fails
the entry rather than being persisted, because memory_bridge feeds narrative
text into ActivitySignal.summary.

Generation length and output length are deliberately separate concerns. The token
ceiling exists only to stop a runaway and gives a reasoning model room to reason
as long as it needs; the stored summary is held to the length the prompt asks
for, and a model that ignores it is rejected for retry rather than trimmed.

Nothing here knows how any model marks its reasoning. Each adapter strips its own
markers and raises ReasoningTruncatedError when a model never reached an answer,
so this module only asks whether a parseable, in-contract narrative arrived.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, ValidationError

from api.core.models.model_invocation import call_model_with_prompt
from api.core.models.model_types import ModelCapability
from api.services.agent_processing.shared import extract_balanced_json
from api.services.zettel.narrative.prompt import MAX_NARRATIVE_CHARS, build_prompt

logger = logging.getLogger(__name__)

# MAX_NARRATIVE_CHARS is imported from prompt rather than redefined: the prompt
# states the limit to the model and this module enforces it on the reply, so both
# must read the same number.
GENERATION_TOKEN_CEILING = 8_192


@dataclass(frozen=True)
class SynthesisResult:
    narrative: str
    model_name: Optional[str]


class SynthesisError(RuntimeError):
    """Raised when no model was available or generation produced nothing."""


async def synthesize(
    entry: Dict[str, Any],
    context: Dict[str, Any],
    *,
    model_id: Optional[str] = None,
    model_stage_semaphore: Optional[asyncio.Semaphore] = None,
) -> SynthesisResult:
    from api.dependencies import get_model_usage_service

    async def acquire_model():
        return await get_model_usage_service().get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=model_id or None,
        )

    # Serializing only model acquisition lets concurrent API generations overlap while still protecting local model selection/loading from competing calls.
    if model_stage_semaphore is not None:
        async with model_stage_semaphore:
            model = await acquire_model()
    else:
        model = await acquire_model()
    if model is None:
        raise SynthesisError("No reasoning model available for narrative synthesis")

    prompt = build_prompt(entry, context)
    raw = await call_model_with_prompt(
        model,
        prompt=prompt,
        purpose="narrative",
        max_tokens=GENERATION_TOKEN_CEILING,
        enable_web_search=False,
    )
    if not raw or not str(raw).strip():
        raise SynthesisError("Model returned an empty narrative")

    return _parse(str(raw), model_id or _model_label(model))


class NarrativePayload(BaseModel):
    """The JSON body a narrative reply must contain.

    Safe defaults mirror ActivityAnalysis so a partially populated object still
    validates; the caller separately enforces a non-empty narrative.
    """
    narrative: str = ""


def _model_label(model: Any) -> Optional[str]:
    """Best-effort model identity for the narrative_model audit column.

    LlamaCppModel is built from a path and exposes neither model_name nor name,
    which is why every narrative_model landed NULL; fall back to the class name
    so the column always says something.
    """
    for attribute in ("model_name", "name"):
        value = getattr(model, attribute, None)
        if isinstance(value, str) and value.strip():
            return value
    return type(model).__name__


def _parse(raw: str, model_name: Optional[str]) -> SynthesisResult:
    payload = _extract_payload(raw)
    if payload is None:
        raise SynthesisError("Model reply contained no JSON object with a narrative")
    try:
        validated = NarrativePayload.model_validate(payload)
    except ValidationError as exc:
        raise SynthesisError(f"Narrative payload failed validation: {exc}") from exc

    narrative = validated.narrative.strip()
    if not narrative:
        raise SynthesisError("Narrative payload carried an empty narrative")
    if len(narrative) > MAX_NARRATIVE_CHARS:
        # Rejected rather than truncated: a cut-off summary reads as though the
        # model trailed off, and memory_bridge feeds this text to the evaluator.
        # SynthesisError leaves the entry pending for another swing.
        raise SynthesisError(
            f"Narrative ran {len(narrative)} characters against a "
            f"{MAX_NARRATIVE_CHARS}-character limit; the model ignored the "
            "length contract"
        )
    return SynthesisResult(
        narrative=narrative,
        model_name=model_name,
    )


def _extract_payload(raw: str) -> Optional[Dict[str, Any]]:
    """Find the JSON body of a reply that may carry prose around it.

    Mirrors ImageProcessor._parse_activity_analysis: try the whole reply first,
    then fall back to bracket-balanced extraction, gating every candidate on a
    structural sentinel so a span covering two objects plus the prose between
    them can never be accepted. extract_balanced_json is used rather than
    robust_json_loads because the latter strips non-ASCII and would mangle
    narrative prose.
    """
    try:
        direct = json.loads(raw)
    except ValueError:
        direct = None
    if _has_narrative(direct):
        return direct

    extracted = extract_balanced_json(raw)
    return extracted if _has_narrative(extracted) else None


def _has_narrative(candidate: Any) -> bool:
    """The structural sentinel: a dict carrying a non-empty narrative string."""
    if not isinstance(candidate, dict):
        return False
    narrative = candidate.get("narrative")
    return isinstance(narrative, str) and bool(narrative.strip())
