"""The checklist completion gate: ask the model to close required items before it finishes, at most twice, then say plainly what is not done.

Only items the user or the agent marked required take part. An item that still can be worked (to do, in progress) makes the gate ask the model to carry on. An item that waits on the user or on someone else needs nothing more from the model, so it never triggers a retry, but it still appears in the footer, because the task is not complete while it is open. The footer is appended by code after the answer is written, so it does not depend on the model remembering to say it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GATE_MAX_REJECTIONS = 2
GATE_FOOTER_MARKER = "**Not completed**"
FOOTER_ITEM_LIMIT = 10
ACTIONABLE_STATUSES = frozenset({"pending", "in_progress"})

_STATUS_PHRASE = {
    "pending": "not started",
    "in_progress": "in progress",
    "waiting_user": "needs your input",
    "waiting_external": "waiting on someone else",
}


def actionable_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Open required items the model can still work on."""
    return [item for item in items if item.get("status") in ACTIONABLE_STATUSES]


def build_gate_message(items: List[Dict[str, Any]]) -> str:
    """The instruction sent back to the model in place of letting its answer stand."""
    from .agent_checklist_prompt import short_id

    lines = [f"- [{short_id(item['id'])}] {item['title']} ({_STATUS_PHRASE.get(item['status'], item['status'])})" for item in items[:FOOTER_ITEM_LIMIT]]
    more = len(items) - FOOTER_ITEM_LIMIT
    if more > 0:
        lines.append(f"- and {more} more")
    return (
        "CHECKLIST CHECK (required items are still open):\n"
        + "\n".join(lines)
        + "\n- Finish the work for each one now, then mark it done. "
        "If an item no longer applies, mark it dropped. "
        "If it is blocked on the user or on someone else, set its status to waiting_user or waiting_external and say what you need in waiting_on. "
        "Do not mark an item done unless its outcome has really happened; a proposal or draft is not the outcome. Then give your final answer."
    )


def build_not_completed_footer(items: List[Dict[str, Any]]) -> str:
    """A fixed, plain list of required items that are still open, in the order the checklist shows them."""
    lines = []
    for item in items[:FOOTER_ITEM_LIMIT]:
        phrase = _STATUS_PHRASE.get(item["status"], item["status"])
        waiting = f": {item['waiting_on']}" if item.get("waiting_on") and item["status"] in ("waiting_user", "waiting_external") else ""
        lines.append(f"- {item['title']} ({phrase}{waiting})")
    more = len(items) - FOOTER_ITEM_LIMIT
    if more > 0:
        lines.append(f"- and {more} more")
    return f"{GATE_FOOTER_MARKER}\n" + "\n".join(lines)


async def with_not_completed_footer(text: str, context: Optional[Dict[str, Any]]) -> str:
    """The answer with the footer appended when required items are open. A failure to read the checklist leaves the answer untouched."""
    try:
        from api.dependencies import get_sqlite_knowledge_service

        from .agent_checklist_service import AgentChecklistService

        items = await AgentChecklistService(get_sqlite_knowledge_service()).open_required_items(context)
    except Exception:
        logger.warning("Could not read the checklist for the completion footer", exc_info=True)
        return text
    if not items or GATE_FOOTER_MARKER in text:
        return text
    return f"{text.rstrip()}\n\n{build_not_completed_footer(items)}"


class ChecklistCompletionGate:
    """Counts how often one run's final answer has been sent back, so the gate cannot loop."""

    def __init__(self, max_rejections: int = GATE_MAX_REJECTIONS) -> None:
        self.max_rejections = max_rejections
        self.rejections = 0
        self.empty_review_sent = False

    async def review_final_answer(self, context: Optional[Dict[str, Any]]) -> Optional[str]:
        """The message to send the model instead of accepting its answer, or None to accept it. Never raises."""
        if self.rejections >= self.max_rejections:
            return None
        try:
            from api.dependencies import get_sqlite_knowledge_service

            from .agent_checklist_service import AgentChecklistService

            service = AgentChecklistService(get_sqlite_knowledge_service())
            items = await service.open_required_items(context)
        except Exception:
            logger.warning("Could not read the checklist for the completion gate", exc_info=True)
            return None
        owed = actionable_items(items)
        if not owed:
            return await self._review_empty_checklist(service, context)
        self.rejections += 1
        logger.info("[AgentTelemetry] checklist-gate rejection=%s open_required=%s", self.rejections, len(owed))
        return build_gate_message(owed)

    async def _review_empty_checklist(self, service: Any, context: Optional[Dict[str, Any]]) -> Optional[str]:
        """Once per run: a run that found records but never made a checklist item gets one chance to add them before it finishes."""
        if self.empty_review_sent or not await service.records_without_checklist(context):
            return None
        from .agent_checklist_prompt import build_empty_checklist_review

        self.empty_review_sent = True
        logger.info("[AgentTelemetry] checklist-gate empty-checklist review sent")
        return build_empty_checklist_review()
