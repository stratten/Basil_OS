"""Seed a scheduled run's checklist from the schedule's previous run, when the schedule opted in."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .scheduled_chain_config import parse_chain_config

logger = logging.getLogger(__name__)


def _describe(copied: int, notes_carried: bool) -> Optional[str]:
    parts = []
    if copied:
        parts.append(f"{copied} open checklist item{'s' if copied != 1 else ''}")
    if notes_carried:
        parts.append("the checklist notes")
    return f"Carried {' and '.join(parts)} over from the previous run." if parts else None


async def carry_checklist_into_run(
    repo: Any,
    scheduled_agent_task: Dict[str, Any],
    *,
    run_id: str,
    new_root_task_id: str,
    continuing_chain: bool,
    knowledge_service: Any,
) -> Optional[str]:
    """Copy open items and notes from the previous run's chain into this run's new chain. Never raises.

    A run that continues a chain already shares that chain's checklist, so only a run that starts a new root is seeded. Returns a short notice for the run history, or None when nothing was carried.
    """
    if continuing_chain or not parse_chain_config(scheduled_agent_task.get("chain_config")).carry_checklist:
        return None
    try:
        from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import AgentChecklistService

        anchor = await repo.latest_chain_anchor(scheduled_agent_task["id"], run_id)
        if anchor is None:
            return None
        result = await AgentChecklistService(knowledge_service).carry_over(
            from_root_task_id=anchor["root_task_id"],
            to_root_task_id=new_root_task_id,
            goal=str(scheduled_agent_task.get("agent_task_text") or "")[:200] or None,
            agent_task_id=new_root_task_id,
        )
        return _describe(result["copied"], result["notes_carried"])
    except Exception:
        logger.warning(
            "Could not carry the checklist into run %s of schedule %s", run_id, scheduled_agent_task.get("id"), exc_info=True
        )
        return None
