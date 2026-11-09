"""The outcome verifier's authority over the task checklist.

The checklist records what still needs to happen as a result of the request and of what the agent or the user found, not what the agent did. The agent keeps it current while it works, but it cannot grade its own proposals, so the verifier signs off after the answer is delivered: it confirms an item done only when its outcome verifiably happened, reopens an item the agent closed too early, and adds an item for an outcome nobody tracked. This module holds the rules the verifier is given, the parser for its decisions, and the code that applies them.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SIGNOFF_ACTOR = "system"
SIGNOFF_EVENT_PREFIX = "Outcome check"
MAX_REVIEW_UPDATES = 30
MAX_REVIEW_NEW_ITEMS = 10
MAX_REASON_CHARS = 200
MAX_TITLE_CHARS = 200
MAX_DETAIL_CHARS = 500
MIN_ITEM_PREFIX_CHARS = 6
UPDATE_STATUSES = ("pending", "in_progress", "waiting_external", "waiting_user", "done", "dropped")
NEW_ITEM_STATUSES = ("pending", "in_progress", "waiting_external", "waiting_user")

SIGNOFF_RULES = (
    "You also sign off on this checklist. It records what still needs to happen as a result of the request and of what the agent or the user found, not a log of what the agent did. "
    "Judge each item against the DELIVERED RESPONSE, the tool trace, and what the user said in this chain. "
    "Mark an item done only when its outcome verifiably happened: a write the tool trace shows succeeded, or a decision the user stated. The agent's own judgment that nothing is needed does not complete an item: the user must have said so, or the action must have been carried out. "
    "A proposal, draft, or recommendation does not complete an item, so an item the agent only proposed on must be waiting_user, with waiting_on saying what the user must decide. "
    "Use pending or in_progress when the next step is the agent's, waiting_external when someone else must act, and dropped only when the outcome no longer applies. "
    "Add an entry to new_items for each outcome the request or the findings imply that no item covers, such as a follow-up the delivered response asks the user to do. Never add an item for something the agent merely did, and a request that was a single quick action implies no outcomes to add. "
    "In checklist_review.items list only items whose status should change, using the id exactly as shown, with a one-sentence reason; leave correct items out. Items marked (edited by the user) cannot be changed. "
    "checklist_review never changes outcome, should_retry, or continuation_instructions."
)


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def parse_checklist_review(evaluation: Dict[str, Any]) -> Optional[Dict[str, List[Dict[str, str]]]]:
    """The verifier's checklist decisions, cleaned and capped, or None when it made none."""
    raw = evaluation.get("checklist_review")
    if not isinstance(raw, dict):
        return None
    updates: List[Dict[str, str]] = []
    for entry in raw.get("items") or []:
        if not isinstance(entry, dict) or len(updates) >= MAX_REVIEW_UPDATES:
            continue
        item = _clip(entry.get("item"), 64)
        status = str(entry.get("status") or "").strip().lower()
        reason = _clip(entry.get("reason"), MAX_REASON_CHARS)
        if not item or status not in UPDATE_STATUSES or not reason:
            continue
        updates.append({"item": item, "status": status, "reason": reason, "waiting_on": _clip(entry.get("waiting_on"), MAX_REASON_CHARS)})
    additions: List[Dict[str, str]] = []
    for entry in raw.get("new_items") or []:
        if not isinstance(entry, dict) or len(additions) >= MAX_REVIEW_NEW_ITEMS:
            continue
        title = _clip(entry.get("title"), MAX_TITLE_CHARS)
        if not title:
            continue
        status = str(entry.get("status") or "").strip().lower()
        additions.append({
            "title": title,
            "detail": _clip(entry.get("detail"), MAX_DETAIL_CHARS),
            "status": status if status in NEW_ITEM_STATUSES else "waiting_user",
            "waiting_on": _clip(entry.get("waiting_on"), MAX_REASON_CHARS),
        })
    if not updates and not additions:
        return None
    return {"items": updates, "new_items": additions}


def _match_item(items: List[Dict[str, Any]], token: str) -> Optional[Dict[str, Any]]:
    """The one open-list item whose id equals or starts with the token, or None when there is no unique match."""
    if len(token) < MIN_ITEM_PREFIX_CHARS:
        return None
    matches = [item for item in items if str(item["id"]).startswith(token)]
    return matches[0] if len(matches) == 1 else None


async def apply_checklist_review(
    knowledge_service: Any,
    ids: Dict[str, Any],
    review: Dict[str, List[Dict[str, str]]],
) -> Dict[str, Any]:
    """Apply the verifier's decisions to this chain's checklist and return a summary. Never raises.

    The verifier changes nothing when the user stopped tracking. It skips an item whose latest change was the user's, an item that changed after the verifier read it (a stale revision), and a new item whose title already exists.
    """
    summary: Dict[str, Any] = {"updated": 0, "created": 0, "skipped": []}
    try:
        from .agent_checklist_service import AgentChecklistService

        service = AgentChecklistService(knowledge_service)
        repository = knowledge_service.agent_checklist_repository
        session = await service.session_for_context(ids, create=bool(review.get("new_items")))
        if session is None:
            summary["skipped"].append("no checklist for this chain")
            return summary
        snapshot = await service.snapshot(session["id"])
        if snapshot["closed_at"]:
            summary["skipped"].append("tracking was stopped by the user")
            return summary
        items = snapshot["items"]
        agent_task_id = ids.get("agent_task_id")
        for entry in review.get("items", []):
            item = _match_item(items, entry["item"])
            if item is None:
                summary["skipped"].append(f"{entry['item']}: no unique open match")
                continue
            if item.get("last_actor") == "user":
                summary["skipped"].append(f"{entry['item']}: last changed by the user")
                continue
            changes: Dict[str, Any] = {"status": entry["status"]}
            if entry["status"] in ("waiting_user", "waiting_external") and entry["waiting_on"]:
                changes["waiting_on"] = entry["waiting_on"]
            result = await repository.update_item(
                session_id=session["id"], item_id=item["id"], changes=changes, expected_revision=item["revision"],
                actor=SIGNOFF_ACTOR, agent_task_id=agent_task_id, event_text=f"{SIGNOFF_EVENT_PREFIX}: {entry['reason']}",
            )
            if not result:
                summary["skipped"].append(f"{entry['item']}: item no longer exists")
            elif result.get("conflict"):
                summary["skipped"].append(f"{entry['item']}: changed while the outcome check ran")
            elif result.get("changed"):
                summary["updated"] += 1
        known_titles = {" ".join(str(item["title"]).split()).lower() for item in items}
        for entry in review.get("new_items", []):
            if entry["title"].lower() in known_titles:
                summary["skipped"].append(f"{entry['title']}: already on the checklist")
                continue
            result = await repository.add_item(
                session_id=session["id"], title=entry["title"], origin="agent", detail=entry["detail"], status=entry["status"],
                waiting_on=entry["waiting_on"] if entry["status"] in ("waiting_user", "waiting_external") else "",
                actor=SIGNOFF_ACTOR, agent_task_id=agent_task_id,
            )
            if result.get("rejected"):
                summary["skipped"].append(f"new items stopped: {result['rejected']}")
                break
            if result.get("created"):
                summary["created"] += 1
                known_titles.add(entry["title"].lower())
        if summary["updated"] or summary["created"]:
            await service.publish(session["id"], ids)
    except Exception:
        logger.warning("Applying the outcome verifier's checklist decisions failed", exc_info=True)
        summary["skipped"].append("the checklist could not be updated")
    return summary
