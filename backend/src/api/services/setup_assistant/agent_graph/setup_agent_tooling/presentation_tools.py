"""Presentation-oriented setup-agent tool handlers."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Awaitable, Callable, List, Optional

from api.routes.setup_assistant.models import (
    SetupAgentEvent,
    SetupAgentEventKind,
    SetupOrientationTone,
)

from .schemas import (
    SETUP_MESSAGE_DELTA_CHARS,
    SETUP_MESSAGE_DELTA_DELAY_SECONDS,
    SetupSuggestionChipInput,
)


async def note_setup_observation(
    factory,
    label: str,
    title: str,
    detail: str,
    tone: SetupOrientationTone = SetupOrientationTone.ready,
) -> str:
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.observation_added,
            payload={
                "id": f"observation-{uuid.uuid4().hex[:12]}",
                "label": label,
                "title": title,
                "detail": detail,
                "tone": tone.value if isinstance(tone, SetupOrientationTone) else str(tone),
            },
        )
    )
    return "Observation surfaced."


async def narrate_setup_progress(factory, message: str) -> str:
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.progress_narration,
            payload={"message": message},
        )
    )
    # Stamp the staleness clock so a slow tool's automatic opening narration
    # does not immediately overwrite the agent's own narration when they fire
    # back-to-back. Matches the same stamp inside ``emit_tool_narration``.
    factory.last_narration_emitted_at = time.monotonic()
    return "Narration sent."


async def set_setup_suggestion_chips(
    factory, chips: List[SetupSuggestionChipInput]
) -> str:
    normalized_chips = []
    for chip in chips[:4]:
        chip_payload = chip.model_dump(mode="json")
        if not (chip_payload.get("preliminary_status_message") or "").strip():
            chip_payload["preliminary_status_message"] = (
                f"Getting started on: {chip.label.rstrip('.')}."
            )
        normalized_chips.append(chip_payload)

    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.chips_set,
            payload={"chips": normalized_chips},
        )
    )
    return "Suggestion chips updated."


async def say_setup_message(factory, content: str) -> str:
    await stream_setup_message(factory.event_emitter, content)
    return "Message sent."


async def stream_setup_message(
    event_emitter: Callable[[SetupAgentEvent], Awaitable[None]],
    content: str,
    message_id: Optional[str] = None,
) -> str:
    """Emit one Basil message as started, paced word-boundary deltas, then completed; returns the message id."""
    resolved_message_id = message_id or f"message-{uuid.uuid4().hex[:12]}"
    await event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.message_started,
            payload={"id": resolved_message_id, "role": "basil"},
        )
    )
    for delta in chunk_setup_message_content(content):
        await event_emitter(
            SetupAgentEvent(
                kind=SetupAgentEventKind.message_delta,
                payload={"id": resolved_message_id, "delta": delta},
            )
        )
        await asyncio.sleep(SETUP_MESSAGE_DELTA_DELAY_SECONDS)
    await event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.message_completed,
            payload={"id": resolved_message_id, "role": "basil", "content": content},
        )
    )
    return resolved_message_id


def chunk_setup_message_content(content: str) -> List[str]:
    chunks: List[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= SETUP_MESSAGE_DELTA_CHARS:
            chunks.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, SETUP_MESSAGE_DELTA_CHARS + 1)
        if split_at <= 0:
            split_at = SETUP_MESSAGE_DELTA_CHARS
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return chunks


async def propose_setup_wrap_up(
    factory,
    recap: str,
    recommended_next_steps: Optional[List[SetupSuggestionChipInput]] = None,
    optional_breadth: Optional[str] = None,
) -> str:
    normalized_next_steps = [
        chip.model_dump(mode="json")
        for chip in (recommended_next_steps or [])[:4]
    ]
    normalized_optional_breadth = (
        optional_breadth.strip()
        if isinstance(optional_breadth, str) and optional_breadth.strip()
        else None
    )
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.wrap_up_proposed,
            payload={
                "recap": recap,
                "recommended_next_steps": normalized_next_steps,
                "optional_breadth": normalized_optional_breadth,
            },
        )
    )
    return "Wrap-up surfaced for the user."
