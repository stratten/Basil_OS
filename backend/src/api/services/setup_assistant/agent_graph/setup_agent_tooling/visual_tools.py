"""Inline visual setup-agent tool handler.

Surfaces one of the curated images in
``setup_visual_catalog.SETUP_VISUAL_CATALOG`` into the conversation
via the ``setup_visual_shown`` SSE event. The frontend reducer
attaches the resulting ``SetupInlineVisual`` to the most recent
Basil message so a single Basil turn that calls ``say`` and then
``show_setup_visual`` ends up rendering the image inline beneath
the spoken text.

Validation is intentionally strict: unknown ``visual_id`` slugs
return a corrective string back to the agent's tool-result loop
listing the available ids, rather than emitting an event the
frontend would silently drop. This keeps hallucinated paths from
ever reaching the UI.
"""

from __future__ import annotations

import uuid
from typing import Optional

from api.routes.setup_assistant.models import (
    SetupAgentEvent,
    SetupAgentEventKind,
    SetupInlineVisual,
)
from api.services.setup_assistant.agent_graph.setup_visual_catalog import (
    available_visual_ids,
    get_setup_visual,
)


async def show_setup_visual(
    factory,
    visual_id: str,
    caption_override: Optional[str] = None,
) -> str:
    """Emit an inline visual card for the requested catalog entry."""

    visual = get_setup_visual(visual_id)
    if visual is None:
        known = ", ".join(available_visual_ids())
        return (
            f"Unknown visual_id '{visual_id}'. No card was shown. "
            f"Available visual ids: {known}. "
            "Pick one of these or omit the call."
        )

    effective_caption = (
        caption_override.strip()
        if caption_override and caption_override.strip()
        else visual.caption
    )

    inline = SetupInlineVisual(
        id=f"inline-visual-{uuid.uuid4().hex[:12]}",
        visual_id=visual.id,
        web_path=visual.web_path,
        secondary_web_path=visual.secondary_web_path,
        caption=effective_caption,
        alt=visual.alt,
        secondary_alt=visual.secondary_alt,
        kind=visual.kind,
        related_agenda_item_id=visual.related_agenda_item_id,
        caption_override=caption_override,
    )

    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.setup_visual_shown,
            payload={"visual": inline.model_dump(mode="json")},
        )
    )

    return (
        f"Visual '{visual.id}' shown inline. "
        "Continue the conversation; do not call show_setup_visual "
        "again for the same id in this turn."
    )
