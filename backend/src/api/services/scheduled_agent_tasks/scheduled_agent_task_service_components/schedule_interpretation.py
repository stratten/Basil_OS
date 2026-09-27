"""LLM-driven natural-language scheduling interpretation.

Turns free-form text like "every day at 8pm review my emails" into a
structured ``InterpretedScheduleContract`` payload that the lifecycle layer
can persist + enqueue. Owns the multi-turn clarification thread store as
process-singleton module-level state.

Layering: depends only on ``schedule_time_math`` from the component package
plus generic helpers (model service, JSON parsing). It must NOT import the
lifecycle, execution, runtime, or facade modules; doing so would cycle.

Public surface (free functions; the facade re-exports / delegates):
    InterpretedScheduleContract              -- Pydantic shape the LLM emits.
    get_interpretation_model_id()            -- resolve preferred model id.
    build_interpretation_prompt(...)         -- assemble the LLM prompt.
    validate_interpreted_schedule_payload()  -- post-validate model output.
    interpret_schedule_prompt(...)           -- top-level entry; orchestrates
                                                model call, validation, and
                                                clarification threading.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from api.core.models.model_types import ModelCapability
from api.core.models.preferences import Preferences
from api.core.services.model_service import get_model_service
from api.services.agent_processing.shared.json_repair import robust_json_loads
from api.services.model_usage_service import ModelUsageService

from .schedule_time_math import (
    compute_next_run_at,
    detect_local_timezone_name,
    get_zone,
    utc_now,
)

logger = logging.getLogger(__name__)


# Per-process in-memory store for in-flight clarification threads. Keyed by
# an opaque context_id surfaced to the UI so a follow-up clarification turn
# can be linked back to its original prompt + question. Module-level (not
# class-level) because a fresh ``ScheduledAgentTaskService`` is constructed per
# HTTP request, but the clarification thread must persist across those
# instances for as long as the user is iterating on the same prompt.
_INTERPRETATION_CONTEXTS: Dict[str, Dict[str, Any]] = {}


class InterpretedScheduleContract(BaseModel):
    """Structured contract the LLM must emit when interpreting a schedule prompt."""

    title: str
    agent_task_text: str
    schedule_type: str
    schedule_config: Dict[str, Any]
    timezone: str
    needs_user_confirmation: bool = False
    clarification_question: Optional[str] = None
    confidence: float = 0.0


def get_interpretation_model_id() -> Optional[str]:
    """Resolve which configured model to use for schedule interpretation.

    Schedule interpretation is a structured-generation task (LLM emits a
    strict JSON contract describing a schedule), not a routing decision.
    It therefore should be driven by the user's preferred reasoning model.
    If no reasoning model is configured, return None so the caller can fall
    back to capability-based selection via ModelUsageService.

    Precedence:
      1. preferences.models.reasoning_model      (preferred)
      2. None  (capability-based pick by ModelUsageService)
    """
    try:
        preferences = Preferences.load()
        reasoning_model = (preferences.models.reasoning_model or "").strip()
        if reasoning_model:
            return reasoning_model
        return None
    except Exception:
        return None


def build_interpretation_prompt(
    user_prompt: str,
    *,
    user_timezone: str,
    user_now_iso: str,
    context: Optional[Dict[str, Any]] = None,
    validation_error: Optional[str] = None,
) -> str:
    # The user-context block is ALWAYS present. Without it, the LLM has no
    # way to resolve "8pm" to a real wall-clock time or "tomorrow" to a
    # real date, which historically forced unnecessary clarification
    # round-trips for completely unambiguous requests like "every day at
    # 8pm". Both fields are populated by interpret_schedule_prompt from
    # either the caller-supplied user_timezone or the autodetected host
    # zone.
    user_context_block = f"""
User context (use these as defaults; do NOT ask the user for any of this):
- User's local timezone (IANA): {user_timezone}
- User's current local time:    {user_now_iso}
"""

    context_block = ""
    if context:
        history_items = context.get("history", [])
        if not isinstance(history_items, list):
            history_items = []
        history_text = "\n".join(
            [f"- {entry}" for entry in history_items if isinstance(entry, str) and entry.strip()]
        ) or "- (no prior history)"
        last_question = context.get("last_clarification_question")
        last_question_text = (
            last_question
            if isinstance(last_question, str) and last_question.strip()
            else "(none)"
        )
        context_block = f"""

Prior context for this same scheduling thread:
{history_text}

Last clarification question asked:
{last_question_text}
"""

    correction_block = ""
    if validation_error:
        correction_block = f"""

Previous output failed validation:
{validation_error}

You MUST correct the JSON to satisfy the schema and rules below.
Do not repeat the same invalid structure.
"""

    return f"""You are an expert scheduling assistant for Basil.
{user_context_block}
Convert the user's natural-language scheduling intent into STRICT JSON matching this schema:
{{
  "title": "short human title",
  "agent_task_text": "the agent task Basil should execute",
  "schedule_type": "one_time" | "recurring",
  "schedule_config": {{
    // one_time:
    //   {{"run_at": "ISO-8601 datetime string with timezone or Z"}}
    //
    // recurring daily:
    //   {{"mode": "daily", "time": "HH:MM"}}
    //
    // recurring weekly:
    //   {{"mode": "weekly", "days": [0..6], "time": "HH:MM"}}  // Monday=0
    //
    // recurring interval:
    //   {{"mode": "interval", "minutes": <positive integer>}}
  }},
  "timezone": "IANA timezone string like America/New_York",
  "needs_user_confirmation": true | false,
  "clarification_question": "string or null",
  "confidence": 0.0-1.0
}}

Rules:
1) Return ONLY valid JSON, no markdown, no commentary.
2) If the user is ambiguous about WHAT to do, set needs_user_confirmation=true
   and include clarification_question. Ambiguity about timezone alone is NOT
   a reason to ask -- see rule 4.
3) Do not invent impossible details. Prefer clarification over guessing for
   actual content (the agent task itself, recurrence mode, day-of-week, etc).
4) timezone defaults to the "User's local timezone" supplied above. ALWAYS
   emit that value in the "timezone" field UNLESS the user explicitly names
   a different timezone in their request (e.g. "8pm Pacific", "every day at
   noon Tokyo time"). NEVER set needs_user_confirmation=true just because the
   user did not mention a timezone -- the supplied default is authoritative.
5) Resolve relative times ("tomorrow", "in 2 hours", "next Monday", "tonight")
   against the supplied "User's current local time", interpreted in the
   user's local timezone. Bare clock times like "8pm" mean 8pm in the user's
   local timezone unless the user says otherwise.
6) agent_task_text should preserve the actual task intent.
7) If prior context exists, treat the current message as a follow-up
   clarification in that same thread.
8) clarification_question must be specific about what is still missing
   (the agent task itself, recurrence mode, day-of-week, etc). It MUST NOT ask
   about timezone unless the user said something explicitly contradictory.
9) If there was a prior validation error, fix that exact issue and return
   corrected JSON only.

User request:
\"\"\"{user_prompt}\"\"\"{context_block}{correction_block}"""


def validate_interpreted_schedule_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    required = ["title", "agent_task_text", "schedule_type", "schedule_config", "timezone"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"Interpreted schedule output missing required fields: {missing}")

    title = str(payload["title"]).strip()
    agent_task_text = str(payload["agent_task_text"]).strip()
    schedule_type = str(payload["schedule_type"]).strip()
    timezone_name = str(payload["timezone"]).strip() or "UTC"
    schedule_config = payload["schedule_config"]

    if not title:
        raise ValueError("Generated schedule title is empty")
    if not agent_task_text:
        raise ValueError("Generated agent_task_text is empty")
    if schedule_type not in ("one_time", "recurring"):
        raise ValueError(f"Invalid schedule_type: {schedule_type}")
    if not isinstance(schedule_config, dict):
        raise ValueError("schedule_config must be an object")

    # Validate timezone format (fallback handled in runtime, but reject obviously bad output here).
    _ = get_zone(timezone_name)

    # Validate schedule payload by attempting to compute next run.
    next_run = compute_next_run_at(schedule_type, schedule_config, timezone_name)
    if next_run is None:
        raise ValueError("Generated schedule_config is invalid or incomplete")

    needs_confirmation = bool(payload.get("needs_user_confirmation", False))
    clarification_question = payload.get("clarification_question")
    confidence_raw = payload.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "title": title,
        "agent_task_text": agent_task_text,
        "schedule_type": schedule_type,
        "schedule_config": schedule_config,
        "timezone": timezone_name,
        "needs_user_confirmation": needs_confirmation,
        "clarification_question": clarification_question if isinstance(clarification_question, str) else None,
        "confidence": confidence,
    }


async def interpret_schedule_prompt(
    user_prompt: str,
    context_id: Optional[str] = None,
    *,
    user_timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """LLM-driven interpretation of a natural-language scheduling request.

    This is the single entry point for turning free-form text like
    "every day at 8pm review my emails" into a structured schedule
    definition that can be persisted and enqueued. Internally it:

      1. Resolves the user's timezone (caller-supplied -> host autodetect
         -> UTC fallback) and the user's current local time, and injects
         both into the LLM prompt as authoritative defaults so the model
         never needs to ask about timezone.
      2. Pulls the configured reasoning model and asks it to emit a
         strict JSON contract describing the schedule.
      3. Validates the returned JSON against
         ``InterpretedScheduleContract`` and against
         ``compute_next_run_at`` (so e.g. ``schedule_type="recurring"``
         with no ``mode`` is rejected). Allows one repair attempt where
         the validation error is fed back to the model.
      4. If the model legitimately needs more information (the *what*,
         not the timezone), persists the in-flight context under
         ``_INTERPRETATION_CONTEXTS[context_id]`` and raises
         ``ValueError`` with a structured ``Need clarification (context_id=...)``
         message that the route handler unpacks into a clarification
         response. A follow-up call with the same ``context_id`` plus the
         user's clarification text resumes the same thread.

    Args:
        user_prompt: Natural-language scheduling request from the user.
        context_id: Opaque ID linking follow-up clarification turns to
            the same in-memory conversation thread.
        user_timezone: IANA name of the timezone the user is operating in
            (e.g. "America/Los_Angeles"). When omitted (e.g. when the
            agent_task agent tool calls us without an explicit zone),
            we autodetect the host's local zone via
            ``detect_local_timezone_name``. The frontend always sends
            its currently-selected form timezone here so explicit user
            selection (e.g. picking Asia/Tokyo in the dropdown before
            describing the schedule) is honored.
    """
    text = (user_prompt or "").strip()
    if not text:
        raise ValueError("Prompt cannot be empty")

    # Resolve the timezone we'll feed the LLM. Order:
    #   1. Caller-supplied user_timezone (must be a valid IANA name).
    #   2. Host autodetection via /etc/localtime symlink.
    #   3. UTC fallback (only if both above fail).
    resolved_tz_name = (user_timezone or "").strip() or detect_local_timezone_name()
    try:
        resolved_zone = ZoneInfo(resolved_tz_name)
    except Exception:
        logger.warning(
            "Caller-supplied user_timezone '%s' is not a valid IANA name; "
            "falling back to autodetected local zone.",
            resolved_tz_name,
        )
        resolved_tz_name = detect_local_timezone_name()
        resolved_zone = ZoneInfo(resolved_tz_name)
    user_now_iso = utc_now().astimezone(resolved_zone).isoformat(timespec="seconds")

    context: Optional[Dict[str, Any]] = None
    if context_id:
        context = _INTERPRETATION_CONTEXTS.get(context_id)

    model_service = get_model_service()
    model_usage_service = ModelUsageService(model_service)
    explicit_model_id = get_interpretation_model_id()
    model = await model_usage_service.get_model_for_task(
        capabilities={ModelCapability.REASONING},
        explicit_model_id=explicit_model_id,
    )
    if not model:
        raise RuntimeError("No reasoning model available for schedule interpretation")

    validation_error: Optional[str] = None
    validated: Optional[Dict[str, Any]] = None
    for attempt in range(2):
        prompt = build_interpretation_prompt(
            text,
            user_timezone=resolved_tz_name,
            user_now_iso=user_now_iso,
            context=context,
            validation_error=validation_error,
        )
        llm_response = await model.generate_response(
            prompt=prompt,
            max_tokens=900,
        )
        try:
            llm_payload = robust_json_loads(llm_response)
            if not isinstance(llm_payload, dict):
                raise ValueError("Schedule interpretation model output was not a valid JSON object")
            contract = InterpretedScheduleContract.model_validate(llm_payload)
            validated = validate_interpreted_schedule_payload(contract.model_dump())
            break
        except (ValueError, ValidationError) as exc:
            validation_error = str(exc)
            if attempt == 0:
                logger.warning(
                    "Schedule interpretation output invalid on first attempt, retrying once: %s",
                    validation_error,
                )
                continue
            raise ValueError(
                f"Schedule interpretation output invalid after retry: {validation_error}"
            ) from exc

    if validated is None:
        raise ValueError("Schedule interpretation output could not be validated")

    if validated["needs_user_confirmation"] and validated["clarification_question"]:
        active_context_id = context_id or str(uuid.uuid4())
        existing = _INTERPRETATION_CONTEXTS.get(active_context_id, {})
        history = existing.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(text)
        _INTERPRETATION_CONTEXTS[active_context_id] = {
            "history": history[-20:],
            "last_clarification_question": validated["clarification_question"],
        }
        raise ValueError(
            f"Need clarification (context_id={active_context_id}): {validated['clarification_question']}"
        )

    if context_id:
        _INTERPRETATION_CONTEXTS.pop(context_id, None)

    return validated
