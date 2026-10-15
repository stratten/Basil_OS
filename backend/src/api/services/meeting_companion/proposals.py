"""Proposed follow-up actions: how a proposal is shaped, when one may start by itself, and how an approval or dismissal is carried out.

Authority rule: transcript and file text are untrusted data. Only a proposal that came from a watch the user created may start by itself, and what it starts is the watch's own wording, never any text the model wrote.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Set, Tuple

from .investigator.models import ProposedAction
from .models import CompanionGlobalSettings, CompanionItem, CompanionWatch, ProposalInfo, TranscriptRange
from .similarity import content_tokens, jaccard, normalize_text

logger = logging.getLogger(__name__)

MAX_PROPOSALS_PER_RUN = 2
MAX_PROPOSALS_PER_MEETING = 6
MAX_AUTO_STARTS_PER_MEETING = 2
MAX_TITLE_CHARS = 120
MAX_INSTRUCTION_CHARS = 600
MAX_EXCERPT_CHARS = 300
DUPLICATE_PROPOSAL_SIMILARITY = 0.6
ALL_ACTIONS: Tuple[str, ...] = ("todo", "agent_task", "assistant_session")
AUTO_CAPABLE_ACTIONS: Tuple[str, ...] = ("todo", "agent_task")


class ProposalNotFound(LookupError):
    """The item does not exist."""


class ProposalRejected(ValueError):
    """The decision is not allowed in the proposal's current state; the message is user-facing."""


class ProposalLaunchError(RuntimeError):
    """An approved proposal could not be started; the message is user-facing."""


@dataclass(frozen=True)
class ProposalPolicy:
    """Which actions the investigator may propose and which of them may start without a click."""

    capabilities: Tuple[str, ...] = ALL_ACTIONS
    auto_capabilities: Tuple[str, ...] = ()


DEFAULT_POLICY = ProposalPolicy()


def policy_from_settings(settings: CompanionGlobalSettings) -> ProposalPolicy:
    """Automatic starting needs mode auto_execute, the capability to be proposable, and the capability to be listed for auto-execute."""
    capabilities = tuple(action for action in ALL_ACTIONS if action in settings.proposal_capabilities)
    auto: Tuple[str, ...] = ()
    if settings.proposal_mode == "auto_execute":
        auto = tuple(action for action in AUTO_CAPABLE_ACTIONS if action in settings.auto_execute_capabilities and action in capabilities)
    return ProposalPolicy(capabilities=capabilities, auto_capabilities=auto)


def may_auto_start(policy: ProposalPolicy, info: ProposalInfo, *, auto_started: int) -> bool:
    """A proposal starts by itself only with watch authority, an auto-executable action the user enabled, and budget left."""
    return info.authority == "watch" and info.action in policy.auto_capabilities and auto_started < MAX_AUTO_STARTS_PER_MEETING


def shape_proposals(
    proposed: Sequence[ProposedAction],
    *,
    policy: ProposalPolicy,
    existing: Sequence[CompanionItem],
    investigation_id: str,
    transcript_range: TranscriptRange,
    watch_id: Optional[str],
    watch_authority: bool,
    confidence: float,
) -> List[CompanionItem]:
    """Filter, bound and de-duplicate the model's suggestions into proposal items; never more than the per-run and per-meeting caps."""
    prior = [item for item in existing if item.proposal is not None]
    seen = [content_tokens(f"{item.proposal.title} {item.proposal.instruction}") for item in prior if item.proposal is not None]
    shaped: List[CompanionItem] = []
    for candidate in proposed:
        if len(shaped) >= MAX_PROPOSALS_PER_RUN or len(prior) + len(shaped) >= MAX_PROPOSALS_PER_MEETING:
            break
        if candidate.action not in policy.capabilities:
            continue
        title = normalize_text(candidate.title)[:MAX_TITLE_CHARS].strip()
        instruction = normalize_text(candidate.instruction)[:MAX_INSTRUCTION_CHARS].strip()
        if not title or not instruction:
            continue
        tokens = content_tokens(f"{title} {instruction}")
        if any(jaccard(tokens, earlier) >= DUPLICATE_PROPOSAL_SIMILARITY for earlier in seen):
            continue
        seen.append(tokens)
        shaped.append(
            CompanionItem(
                id=f"it-{uuid.uuid4().hex[:10]}",
                kind="proposal",
                text=title,
                confidence=confidence,
                transcript_range=transcript_range,
                trigger="investigation",
                watch_id=watch_id,
                researched=True,
                investigation_id=investigation_id,
                proposal=ProposalInfo(
                    proposal_id=f"pr-{uuid.uuid4().hex[:8]}",
                    action=candidate.action,
                    title=title,
                    instruction=instruction,
                    authority="watch" if watch_authority else "review",
                ),
            )
        )
    return shaped


@dataclass(frozen=True)
class ProposalDecision:
    """The outcome of one approve, dismiss or automatic start."""

    state: str
    title: str
    instruction: str
    todo_id: Optional[str] = None
    agent_task_id: Optional[str] = None
    error: Optional[str] = None


class ProposalLauncher(Protocol):
    """What the proposals module needs from the To-Do domain."""

    async def create_todo(
        self, *, session_key: str, proposal_id: str, title: str, description: str, excerpt: str, responsibility: str, system_created: bool,
    ) -> str: ...

    async def launch_worker(self, todo_id: str) -> str: ...


AppendProposalEvent = Callable[[Dict[str, Any]], Any]


@dataclass(frozen=True)
class _StartRequest:
    title: str
    description: str
    excerpt: str
    system_created: bool


_in_flight: Set[str] = set()


def _reference(session_key: str) -> str:
    return f"Meeting reference: {session_key}."


def manual_request(info: ProposalInfo, session_key: str) -> _StartRequest:
    """What an approval starts: the instruction the user saw on the card."""
    return _StartRequest(
        title=info.title,
        description=f"{info.instruction}\n\nProposed by the meeting Companion and approved by you. {_reference(session_key)}",
        excerpt=info.instruction[:MAX_EXCERPT_CHARS],
        system_created=False,
    )


def watch_request(watch: CompanionWatch, session_key: str) -> _StartRequest:
    """What an automatic start runs: only the user's own watch wording. No model or transcript text enters it."""
    topic = normalize_text(watch.topic)
    own_words = normalize_text(watch.instruction) or topic
    return _StartRequest(
        title=own_words[:MAX_TITLE_CHARS],
        description=f"{own_words}\n\nStarted automatically by the meeting Companion because your watch for \u201c{topic}\u201d matched. {_reference(session_key)}",
        excerpt=own_words[:MAX_EXCERPT_CHARS],
        system_created=True,
    )


def _event_payload(item: CompanionItem, outcome: ProposalDecision, *, auto: bool) -> Dict[str, Any]:
    assert item.proposal is not None
    payload: Dict[str, Any] = {"item_id": item.id, "proposal_id": item.proposal.proposal_id, "state": outcome.state}
    for key in ("todo_id", "agent_task_id", "error"):
        value = getattr(outcome, key)
        if value:
            payload[key] = value
    if auto:
        payload["auto"] = True
    return payload


async def _start(
    *, info: ProposalInfo, session_key: str, request: _StartRequest, launcher: Optional[ProposalLauncher],
) -> ProposalDecision:
    """Create the To-Do (or reuse the one a failed attempt made) and, for agent work, launch its worker."""
    todo_id = info.todo_id
    try:
        if launcher is None:
            raise ProposalLaunchError("Starting actions is not available right now.")
        if todo_id is None:
            todo_id = await launcher.create_todo(
                session_key=session_key,
                proposal_id=info.proposal_id,
                title=request.title,
                description=request.description,
                excerpt=request.excerpt,
                responsibility="agent" if info.action == "agent_task" else "unspecified",
                system_created=request.system_created,
            )
        agent_task_id = await launcher.launch_worker(todo_id) if info.action == "agent_task" else None
    except ProposalLaunchError as error:
        return ProposalDecision("failed", info.title, info.instruction, todo_id=todo_id, error=str(error))
    except Exception as error:
        logger.error("Companion proposal %s could not be started: %s", info.proposal_id, error, exc_info=True)
        return ProposalDecision("failed", info.title, info.instruction, todo_id=todo_id, error="The action could not be started.")
    return ProposalDecision("started", info.title, info.instruction, todo_id=todo_id, agent_task_id=agent_task_id)


async def decide_proposal(
    *,
    session_key: str,
    item: Optional[CompanionItem],
    decision: str,
    launcher: Optional[ProposalLauncher],
    append: AppendProposalEvent,
) -> ProposalDecision:
    """Approve or dismiss a proposal and record the outcome with ``append``; raises ``ProposalNotFound`` or ``ProposalRejected``."""
    if item is None:
        raise ProposalNotFound("That Companion item does not exist.")
    info = item.proposal
    if info is None:
        raise ProposalRejected("That item is not a proposal.")
    if decision not in ("approve", "dismiss"):
        raise ProposalRejected("Choose approve or dismiss.")
    key = f"{session_key}:{info.proposal_id}"
    if key in _in_flight:
        raise ProposalRejected("That action is already starting.")
    if info.state in ("started", "handed_off"):
        raise ProposalRejected("That action was already started.")
    if decision == "dismiss":
        outcome = ProposalDecision("dismissed", info.title, info.instruction)
        if info.state != "dismissed":
            append(_event_payload(item, outcome, auto=False))
        return outcome
    if info.state == "dismissed" or item.dismissed:
        raise ProposalRejected("That proposal was dismissed.")
    _in_flight.add(key)
    try:
        if info.action == "assistant_session":
            outcome = ProposalDecision("handed_off", info.title, info.instruction)
        else:
            outcome = await _start(info=info, session_key=session_key, request=manual_request(info, session_key), launcher=launcher)
        append(_event_payload(item, outcome, auto=False))
    finally:
        _in_flight.discard(key)
    return outcome


async def auto_start_proposal(
    *,
    session_key: str,
    item: CompanionItem,
    watch: CompanionWatch,
    launcher: Optional[ProposalLauncher],
    append: AppendProposalEvent,
    still_allowed: Callable[[], bool],
) -> None:
    """Start a watch-authorized proposal without a click; never raises. ``still_allowed`` is re-checked at the last moment so a changed setting, a manual decision or a closed session wins."""
    info = item.proposal
    if info is None or info.action not in AUTO_CAPABLE_ACTIONS:
        return
    key = f"{session_key}:{info.proposal_id}"
    if key in _in_flight or not still_allowed():
        return
    _in_flight.add(key)
    try:
        outcome = await _start(info=info, session_key=session_key, request=watch_request(watch, session_key), launcher=launcher)
        append(_event_payload(item, outcome, auto=True))
    except Exception as error:
        logger.error("Companion automatic start of %s failed: %s", info.proposal_id, error, exc_info=True)
    finally:
        _in_flight.discard(key)
