"""How one scheduled run relates to the earlier runs of the same schedule: its own task, the start of a chain, a continuation, or skipped."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .scheduled_chain_config import ChainConfig, parse_chain_config

logger = logging.getLogger(__name__)

ACTION_INDEPENDENT = "independent"
ACTION_START = "start"
ACTION_CONTINUE = "continue"
ACTION_SKIP = "skip"

SCHEDULED_ORIGIN_TYPE = "scheduled_task"
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "canceled"})

HANDOFF_DEFAULT_CHARS = 6_000
HANDOFF_MIN_CHARS = 2_000
HANDOFF_MAX_CHARS = 12_000
HANDOFF_WINDOW_SHARE = 0.05
HANDOFF_CHARS_PER_TOKEN = 3

SKIP_REASON = "Skipped because the previous run is still in progress or waiting for you."
LOOKUP_FAILED_NOTICE = "Could not check the earlier runs, so this run started its own task."


@dataclass(frozen=True)
class ChainPlan:
    """What the runner does with one claimed run."""

    action: str = ACTION_INDEPENDENT
    root_task_id: Optional[str] = None
    handoff_block: Optional[str] = None
    notice: Optional[str] = None
    skip_reason: Optional[str] = None


def describe_age_limit(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} day{'s' if days != 1 else ''}"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minutes"


def _minutes_since(timestamp: Any, now: datetime) -> float:
    """Minutes between a stored task timestamp and ``now``.

    Task timestamps are stored as naive UTC (``utc_now_naive_iso``), so a naive value is read as UTC; an aware value is compared as-is.
    """
    if not isinstance(timestamp, datetime):
        return 0.0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    reference = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return max(0.0, (reference - timestamp).total_seconds() / 60.0)


def _scheduled_turn_count(chain: List[Any], scheduled_agent_task_id: str) -> int:
    return sum(
        1
        for turn in chain
        if getattr(turn, "origin_type", None) == SCHEDULED_ORIGIN_TYPE
        and getattr(turn, "origin_id", None) == scheduled_agent_task_id
    )


def _rollover_reason(config: ChainConfig, chain: List[Any], scheduled_agent_task_id: str, now: datetime) -> Optional[str]:
    """Which limit the chain has reached, in words for the run history, or None when it can still grow."""
    if config.max_runs and _scheduled_turn_count(chain, scheduled_agent_task_id) >= config.max_runs:
        return f"{config.max_runs} run{'s' if config.max_runs != 1 else ''}"
    if config.max_age_minutes and _minutes_since(getattr(chain[0], "timestamp", None), now) >= config.max_age_minutes:
        return describe_age_limit(config.max_age_minutes)
    return None


async def _handoff_char_budget(model_id: Optional[str]) -> int:
    window: Optional[int] = None
    if model_id:
        try:
            from api.services.agent_processing.lifecycle.execution_graph.context_window_budget import (
                resolve_context_window_tokens,
            )

            window = await resolve_context_window_tokens(None, {"model_id": model_id})
        except Exception:
            logger.debug("Could not read the context window of %s for the chain handoff", model_id, exc_info=True)
            window = None
    if not window:
        return HANDOFF_DEFAULT_CHARS
    return max(HANDOFF_MIN_CHARS, min(HANDOFF_MAX_CHARS, int(window * HANDOFF_CHARS_PER_TOKEN * HANDOFF_WINDOW_SHARE)))


async def build_handoff_block(chain: List[Any], model_id: Optional[str]) -> Optional[str]:
    """The last real result the closed chain produced, framed as read-only background, or None when it produced none."""
    from api.services.agent_processing.lifecycle.planning.agent_context_assembler import extract_result_summary_text

    limit = await _handoff_char_budget(model_id)
    for turn in reversed(chain):
        summary = extract_result_summary_text(getattr(turn, "result_data", None), limit)
        if summary:
            return (
                "PREVIOUS SCHEDULED CONVERSATION (read-only background):\n"
                "This scheduled task earlier ran as a separate conversation that has now been closed. "
                "Its last result is below. Build on it where it helps, and do not repeat work it already finished.\n\n"
                f"{summary}"
            )
    return None


async def plan_chain_run(
    repo: Any,
    db: Any,
    scheduled_agent_task: Dict[str, Any],
    *,
    run_id: str,
    now: Optional[datetime] = None,
) -> ChainPlan:
    """Decide how a claimed run relates to the earlier runs of its schedule. Never raises."""
    config = parse_chain_config(scheduled_agent_task.get("chain_config"))
    if not config.is_chained:
        return ChainPlan()
    schedule_id = scheduled_agent_task["id"]
    now = now or datetime.now(timezone.utc)
    try:
        anchor = await repo.latest_chain_anchor(schedule_id, run_id)
        if anchor is None:
            return ChainPlan(action=ACTION_START)
        chain: List[Any] = []
        if not anchor.get("root_archived_at"):
            chain = list(await db.get_agent_task_chain(anchor["root_task_id"]) or [])
        if not chain:
            return ChainPlan(action=ACTION_START)
        reason = _rollover_reason(config, chain, schedule_id, now)
        if reason:
            handoff = await build_handoff_block(chain, scheduled_agent_task.get("model_id")) if config.carry_over else None
            return ChainPlan(
                action=ACTION_START,
                handoff_block=handoff,
                notice=f"Started a new conversation because the previous one reached its limit of {reason}.",
            )
        latest_status = str(getattr(chain[-1], "status", "") or "").lower()
        if latest_status not in TERMINAL_TASK_STATUSES:
            return ChainPlan(action=ACTION_SKIP, skip_reason=SKIP_REASON)
        return ChainPlan(action=ACTION_CONTINUE, root_task_id=anchor["root_task_id"])
    except Exception:
        logger.warning(
            "plan_chain_run: could not plan chain for scheduled_agent_task_id=%s run_id=%s; running independently",
            schedule_id,
            run_id,
            exc_info=True,
        )
        return ChainPlan(notice=LOOKUP_FAILED_NOTICE)
