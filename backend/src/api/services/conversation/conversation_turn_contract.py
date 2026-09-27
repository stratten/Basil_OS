"""Durable route metadata for Conversation turns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Final


CONVERSATION_TURN_METADATA_KEY: Final = "conversation_turn"
_LEGACY_AGENT_TASK_ROUTE_VALUES: Final = frozenset({"contextual_agent", "delegated_agent"})
MAX_CONVERSATION_NARRATION_ATTEMPTS: Final = 3
CONVERSATION_TURN_STALE_AFTER: Final = timedelta(hours=6)


class ConversationTurnRoute(StrEnum):
    """The durable execution route selected for one Conversation turn."""

    DIRECT = "direct"
    AGENT_TASK = "agent_task"


@dataclass(frozen=True)
class ConversationTaskContinuationCandidate:
    """A server-authorized Conversation-owned task chain available to the router."""

    candidate_id: int
    root_task_id: str
    previous_task_id: str
    request_text: str
    outcome_text: str
    terminal_status: str


class ConversationTurnLifecycle(StrEnum):
    """The durable lifecycle state for a routed assistant placeholder."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConversationTurnNarrationLifecycle(StrEnum):
    """The durable state of post-Agent Task Conversation narration."""

    PENDING = "pending"
    READY = "ready"
    NARRATING = "narrating"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ConversationTurnNarrationMetadata:
    """Validated durable state for later normal Conversation narration."""

    lifecycle: ConversationTurnNarrationLifecycle
    attempt_count: int


@dataclass(frozen=True)
class ConversationTurnMetadata:
    """Validated durable metadata carried by a routed assistant placeholder."""

    route: ConversationTurnRoute
    lifecycle: ConversationTurnLifecycle
    agent_task_id: str | None
    terminal_outcome: str | None
    user_message_id: str | None
    narration: ConversationTurnNarrationMetadata


def is_terminal_conversation_turn_lifecycle(lifecycle: ConversationTurnLifecycle) -> bool:
    """Return whether a turn lifecycle cannot transition further."""
    return lifecycle in {
        ConversationTurnLifecycle.COMPLETED,
        ConversationTurnLifecycle.FAILED,
        ConversationTurnLifecycle.CANCELLED,
    }


def is_active_conversation_turn_lifecycle(lifecycle: ConversationTurnLifecycle) -> bool:
    """Return whether a turn still needs a durable terminal outcome."""
    return lifecycle in {
        ConversationTurnLifecycle.PENDING,
        ConversationTurnLifecycle.RUNNING,
    }


def is_terminal_conversation_turn_metadata(raw_metadata: Any) -> bool:
    """Return whether raw persisted turn metadata carries a terminal lifecycle."""
    parsed = parse_conversation_turn_metadata(raw_metadata)
    return parsed is not None and is_terminal_conversation_turn_lifecycle(parsed.lifecycle)


def is_conversation_turn_metadata_active(raw_metadata: Any) -> bool:
    """Return whether the most recent routed turn for a conversation is still active."""
    parsed = parse_conversation_turn_metadata(raw_metadata)
    if parsed is None:
        return False
    if not is_terminal_conversation_turn_lifecycle(parsed.lifecycle):
        return True
    if parsed.route is not ConversationTurnRoute.AGENT_TASK:
        return False
    return parsed.narration.lifecycle in {
        ConversationTurnNarrationLifecycle.READY,
        ConversationTurnNarrationLifecycle.NARRATING,
        ConversationTurnNarrationLifecycle.RETRYING,
    }


def parse_conversation_turn_metadata(metadata: Any) -> ConversationTurnMetadata | None:
    """Validate legacy-safe routed-turn metadata without raising during reload."""
    if not isinstance(metadata, dict):
        return None
    raw_turn = metadata.get(CONVERSATION_TURN_METADATA_KEY)
    if not isinstance(raw_turn, dict):
        return None
    raw_route = raw_turn.get("route")
    if isinstance(raw_route, str) and raw_route in _LEGACY_AGENT_TASK_ROUTE_VALUES:
        route = ConversationTurnRoute.AGENT_TASK
    else:
        try:
            route = ConversationTurnRoute(raw_route)
        except (TypeError, ValueError):
            return None
    try:
        lifecycle = ConversationTurnLifecycle(raw_turn.get("lifecycle"))
    except (TypeError, ValueError):
        return None
    agent_task_id = raw_turn.get("agent_task_id")
    if agent_task_id is not None and (not isinstance(agent_task_id, str) or not agent_task_id.strip()):
        return None
    terminal_outcome = raw_turn.get("terminal_outcome")
    if terminal_outcome is not None and not isinstance(terminal_outcome, str):
        return None
    user_message_id = raw_turn.get("user_message_id")
    if user_message_id is not None and (
        not isinstance(user_message_id, str) or not user_message_id.strip()
    ):
        return None
    raw_narration = raw_turn.get("narration")
    if raw_narration is None:
        narration = ConversationTurnNarrationMetadata(
            lifecycle=ConversationTurnNarrationLifecycle.PENDING,
            attempt_count=0,
        )
    elif isinstance(raw_narration, dict):
        try:
            narration_lifecycle = ConversationTurnNarrationLifecycle(raw_narration.get("lifecycle"))
        except (TypeError, ValueError):
            return None
        raw_attempt_count = raw_narration.get("attempt_count", 0)
        if isinstance(raw_attempt_count, bool) or not isinstance(raw_attempt_count, int):
            return None
        if raw_attempt_count < 0 or raw_attempt_count > MAX_CONVERSATION_NARRATION_ATTEMPTS:
            return None
        narration = ConversationTurnNarrationMetadata(
            lifecycle=narration_lifecycle,
            attempt_count=raw_attempt_count,
        )
    else:
        return None
    return ConversationTurnMetadata(
        route=route,
        lifecycle=lifecycle,
        agent_task_id=agent_task_id,
        terminal_outcome=terminal_outcome,
        user_message_id=user_message_id,
        narration=narration,
    )


def build_conversation_turn_placeholder_metadata(
    route: ConversationTurnRoute,
) -> dict[str, Any]:
    """Build the initial metadata for a durable routed assistant placeholder."""
    return {
        CONVERSATION_TURN_METADATA_KEY: {
            "route": route.value,
            "lifecycle": ConversationTurnLifecycle.PENDING.value,
            "agent_task_id": None,
            "terminal_outcome": None,
            "user_message_id": None,
            "narration": {
                "lifecycle": ConversationTurnNarrationLifecycle.PENDING.value,
                "attempt_count": 0,
            },
        }
    }
