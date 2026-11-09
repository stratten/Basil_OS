"""The checklist block the outcome verifier reads, with the sign-off rules it applies.

The verifier already judges whether the delivered answer meets the request. With the checklist in front of it, it can also say in its reasoning how many of the requested items were tracked and what state each is in, and it signs off on the checklist itself (see agent_checklist_signoff). The block tells the verifier in plain words not to change the outcome, ask for a retry, or write continuation instructions because of the checklist, so a thin checklist can never fail an otherwise good run.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .agent_checklist_prompt import short_id
from .agent_checklist_signoff import SIGNOFF_RULES

logger = logging.getLogger(__name__)

EVIDENCE_MAX_ITEMS = 30
EVIDENCE_TITLE_CHARS = 100
EVIDENCE_MAX_CHARS = 4500

_EVIDENCE_NOTE = "what Basil tracks for the user and you sign off on. Do not change the outcome, request a retry, or write continuation_instructions because of it."


def _title(text: Any) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= EVIDENCE_TITLE_CHARS else value[: EVIDENCE_TITLE_CHARS - 1].rstrip() + "…"


def _item_line(item: Dict[str, Any]) -> str:
    line = f"- [{short_id(item['id'])}] [{item['status']}] {_title(item['title'])}"
    if item.get("required"):
        line += " (required)"
    if item.get("waiting_on") and item["status"] in ("waiting_user", "waiting_external"):
        line += f", waiting on: {_title(item['waiting_on'])}"
    if item.get("last_actor") == "user":
        line += " (edited by the user)"
    return line


def build_checklist_evidence(items: List[Dict[str, Any]], counts: Dict[str, int]) -> str:
    """The block for the verifier. An empty checklist still gets a short line, so the verifier can say that a requested set was not tracked."""
    total = int(counts.get("total", 0))
    if total == 0:
        return (
            f"TASK CHECKLIST (empty; {_EVIDENCE_NOTE}) "
            "If the request asked for a set of items, mention in your reasoning that none of them were tracked. "
            f"{SIGNOFF_RULES}"
        )
    header = (
        f"TASK CHECKLIST ({_EVIDENCE_NOTE}) "
        f"{counts.get('done', 0)} of {total} done, {counts.get('waiting_user', 0)} waiting on the user, "
        f"{counts.get('waiting_external', 0)} waiting on someone else, {counts.get('required_open', 0)} required items still open."
    )
    footer = (
        "In your reasoning, say briefly how many of the requested items this checklist tracks and the state of each. "
        "If the request named a set of items and the checklist tracks fewer of them, say which are missing."
    )
    reserved = len(header) + len(SIGNOFF_RULES) + len(footer) + 40
    lines = [header, SIGNOFF_RULES]
    used = reserved
    shown = 0
    for item in items[:EVIDENCE_MAX_ITEMS]:
        line = _item_line(item)
        if used + len(line) + 1 > EVIDENCE_MAX_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1
    if len(items) > shown:
        lines.append(f"- and {len(items) - shown} more items")
    lines.append(footer)
    return "\n".join(lines)


async def finalizer_checklist_block(context: Optional[Dict[str, Any]]) -> str:
    """The evidence block for this chain, or an empty string when it cannot be read or the user stopped tracking. Never raises and never creates a session."""
    try:
        from api.dependencies import get_sqlite_knowledge_service

        from .agent_checklist_service import AgentChecklistService

        service = AgentChecklistService(get_sqlite_knowledge_service())
        session = await service.session_for_context(context, create=False)
        if session is None:
            return build_checklist_evidence([], {"total": 0})
        snapshot = await service.snapshot(session["id"])
        if snapshot["closed_at"]:
            return ""
        return build_checklist_evidence(snapshot["items"], snapshot["counts"])
    except Exception:
        logger.warning("Could not read the checklist for the finalizer", exc_info=True)
        return ""
