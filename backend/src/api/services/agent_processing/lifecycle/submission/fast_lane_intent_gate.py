"""LLM-based intent gate for the context-only fast lane (P7).

Decides whether a follow-up agent task can be answered directly from the
existing conversation context/artifacts with no tool use, or whether it must
escalate to the full multi_step_workflow pipeline. This is a genuine model
judgment call via structured JSON output -- there must be no substring or
keyword matching anywhere in this decision.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from ..execution_graph.agent_json_decision import parse_json_object_response
from ..execution_graph.agent_model_caller import call_agent_model_with_messages

logger = logging.getLogger(__name__)

# Escalate whenever the gate isn't clearly confident -- default-to-full-
# pipeline-when-unsure. A mis-routed *discussion* only costs one extra cheap
# LLM call before falling into the normal pipeline; a mis-routed *execution*
# silently drops the user's requested action, which this threshold is tuned
# to avoid.
FAST_LANE_CONFIDENCE_THRESHOLD = 0.7

# Keep the decision cheap: this is a single non-streaming classification call.
_DECISION_MAX_TOKENS = 300
_DECISION_TIMEOUT_SECONDS = 6.0


@dataclass(frozen=True)
class FastLaneDecision:
    """The model's judgment about whether this follow-up needs tools."""

    can_answer_from_context: bool
    confidence: float
    reason: str

    @property
    def takes_fast_lane(self) -> bool:
        return self.can_answer_from_context and self.confidence >= FAST_LANE_CONFIDENCE_THRESHOLD


_ESCALATE_DECISION = FastLaneDecision(
    can_answer_from_context=False, confidence=0.0, reason="Escalated (no gate decision available)."
)


async def resolve_fast_lane_reasoning_model(model_id: str | None = None):
    """Resolve the reasoning model used by the fast-lane decision and response."""
    try:
        from api.core.models.model_types import ModelCapability
        from api.dependencies import get_model_service
        from api.services.model_usage_service import ModelUsageService

        model_usage_service = ModelUsageService(get_model_service())
        return await model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=model_id,
        )
    except Exception as exc:
        logger.info("Fast-lane model resolution failed: %s", exc)
        return None


async def evaluate_fast_lane_intent(
    model,
    user_request: str,
    conversation_history: str,
) -> FastLaneDecision:
    """Ask the model whether this follow-up can be answered purely from
    ``conversation_history`` with no tool use. Any failure (no model, bad
    JSON, timeout) resolves to escalation -- never guesses fast-lane on
    uncertainty.
    """
    if model is None:
        return _ESCALATE_DECISION

    system_message = (
        "You decide whether a user's follow-up message can be answered right now, "
        "purely from the conversation history already shown to you, with no new "
        "tool use, file access, or external action. Judge this semantically: "
        "consider whether answering would require anything not already present in "
        "the history (a new fact, a new file, a new action taken on the user's "
        "behalf) versus purely explaining, summarizing, or discussing what is "
        "already there.\n\n"
        "Respond with ONLY a JSON object and no other text, in exactly this shape:\n"
        '{"can_answer_from_context": <true or false>, "confidence": <0.0-1.0>, '
        '"reason": "<one short sentence>"}\n\n'
        "Set can_answer_from_context to false whenever the message asks for a new "
        "action (create/change/run/send/delete/search/open/etc.) or needs "
        "information not already present above. When genuinely unsure, prefer "
        "false and a lower confidence -- guessing true incorrectly silently drops "
        "the user's requested action."
    )

    user_message = (
        f"CONVERSATION SO FAR:\n{conversation_history}\n\n"
        f"USER'S NEW FOLLOW-UP:\n{user_request}\n\n"
        "Can this follow-up be answered directly from the conversation above, "
        "with no tool use?"
    )

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    try:
        response_text = await asyncio.wait_for(
            call_agent_model_with_messages(
                model,
                messages,
                enable_web_search=False,
                max_tokens=_DECISION_MAX_TOKENS,
            ),
            timeout=_DECISION_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.info("Fast-lane intent gate call failed or timed out; escalating. error=%s", exc)
        return _ESCALATE_DECISION

    try:
        payload = parse_json_object_response(response_text)
    except (TypeError, json.JSONDecodeError) as exc:
        preview = (str(response_text) or "").strip().replace("\n", "\\n")[:240]
        logger.info(
            "Fast-lane intent gate returned non-JSON; escalating. error=%s preview=%r",
            exc,
            preview,
        )
        return _ESCALATE_DECISION

    can_answer = bool(payload.get("can_answer_from_context"))
    reason = str(payload.get("reason") or "").strip() or "No reason provided."
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return FastLaneDecision(can_answer_from_context=can_answer, confidence=confidence, reason=reason)
