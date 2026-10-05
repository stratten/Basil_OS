"""Durable timeline entries for the moments an agent task waits on, and hears back from, the user."""

from __future__ import annotations

import logging
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
})

USER_INTERACTION_STATUSES = frozenset({
    "waiting",
    "answered",
    "dismissed",
    "approved",
    "denied",
    "timed_out",
    "cancelled",
    "resolved",
})

Broadcast = Callable[[Dict[str, Any]], Awaitable[Any]]

_WAITING_TITLES = {
    "clarification": "Basil asked you a question",
    "approval": "Waiting for your approval",
    "credential": "Waiting for Keychain access",
    "provider_target": "Basil asked you to confirm a target",
    "command_input": "A command asked for your input",
    "provider_input": "A provider asked for your input",
    "provider_permission": "A provider asked for your permission",
}

_RESOLVED_TITLES = {
    "answered": "You answered",
    "dismissed": "You closed the question without answering",
    "approved": "You approved",
    "denied": "You declined",
    "timed_out": "No response before the time limit",
    "cancelled": "The request was cancelled",
    "resolved": "You responded",
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
    title = _WAITING_TITLES[kind] if status == "waiting" else _RESOLVED_TITLES[status]
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
        await _broadcast_entry(agent_task_id, entry, broadcast)
    except Exception:
        logger.exception("Failed to record user interaction request %s", interaction_id)


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
        allowed = set(kinds)
        waiting = [
            interaction
            for interaction in (_interaction_of(entry) for entry in await _load_timeline(agent_task_id))
            if interaction is not None
            and interaction.get("status") == "waiting"
            and interaction.get("kind") in allowed
        ]
        if not waiting:
            return
        await _persist_resolution(agent_task_id, waiting[-1], status, response, False, broadcast)
    except Exception:
        logger.exception("Failed to resolve the waiting user interaction for %s", agent_task_id)


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
    await persist_timeline_entry(agent_task_id, entry, replace_existing=True, preserve_position=True)
    await _broadcast_entry(agent_task_id, entry, broadcast)
