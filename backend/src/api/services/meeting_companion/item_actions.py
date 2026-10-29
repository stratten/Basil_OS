"""From a Companion note to a To-Do or an agent task: the button path and the proactive path.

The button path is the user's own approval, so it creates an action card from the note and approves it in one step. The proactive path turns the evaluator's proposals into ordinary review cards that wait for a click. Both go through ``shape_proposals`` or the same card shape, so the capability settings, the dedupe and the per-meeting cap apply.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from .investigator.models import ProposedAction
from .models import AuditReport, CompanionItem, ProposalInfo, TranscriptRange
from .proposals import (
    ALL_ACTIONS,
    PROPOSAL_ACTION_LABELS,
    MAX_INSTRUCTION_CHARS,
    MAX_TITLE_CHARS,
    ProposalDecision,
    ProposalLauncher,
    ProposalNotFound,
    ProposalPolicy,
    ProposalRejected,
    decide_proposal,
    shape_proposals,
)
from .similarity import normalize_text

USER_ACTIONS = ("todo", "agent_task")
ITEM_ACTION_TRIGGER = "item_action"
FAST_PROPOSAL_MAX_PER_EVALUATION = 1
_FIRST_SENTENCE = re.compile(r"^(.{12,}?[.!?])(?:\s|$)")


@dataclass(frozen=True)
class ItemActionResult:
    """The card the action created and what the approval did."""

    card_id: str
    decision: ProposalDecision


def actionable_item(items: Sequence[CompanionItem], audit: Optional[AuditReport], item_id: str) -> Optional[CompanionItem]:
    """The note an action button was clicked on: a feed item, or an audit finding presented as a suggestion so it can become a to-do or an agent task the same way."""
    found = next((candidate for candidate in items if candidate.id == item_id), None)
    if found is not None or audit is None:
        return found
    moment = next((candidate for candidate in audit.moments if candidate.id == item_id), None)
    if moment is None:
        return None
    return CompanionItem(
        id=moment.id,
        kind="suggestion",
        text=moment.suggested_text,
        confidence=moment.confidence,
        transcript_range=TranscriptRange(start=moment.start, end=moment.end),
        trigger="audit",
    )


def title_from_text(text: str) -> str:
    """A short imperative-sized title: the first sentence when there is one, otherwise the text cut at a word boundary."""
    flat = normalize_text(text)
    sentence = _FIRST_SENTENCE.match(flat)
    candidate = sentence.group(1) if sentence else flat
    if len(candidate) <= MAX_TITLE_CHARS:
        return candidate.strip()
    cut = candidate[:MAX_TITLE_CHARS]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > MAX_TITLE_CHARS // 2 else cut).rstrip(" ,;:")


def instruction_from_text(text: str, action: str) -> str:
    flat = normalize_text(text)
    if action == "agent_task":
        flat = f"Follow up on this note from the meeting: {flat}"
    return flat[:MAX_INSTRUCTION_CHARS].strip()


def shape_action_card(
    *,
    text: str,
    action: str,
    policy: ProposalPolicy,
    existing: Sequence[CompanionItem],
    confidence: float,
    transcript_range: TranscriptRange,
    source_item_id: str,
) -> CompanionItem:
    """The review card for a user's own to-do or agent-task click; raises ``ProposalRejected`` with a user-facing reason."""
    if action not in USER_ACTIONS:
        raise ProposalRejected("Choose To-Do or Agent Task.")
    if action not in policy.capabilities:
        raise ProposalRejected(f"{PROPOSAL_ACTION_LABELS[action]} actions are turned off in the Companion settings.")
    title = title_from_text(text)
    instruction = instruction_from_text(text, action)
    if not title or not instruction:
        raise ProposalRejected("There is nothing to turn into an action.")
    for earlier in existing:
        if earlier.source_item_id == source_item_id and not earlier.dismissed:
            raise ProposalRejected("That note already has an action. Open its card to follow or retry it.")
    return CompanionItem(
        id=f"it-{uuid.uuid4().hex[:10]}",
        kind="proposal",
        text=title,
        confidence=confidence,
        transcript_range=transcript_range,
        trigger=ITEM_ACTION_TRIGGER,
        source_item_id=source_item_id,
        proposal=ProposalInfo(
            proposal_id=f"pr-{uuid.uuid4().hex[:8]}",
            action=action,  # type: ignore[arg-type]
            title=title,
            instruction=instruction,
            authority="review",
        ),
    )


async def run_item_action(
    *,
    session_key: str,
    item: Optional[CompanionItem],
    action: str,
    existing: Sequence[CompanionItem],
    policy: ProposalPolicy,
    launcher: Optional[ProposalLauncher],
    append_item: Callable[[CompanionItem], object],
    append_proposal: Callable[[dict], object],
    reference_paths: Sequence[str] = (),
) -> ItemActionResult:
    """Create the action card for ``item`` and approve it. Raises ``ProposalNotFound`` or ``ProposalRejected``; a failed start is a normal result with state ``failed`` that the card lets the user retry."""
    if item is None:
        raise ProposalNotFound("That Companion item does not exist.")
    if item.kind == "proposal" or item.proposal is not None:
        raise ProposalRejected("That item is already a proposed action.")
    card = shape_action_card(
        text=item.text,
        action=action,
        policy=policy,
        existing=existing,
        confidence=item.confidence,
        transcript_range=item.transcript_range,
        source_item_id=item.id,
    )
    append_item(card)
    decision = await decide_proposal(session_key=session_key, item=card, decision="approve", launcher=launcher, append=append_proposal, reference_paths=reference_paths)
    return ItemActionResult(card_id=card.id, decision=decision)


def shape_evaluation_proposals(
    proposed: Sequence[ProposedAction],
    *,
    policy: ProposalPolicy,
    existing: Sequence[CompanionItem],
    transcript_range: TranscriptRange,
    trigger: str,
    confidence: float,
) -> List[CompanionItem]:
    """Review cards for the evaluator's proposals: ``review`` authority only, never a watch's, at most one per evaluation, filtered by the user's capability settings and the per-meeting cap."""
    allowed = [candidate for candidate in proposed if candidate.action in USER_ACTIONS and candidate.action in ALL_ACTIONS]
    return shape_proposals(
        allowed,
        policy=policy,
        existing=existing,
        investigation_id=None,
        transcript_range=transcript_range,
        watch_id=None,
        watch_authority=False,
        confidence=confidence,
        trigger=trigger,
        researched=False,
        max_new=FAST_PROPOSAL_MAX_PER_EVALUATION,
    )
