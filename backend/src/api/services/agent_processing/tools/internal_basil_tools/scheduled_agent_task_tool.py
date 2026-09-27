"""
Scheduled Agent Task Tool for Agent Workflows

Allows the agent to convert natural-language scheduling intent into a persisted
scheduled agent task using Basil's schedule interpretation service.
"""

import json
import logging
from typing import Optional, Tuple

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.scheduled_agent_tasks.scheduled_agent_task_service import ScheduledAgentTaskService
from .checkpoint_tool import request_user_input

logger = logging.getLogger(__name__)


# Why this slim:
# - The full description spends most of its space teaching the agent ONE
#   load-bearing routing rule: 'use this tool only when Basil itself does
#   work at trigger time; if the user is supposed to do the work, route
#   to Reminders/Calendar via applescript_service instead'. That rule is
#   the single highest-value signal and is preserved verbatim in compact
#   form below; it has no equivalent in the system prompt.
# - KEEPS the discriminating question 'at trigger time, who does the work
#   - Basil or the user?' because surface phrasing ('remind me / every X
#   at Y') is identical for both routes; KEEPS the clarification rule
#   ('reuse context_id') because it is structurally invisible from the
#   args schema alone.
# - DROPS the worked examples (the discriminating question is enough to
#   reproduce them) and the 'Behavior:' bullet list (the agent learns
#   the interpreter behavior from one round trip).
SLIM_DESCRIPTION = (
    "create_scheduled_agent_task_from_prompt(prompt, context_id?, is_active?) - "
    "schedule Basil to AUTONOMOUSLY run agentic work at a future time. "
    "Discriminating question: at trigger time, who does the work - Basil "
    "(send email, query data, run a workflow) or the user (a reminder / "
    "alarm)? If the user does the work, do NOT use this; route to "
    "Reminders.app / Calendar.app via applescript_service instead. "
    "Surface phrasing ('remind me', 'every X at Y') is NOT sufficient to "
    "choose this tool. If the prompt is ambiguous (recurrence, timing, "
    "payload), the interpreter returns a clarification + context_id; "
    "ask the user via request_user_input and reuse the same context_id "
    "in the follow-up call."
)


class ScheduledAgentTaskInput(BaseModel):
    """Input schema for scheduled agent task creation from natural language."""

    prompt: str = Field(
        description=(
            "Natural-language request describing what to run and when. "
            "Example: 'Check my inbox every day at 8pm and summarize unanswered emails'."
        )
    )
    context_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional schedule-interpretation context id used for follow-up clarifications. "
            "Reuse this when the user answers a prior clarification question."
        ),
    )
    is_active: bool = Field(
        default=True,
        description="Whether the created schedule should be active immediately.",
    )


def _extract_clarification_details(message: str, fallback_context_id: Optional[str]) -> Tuple[Optional[str], str]:
    """Extract context id and clarification question from interpreter exception text."""
    context_id = fallback_context_id
    question = "Please clarify your scheduling request."

    marker = "(context_id="
    marker_index = message.find(marker)
    if marker_index >= 0:
        after_marker = message[marker_index + len(marker):]
        end_idx = after_marker.find(")")
        if end_idx >= 0:
            extracted_id = after_marker[:end_idx].strip()
            if extracted_id:
                context_id = extracted_id

    colon_idx = message.find(":")
    if colon_idx >= 0 and colon_idx + 1 < len(message):
        extracted_question = message[colon_idx + 1:].strip()
        if extracted_question:
            question = extracted_question

    return context_id, question


async def _create_scheduled_agent_task_impl(
    prompt: str,
    context_id: Optional[str] = None,
    is_active: bool = True,
) -> str:
    """Create a scheduled agent task from a natural-language prompt via the interpreter service."""
    try:
        service = ScheduledAgentTaskService()
        interpreted = await service.interpret_schedule_prompt(prompt, context_id=context_id)
        created = await service.create_scheduled_agent_task(
            title=interpreted["title"],
            agent_task_text=interpreted["agent_task_text"],
            schedule_type=interpreted["schedule_type"],
            schedule_config=interpreted["schedule_config"],
            timezone_name=interpreted["timezone"],
            source_type="smart",
            is_active=is_active,
        )
        return json.dumps(
            {
                "success": True,
                "scheduled_agent_task": created,
                "context_id": context_id,
            },
            ensure_ascii=False,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Need clarification"):
            clarification_context_id, clarification_question = _extract_clarification_details(message, context_id)
            context_hint = (
                f"Use context_id={clarification_context_id} when calling create_scheduled_agent_task_from_prompt "
                "with the user's follow-up answer."
                if clarification_context_id
                else "Call create_scheduled_agent_task_from_prompt again with the user's follow-up answer."
            )
            request_user_input.invoke(
                {
                    "prompt": clarification_question,
                    "input_type": "text",
                    "context_summary": context_hint,
                }
            )
        logger.warning("Schedule interpretation validation error: %s", message)
        return json.dumps({"success": False, "error": message}, ensure_ascii=False)
    except Exception as exc:
        logger.error("Failed to create scheduled agent task from prompt: %s", exc, exc_info=True)
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


def create_scheduled_agent_task_tool(profile=None) -> StructuredTool:
    """Factory function to create the scheduled agent task tool.

    Under a slim rendering profile the description is swapped to
    ``SLIM_DESCRIPTION`` above; otherwise the full description flows
    through unchanged.
    """
    full_description = """Schedule Basil to autonomously execute an agentic action at a future time.

DECISIONING RULE (apply this before choosing this tool):
Use this tool ONLY when Basil itself must execute tool calls at the scheduled time.
If the only thing that needs to happen at trigger time is the user being notified
to do something themselves, this is NOT an agentic schedule — use the appropriate
native macOS app instead (e.g. Reminders.app, Calendar.app via applescript_service).

The discriminating question is: at trigger time, who does the work — Basil, or the user?
- Basil does the work (sends an email, queries data, runs a workflow) → use this tool
- User does the work; Basil is just the alarm clock → do NOT use this tool

Examples:
- USE: "Every morning at 8am, summarize my unread emails and send me the digest"
  → Basil must run email tools and compose a summary at trigger time.
- DO NOT USE: "Remind me to text Nick on Saturday at 5pm"
  → The only trigger-time work is notifying the user. Use Reminders.app instead.

Note: matching the surface phrasing ("schedule", "remind me", "every X at Y") is NOT
sufficient justification. Both agentic and non-agentic requests use that phrasing.
Apply the rule above to the substance of what must happen when the trigger fires.

Behavior:
- Interprets natural language into a strict schedule schema via Basil's schedule interpreter.
- Persists the resulting scheduled agent task.
- If details are ambiguous (recurrence, timing, payload), request clarification via
  request_user_input rather than guessing. Reuse the returned context_id in the next call.
"""
    chosen_description = select_description_for_profile(
        profile, full_description, SLIM_DESCRIPTION
    )
    return StructuredTool.from_function(
        func=_create_scheduled_agent_task_impl,
        name="create_scheduled_agent_task_from_prompt",
        description=chosen_description,
        args_schema=ScheduledAgentTaskInput,
        coroutine=_create_scheduled_agent_task_impl,
    )
