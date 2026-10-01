"""Let the agent wait and re-check within a task, or come back to the task later."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
from api.services.agent_processing.shared.workflow_budget_pause import (
    current_pausable_deadline,
    pause_workflow_budget,
)

logger = logging.getLogger(__name__)

WAIT_TOOL_NAME = "wait_before_checking_again"
SCHEDULE_TOOL_NAME = "schedule_agent_follow_up"
CANCEL_TOOL_NAME = "cancel_agent_follow_ups"
MIN_WAIT_SECONDS = 5
MAX_WAIT_SECONDS = 600
MAX_TOTAL_WAIT_SECONDS_PER_RUN = 1800
WAIT_TICK_SECONDS = 5.0
WAIT_BUDGET_MARGIN_SECONDS = 30.0
MIN_FOLLOW_UP_MINUTES = 1
MAX_FOLLOW_UP_MINUTES = 7 * 24 * 60
MAX_INSTRUCTIONS_CHARS = 4000
WAIT_USED_CONTEXT_KEY = "_agent_wait_seconds_used"


class WaitBeforeCheckingAgainInput(BaseModel):
    seconds: int = Field(description="Seconds to wait before checking again, from 5 to 600.")
    reason: str = Field(default="", description="What you are waiting for, for example 'build to finish'.")


class ScheduleAgentFollowUpInput(BaseModel):
    delay_minutes: int = Field(description="Minutes from now until the follow-up check, from 1 to 10080 (7 days).")
    check_instructions: str = Field(description="Exactly what to check when the follow-up runs, written so a later turn can act on it without guessing.")
    reason: str = Field(default="", description="Why a later check is needed.")


class CancelAgentFollowUpsInput(BaseModel):
    reason: str = Field(default="", description="Why the pending follow-ups are no longer needed.")


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _default_repository() -> Any:
    from api.dependencies import get_sqlite_knowledge_service

    return get_sqlite_knowledge_service().agent_task_follow_up_repository


def _record_wait_progress(agent_task_id: Optional[str], *, status: str, progress_kind: str, **metadata: Any) -> None:
    try:
        from api.services.agent_processing.lifecycle.execution_graph.tool_run_watchdog import record_tool_progress

        record_tool_progress(
            agent_task_id=agent_task_id,
            tool_name=WAIT_TOOL_NAME,
            status=status,
            progress_kind=progress_kind,
            **metadata,
        )
    except Exception as exc:
        logger.debug("Could not record wait progress: %s", exc)


def create_agent_follow_up_tools(
    *,
    agent_task_id: Optional[str] = None,
    root_task_id: Optional[str] = None,
    include_durable: bool = True,
    repository_provider: Optional[Callable[[], Any]] = None,
) -> List[StructuredTool]:
    """Return the in-task wait tool and, unless excluded, the durable follow-up tools."""
    get_repository = repository_provider or _default_repository

    def _resolve_ids() -> Tuple[Optional[str], Optional[str]]:
        context = get_current_agent_context()
        source_id = agent_task_id or context.get("agent_task_id")
        root_id = root_task_id or context.get("root_task_id") or source_id
        return (str(source_id) if source_id else None, str(root_id) if root_id else None)

    async def _wait(seconds: int, reason: str = "") -> str:
        context = get_current_agent_context()
        source_id, _root_id = _resolve_ids()
        requested = max(MIN_WAIT_SECONDS, min(MAX_WAIT_SECONDS, int(seconds)))
        used = float(context.get(WAIT_USED_CONTEXT_KEY) or 0.0)
        allowance = MAX_TOTAL_WAIT_SECONDS_PER_RUN - used
        deadline = current_pausable_deadline()
        if deadline is not None and callable(getattr(deadline, "remaining_seconds", None)):
            reserve = float(getattr(deadline, "finalization_reserve_seconds", 0.0) or 0.0)
            allowance = min(allowance, deadline.remaining_seconds() - reserve - WAIT_BUDGET_MARGIN_SECONDS)
        wait_seconds = min(float(requested), allowance)
        if wait_seconds < MIN_WAIT_SECONDS:
            return _json(
                {
                    "success": False,
                    "waited_seconds": 0,
                    "error": "Not enough time remains in this run to wait. Use schedule_agent_follow_up to come back to this task later, or finish now and report the current state.",
                }
            )

        _record_wait_progress(source_id, status="waiting", progress_kind="agent_wait_started", wait_seconds=round(wait_seconds), wait_reason=reason or None)
        started = time.time()
        target = started + wait_seconds
        waited = 0.0
        try:
            with pause_workflow_budget("agent_wait"):
                while True:
                    remaining = target - time.time()
                    if remaining <= 0:
                        break
                    await asyncio.sleep(min(WAIT_TICK_SECONDS, remaining))
        finally:
            waited = max(0.0, time.time() - started)
            if isinstance(context, dict):
                context[WAIT_USED_CONTEXT_KEY] = used + waited
            _record_wait_progress(source_id, status="active", progress_kind="agent_wait_finished")
        return _json(
            {
                "success": True,
                "waited_seconds": round(waited),
                "requested_seconds": int(seconds),
                "reason": reason,
                "remaining_wait_allowance_seconds": max(0, round(MAX_TOTAL_WAIT_SECONDS_PER_RUN - used - waited)),
                "next_step": "Check the condition again now. If it is still not ready, wait again within the remaining allowance, or use schedule_agent_follow_up to come back to this task later.",
            }
        )

    async def _schedule(delay_minutes: int, check_instructions: str, reason: str = "") -> str:
        from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import (
            FollowUpLimitExceeded,
        )

        source_id, root_id = _resolve_ids()
        if not source_id or not root_id:
            return _json({"success": False, "error": "No active Agent Task to attach a follow-up to."})
        instructions = (check_instructions or "").strip()
        if not instructions:
            return _json({"success": False, "error": "check_instructions must describe what to check."})
        if len(instructions) > MAX_INSTRUCTIONS_CHARS:
            return _json({"success": False, "error": f"Keep check_instructions under {MAX_INSTRUCTIONS_CHARS} characters."})
        minutes = max(MIN_FOLLOW_UP_MINUTES, min(MAX_FOLLOW_UP_MINUTES, int(delay_minutes)))
        due_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        try:
            record = await get_repository().create_follow_up(
                root_task_id=root_id,
                source_agent_task_id=source_id,
                instructions=instructions,
                reason=(reason or "").strip(),
                due_at=due_at,
            )
        except FollowUpLimitExceeded as exc:
            return _json({"success": False, "error": str(exc)})
        return _json(
            {
                "success": True,
                "follow_up_id": record["id"],
                "due_at": record["due_at"],
                "delay_minutes": minutes,
                "next_step": "Finish this turn now with a short summary of what you found so far and when you will check again. The follow-up starts a new turn of this task at due_at; do not wait for it in this turn.",
            }
        )

    async def _cancel(reason: str = "") -> str:
        _source_id, root_id = _resolve_ids()
        if not root_id:
            return _json({"success": False, "error": "No active Agent Task."})
        detail = (reason or "").strip() or "no reason given"
        canceled = await get_repository().cancel_pending_for_root(root_id, reason=f"Canceled by the agent: {detail}")
        return _json({"success": True, "canceled_follow_ups": canceled})

    tools: List[StructuredTool] = [
        StructuredTool.from_function(
            func=_wait,
            coroutine=_wait,
            name=WAIT_TOOL_NAME,
            description=(
                "Pause this task for 5 to 600 seconds, then check again. Use it when something you started needs time "
                "(a build, an upload, a deployment, a reply) and checking again within a few minutes is likely to succeed. "
                "Waiting does not use up the task's time budget, but one run can wait at most 30 minutes in total. "
                "For longer waits, use schedule_agent_follow_up instead."
            ),
            args_schema=WaitBeforeCheckingAgainInput,
        )
    ]
    if include_durable:
        tools.append(
            StructuredTool.from_function(
                func=_schedule,
                coroutine=_schedule,
                name=SCHEDULE_TOOL_NAME,
                description=(
                    "Come back to this task later: in 1 minute to 7 days, Basil starts a new turn of this same task that "
                    "performs check_instructions with the earlier turns as context. It survives restarts. Use it when a result "
                    "will take longer than a few minutes, then finish the current turn. Do not use it for work the user should do "
                    "themselves, and do not use it for recurring schedules (use create_scheduled_agent_task_from_prompt)."
                ),
                args_schema=ScheduleAgentFollowUpInput,
            )
        )
        tools.append(
            StructuredTool.from_function(
                func=_cancel,
                coroutine=_cancel,
                name=CANCEL_TOOL_NAME,
                description="Cancel this task's pending follow-up checks, for example when the user says to stop checking or the result has arrived.",
                args_schema=CancelAgentFollowUpsInput,
            )
        )
    return tools


__all__ = [
    "CANCEL_TOOL_NAME",
    "MAX_TOTAL_WAIT_SECONDS_PER_RUN",
    "SCHEDULE_TOOL_NAME",
    "WAIT_TOOL_NAME",
    "WAIT_USED_CONTEXT_KEY",
    "create_agent_follow_up_tools",
]
