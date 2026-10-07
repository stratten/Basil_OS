"""Durable timeline entries for the moments an agent task waits on, and hears back from, the user."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional, Sequence

from .agent_timeline_contract import build_timeline_event, normalize_timeline_entry, timeline_timestamp
from .timeline_persistence import persist_timeline_entry

logger = logging.getLogger(__name__)

USER_INTERACTION_DETAIL_KIND = "user_interaction"

USER_INTERACTION_KINDS = frozenset({
    "clarification",
    "approval",
    "credential",
    "provider_target",
    "command_input",
    "provider_input",
    "provider_permission",
    "guidance",
    "pause",
})

USER_INTERACTION_STATUSES = frozenset({
    "waiting",
    "answered",
    "dismissed",
    "approved",
    "denied",
    "timed_out",
    "canceled",
    "resolved",
})

Broadcast = Callable[[Dict[str, Any]], Awaitable[Any]]

# Requests this process announced and has not yet resolved. The durable timeline is rewritten whole by several
# independent writers, so a waiting entry can be lost before its answer arrives; this lets the answer still reach
# the UI and the saved timeline instead of leaving the request showing as waiting.
_PENDING_ASKED_LIMIT = 512
_pending_asked: "OrderedDict[tuple[str, str], Dict[str, Any]]" = OrderedDict()

_WAITING_TITLES = {
    "clarification": "Basil asked you a question",
    "approval": "Waiting for your approval",
    "credential": "Waiting for Keychain access",
    "provider_target": "Basil asked you to confirm a target",
    "command_input": "A command asked for your input",
    "provider_input": "A provider asked for your input",
    "provider_permission": "A provider asked for your permission",
    "guidance": "Your note is queued for Basil's next step",
    "pause": "You paused Basil",
}

_RESOLVED_TITLES = {
    "answered": "You answered",
    "dismissed": "You closed the question without answering",
    "approved": "You approved",
    "denied": "You declined",
    "timed_out": "No response before the time limit",
    "canceled": "The request was canceled",
    "resolved": "You responded",
}

_RESOLVED_TITLES_BY_KIND = {
    ("guidance", "resolved"): "Basil received your note",
    ("guidance", "canceled"): "Basil finished before reading your note",
    ("pause", "resolved"): "You resumed the run",
    ("pause", "canceled"): "The paused run was stopped",
}


def user_interaction_entry_id(interaction_id: str) -> str:
    return f"user_interaction_{interaction_id}"


def checkpoint_interaction_kind(checkpoint_data: Mapping[str, Any]) -> str:
    metadata = checkpoint_data.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("source") == "provider_target_authorization":
        return "provider_target"
    return "clarification"


def build_user_interaction_entry(
    *,
    interaction_id: str,
    kind: str,
    prompt: str,
    status: str = "waiting",
    asked_at: Optional[str] = None,
    input_type: Optional[str] = None,
    options: Optional[Sequence[Any]] = None,
    response: Optional[str] = None,
    response_hidden: bool = False,
    responded_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Return one complete contract entry describing a single ask/response exchange."""
    if kind not in USER_INTERACTION_KINDS:
        raise ValueError(f"Unknown user interaction kind: {kind!r}")
    if status not in USER_INTERACTION_STATUSES:
        raise ValueError(f"Unknown user interaction status: {status!r}")
    asked_at = asked_at or timeline_timestamp()
    title = (
        _WAITING_TITLES[kind]
        if status == "waiting"
        else _RESOLVED_TITLES_BY_KIND.get((kind, status), _RESOLVED_TITLES[status])
    )
    interaction: Dict[str, Any] = {
        "interaction_id": interaction_id,
        "kind": kind,
        "status": status,
        "prompt": prompt,
        "asked_at": asked_at,
    }
    if input_type:
        interaction["input_type"] = input_type
    normalized_options = [str(option) for option in options or [] if str(option).strip()]
    if normalized_options:
        interaction["options"] = normalized_options
    if response_hidden:
        interaction["response_hidden"] = True
    elif response is not None:
        interaction["response"] = response
    if responded_at:
        interaction["responded_at"] = responded_at
    return normalize_timeline_entry({
        "id": user_interaction_entry_id(interaction_id),
        "type": "step",
        "timestamp": asked_at,
        "title": title,
        "content": prompt or title,
        "body": prompt or title,
        "detail_kind": USER_INTERACTION_DETAIL_KIND,
        "source": "user_interaction",
        "correlation_id": user_interaction_entry_id(interaction_id),
        "metadata": {"user_interaction": interaction},
    })


async def _broadcast_entry(agent_task_id: str, entry: Mapping[str, Any], broadcast: Optional[Broadcast]) -> None:
    if broadcast is None:
        return
    event = build_timeline_event(entry)
    event["event_type"] = "agent_task_step_detail"
    event["agent_task_id"] = agent_task_id
    try:
        await broadcast(event)
    except Exception:
        logger.exception("Failed to broadcast user interaction %s", entry.get("id"))


async def record_user_interaction_asked(
    agent_task_id: Optional[str],
    *,
    interaction_id: Optional[str],
    kind: str,
    prompt: str,
    input_type: Optional[str] = None,
    options: Optional[Sequence[Any]] = None,
    broadcast: Optional[Broadcast] = None,
) -> None:
    """Persist and announce that the task is now waiting on the user; never raises."""
    if not agent_task_id or not interaction_id:
        return
    try:
        entry = build_user_interaction_entry(
            interaction_id=str(interaction_id),
            kind=kind,
            prompt=prompt,
            input_type=input_type,
            options=options,
        )
        await persist_timeline_entry(agent_task_id, entry, replace_existing=True, preserve_position=True)
        _remember_asked(agent_task_id, entry["metadata"]["user_interaction"])
        await _broadcast_entry(agent_task_id, entry, broadcast)
    except Exception:
        logger.exception("Failed to record user interaction request %s", interaction_id)


async def record_user_interaction_entry(
    agent_task_id: Optional[str],
    *,
    interaction_id: Optional[str],
    kind: str,
    prompt: str,
    status: str,
    asked_at: Optional[str] = None,
    response: Optional[str] = None,
    broadcast: Optional[Broadcast] = None,
) -> None:
    """Persist and announce one exchange in a single step, already in its final status; never raises."""
    if not agent_task_id or not interaction_id:
        return
    try:
        entry = build_user_interaction_entry(
            interaction_id=str(interaction_id),
            kind=kind,
            prompt=prompt,
            status=status,
            asked_at=asked_at,
            response=response,
            responded_at=None if status == "waiting" else timeline_timestamp(),
        )
        await persist_timeline_entry(agent_task_id, entry, replace_existing=True, preserve_position=True)
        await _broadcast_entry(agent_task_id, entry, broadcast)
    except Exception:
        logger.exception("Failed to record user interaction %s", interaction_id)


async def _load_timeline(agent_task_id: str) -> list:
    from api.dependencies import get_sqlite_knowledge_service

    record = await get_sqlite_knowledge_service().get_agent_task(agent_task_id)
    return list(getattr(record, "execution_timeline", None) or []) if record else []


def _interaction_of(entry: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(entry, Mapping) or entry.get("detail_kind") != USER_INTERACTION_DETAIL_KIND:
        return None
    metadata = entry.get("metadata")
    interaction = metadata.get("user_interaction") if isinstance(metadata, Mapping) else None
    return interaction if isinstance(interaction, Mapping) else None


def _remember_asked(agent_task_id: str, interaction: Mapping[str, Any]) -> None:
    key = (agent_task_id, str(interaction.get("interaction_id")))
    _pending_asked[key] = dict(interaction)
    _pending_asked.move_to_end(key)
    while len(_pending_asked) > _PENDING_ASKED_LIMIT:
        _pending_asked.popitem(last=False)


def _waiting_interactions(
    agent_task_id: str,
    timeline: Iterable[Any],
    kinds: Optional[Iterable[str]] = None,
) -> list[Mapping[str, Any]]:
    """Requests still waiting on the user, oldest first: those in the saved timeline plus announced ones the saved timeline lost."""
    recorded = [interaction for interaction in (_interaction_of(entry) for entry in timeline) if interaction is not None]
    saved_ids = {str(interaction.get("interaction_id")) for interaction in recorded}
    waiting = [interaction for interaction in recorded if interaction.get("status") == "waiting"]
    waiting.extend(
        interaction
        for (task_id, interaction_id), interaction in _pending_asked.items()
        if task_id == agent_task_id and interaction_id not in saved_ids
    )
    allowed = set(kinds) if kinds is not None else None
    return sorted(
        (interaction for interaction in waiting if allowed is None or interaction.get("kind") in allowed),
        key=lambda interaction: str(interaction.get("asked_at") or ""),
    )


def user_run_notes_from_timeline(timeline: Iterable[Any]) -> list[str]:
    """Notes Basil read during the run and notes added on resume, oldest first."""
    notes: list[str] = []
    for entry in timeline:
        interaction = _interaction_of(entry)
        if interaction is None or interaction.get("status") != "resolved":
            continue
        kind = interaction.get("kind")
        if kind == "guidance":
            text = interaction.get("prompt")
        elif kind == "pause":
            text = interaction.get("response")
        else:
            continue
        if isinstance(text, str) and text.strip():
            notes.append(text.strip())
    return notes


async def user_run_notes_context(agent_task_id: Optional[str]) -> Optional[str]:
    """Describe the user's mid-run notes for the outcome evaluator; never raises."""
    if not agent_task_id:
        return None
    try:
        notes = user_run_notes_from_timeline(await _load_timeline(agent_task_id))
    except Exception:
        logger.exception("Could not load run notes for %s", agent_task_id)
        return None
    if not notes:
        return None
    lines = "\n".join(f"- {note[:1000]}" for note in notes)
    return (
        "NOTES THE USER SENT DURING THIS RUN (oldest first). These amend the original request; "
        "when a note changes the scope, judge the result against the request as amended, and let later notes win:\n"
        f"{lines}"
    )


async def record_user_interaction_resolved(
    agent_task_id: Optional[str],
    *,
    interaction_id: Optional[str],
    status: str,
    response: Optional[str] = None,
    response_hidden: bool = False,
    broadcast: Optional[Broadcast] = None,
) -> None:
    """Update the recorded request with the user's response in place; never raises."""
    if not agent_task_id or not interaction_id:
        return
    try:
        entry_id = user_interaction_entry_id(str(interaction_id))
        existing = next(
            (
                _interaction_of(entry)
                for entry in await _load_timeline(agent_task_id)
                if isinstance(entry, Mapping) and entry.get("id") == entry_id
            ),
            None,
        )
        if existing is None:
            existing = _pending_asked.get((agent_task_id, str(interaction_id)))
        if existing is None:
            return
        await _persist_resolution(agent_task_id, existing, status, response, response_hidden, broadcast)
    except Exception:
        logger.exception("Failed to record user interaction response %s", interaction_id)


async def resolve_latest_waiting_user_interaction(
    agent_task_id: Optional[str],
    *,
    kinds: Iterable[str],
    status: str,
    response: Optional[str] = None,
    broadcast: Optional[Broadcast] = None,
) -> None:
    """Resolve the newest still-waiting request of the given kinds; never raises."""
    if not agent_task_id:
        return
    try:
        waiting = _waiting_interactions(agent_task_id, await _load_timeline(agent_task_id), kinds)
        if not waiting:
            return
        await _persist_resolution(agent_task_id, waiting[-1], status, response, False, broadcast)
    except Exception:
        logger.exception("Failed to resolve the waiting user interaction for %s", agent_task_id)


def close_waiting_interactions_in_timeline(
    timeline: Iterable[Any],
    *,
    status: str = "canceled",
) -> tuple[list, int]:
    """Return the timeline with every still-waiting user interaction closed, and how many were closed. Pure, so durable startup reconciliation and the live cancel path share one definition of stale."""
    closed = 0
    updated: list = []
    for entry in timeline:
        interaction = _interaction_of(entry)
        if interaction is None or interaction.get("status") != "waiting":
            updated.append(entry)
            continue
        updated.append(
            build_user_interaction_entry(
                interaction_id=str(interaction.get("interaction_id")),
                kind=str(interaction.get("kind")),
                prompt=str(interaction.get("prompt") or ""),
                status=status,
                asked_at=interaction.get("asked_at") if isinstance(interaction.get("asked_at"), str) else None,
                input_type=interaction.get("input_type") if isinstance(interaction.get("input_type"), str) else None,
                options=interaction.get("options") if isinstance(interaction.get("options"), list) else None,
                responded_at=timeline_timestamp(),
            )
        )
        closed += 1
    return updated, closed


async def resolve_all_waiting_user_interactions(
    agent_task_id: Optional[str],
    *,
    status: str = "canceled",
    broadcast: Optional[Broadcast] = None,
) -> int:
    """Close every request still waiting on the user (the run that asked it has ended); returns how many were closed and never raises."""
    if not agent_task_id:
        return 0
    try:
        waiting = _waiting_interactions(agent_task_id, await _load_timeline(agent_task_id))
        for interaction in waiting:
            await _persist_resolution(agent_task_id, interaction, status, None, False, broadcast)
        return len(waiting)
    except Exception:
        logger.exception("Failed to close waiting user interactions for %s", agent_task_id)
        return 0


async def _persist_resolution(
    agent_task_id: str,
    existing: Mapping[str, Any],
    status: str,
    response: Optional[str],
    response_hidden: bool,
    broadcast: Optional[Broadcast],
) -> None:
    entry = build_user_interaction_entry(
        interaction_id=str(existing.get("interaction_id")),
        kind=str(existing.get("kind")),
        prompt=str(existing.get("prompt") or ""),
        status=status,
        asked_at=existing.get("asked_at") if isinstance(existing.get("asked_at"), str) else None,
        input_type=existing.get("input_type") if isinstance(existing.get("input_type"), str) else None,
        options=existing.get("options") if isinstance(existing.get("options"), list) else None,
        response=response,
        response_hidden=response_hidden,
        responded_at=timeline_timestamp(),
    )
    try:
        await persist_timeline_entry(agent_task_id, entry, replace_existing=True, preserve_position=True)
    except Exception:
        logger.exception("Failed to save the resolution of user interaction %s", existing.get("interaction_id"))
    _pending_asked.pop((agent_task_id, str(existing.get("interaction_id"))), None)
    await _broadcast_entry(agent_task_id, entry, broadcast)
