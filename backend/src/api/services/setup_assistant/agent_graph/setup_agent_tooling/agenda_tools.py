"""Session-agenda setup-agent tool handlers.

Three tools live here, all of which fire SSE events the frontend
reducer consumes:

- ``propose_session_agenda(items)`` — wholesale replacement of the
  session agenda. Called once early in conversation phase (and
  potentially re-called if the agent wants to restructure mid-flow).
  The frontend clears any prior agenda and adopts the new list in
  the order provided.

- ``mark_agenda_item(id, status, completion_basis?)`` — per-item
  status update. Called whenever the agent picks an item up
  (``in_progress``), an item is unambiguously done (``completed``),
  the user opts out (``skipped``), or the item makes sense to revisit
  later (``deferred``).

- ``request_agenda_item_confirmation(agenda_item_id, prompt)`` —
  emits an inline confirmation card asking the user whether a
  literacy/demo item landed. Used when there's no observable
  side-effect to confirm completion from; the user's response comes
  back as a system observation in the next turn so the agent can
  react.

Tools return short confirmation strings to the agent's tool-result
loop so it can decide what to do next without re-reading the SSE
stream.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from api.routes.setup_assistant.models import (
    SetupAgendaConfirmationRequest,
    SetupAgendaItemMark,
    SetupAgentEvent,
    SetupAgentEventKind,
    SetupSessionAgendaItem,
    SetupSessionAgendaItemStatus,
    SetupSessionAgendaProposal,
)

from .schemas import SetupAgendaItemInput


async def propose_session_agenda(
    factory,
    items: List[SetupAgendaItemInput],
) -> str:
    """Replace the current session agenda with the supplied items."""

    validated_items = [
        SetupSessionAgendaItem(
            id=item.id,
            title=item.title,
            intent=item.intent,
            kind=item.kind,
            source=item.source,
            status=item.status,
            completion_basis=item.completion_basis,
        )
        for item in items
    ]
    proposal = SetupSessionAgendaProposal(items=validated_items)
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.agenda_proposed,
            payload={"proposal": proposal.model_dump(mode="json")},
        )
    )
    return f"Session agenda set with {len(validated_items)} item(s)."


async def mark_agenda_item(
    factory,
    id: str,
    status: SetupSessionAgendaItemStatus,
    completion_basis: Optional[str] = None,
) -> str:
    """Update a single agenda item's status and (optional) completion basis."""

    mark = SetupAgendaItemMark(
        id=id,
        status=status,
        completion_basis=completion_basis,
    )
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.agenda_item_marked,
            payload={"mark": mark.model_dump(mode="json")},
        )
    )
    return f"Agenda item '{id}' marked {status.value}."


async def request_agenda_item_confirmation(
    factory,
    agenda_item_id: str,
    prompt: str,
) -> str:
    """Emit an inline 'did this land?' confirmation card for an agenda item."""

    confirmation = SetupAgendaConfirmationRequest(
        id=f"agenda-confirm-{uuid.uuid4().hex[:12]}",
        agenda_item_id=agenda_item_id,
        prompt=prompt,
    )
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.agenda_confirmation_requested,
            payload={"confirmation": confirmation.model_dump(mode="json")},
        )
    )
    return (
        f"Confirmation card surfaced for agenda item '{agenda_item_id}'. "
        "Wait for the user's response before changing the item's status."
    )
