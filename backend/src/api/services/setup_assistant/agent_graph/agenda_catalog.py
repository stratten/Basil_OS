"""Curated seed catalog for the setup-assistant session agenda.

The setup agent treats this catalog as a *menu*, not a checklist: it
receives the applicable entries in the first conversation-phase turn
via the request's `agenda_items` field, then calls
`propose_session_agenda` with whatever subset (plus any agent-authored
additions) it actually intends to work through. Entries here cover
ground that would otherwise be missed without an explicit prompt --
notably the UI-literacy items that used to live in the deprecated
Swift onboarding flow (status-bubble colors, menu bar item states,
agent-task widget walkthrough) -- and the operational basics
(starter model downloads, mail connection, writing-voice samples)
that depend on actual machine state.

Applicability is computed off the same `SetupDiscoveryFact` list the
orientation phase already collects (see
`SetupAssistantDiscoveryService`), so no new discovery work is
required to surface the seed. Predicates intentionally err on the
side of inclusion: when in doubt, ship the item and let the agent
trim it.

This module is pure data + pure functions -- no IO, no imports from
the heavier service layer -- so it can be unit-tested in isolation
and imported anywhere in the setup graph without circular concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from api.routes.setup_assistant.models import SetupDiscoveryFact
from api.services.setup_assistant.agent_graph.setup_visual_catalog import (
    primary_visual_id_for_agenda_item,
)


AgendaItemKind = str  # "action" | "demo" | "literacy" | "conversational"
AgendaItemSource = str  # "catalog" | "agent"
AgendaItemStatus = str  # "pending" | "in_progress" | "completed" | "skipped" | "deferred"


@dataclass(frozen=True)
class CatalogAgendaItem:
    """A single entry in the curated agenda starter catalog."""

    id: str
    title: str
    intent: str
    kind: AgendaItemKind
    applicability: Callable[[Sequence[SetupDiscoveryFact]], bool] = field(
        default=lambda _facts: True
    )
    # Explicit override for the paired visual id. When None, the seed
    # dict falls back to the canonical pairing computed from the visual
    # catalog (via primary_visual_id_for_agenda_item). Set this only
    # when an item should advertise a non-canonical visual or when the
    # visual catalog has multiple matches and you want to pin which
    # one the seed advertises.
    default_visual_id: Optional[str] = None

    def to_seed_dict(self) -> Dict[str, Any]:
        """Render as the JSON-friendly seed shape the agent receives.

        Status/completion_basis are included so the seed matches the
        round-trip shape the agent will produce via
        `propose_session_agenda`; defaults reflect "fresh, untouched".

        ``default_visual_id`` is surfaced only when a pairing exists
        (either explicitly set on the dataclass or resolved from the
        visual catalog). When omitted, the agent treats the item as
        having no paired visual and won't call ``show_setup_visual``
        for it without an explicit override.
        """

        seed: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "intent": self.intent,
            "kind": self.kind,
            "source": "catalog",
            "status": "pending",
            "completion_basis": None,
        }
        visual_id = self.default_visual_id or primary_visual_id_for_agenda_item(self.id)
        if visual_id is not None:
            seed["default_visual_id"] = visual_id
        return seed


# --- Applicability predicates ------------------------------------------------
# Kept small, readable, and parameterized by fact-id prefix / metadata so
# the catalog body stays declarative.

def _has_starter_model_missing(facts: Sequence[SetupDiscoveryFact]) -> bool:
    """True if any starter reasoning/general model is not yet on disk."""

    for fact in facts:
        if not fact.id.startswith("starter-model-"):
            continue
        if fact.value == "missing":
            return True
    return False


def _has_transcription_model_missing(facts: Sequence[SetupDiscoveryFact]) -> bool:
    """True if a transcription-capable starter model is not yet on disk."""

    for fact in facts:
        if not fact.id.startswith("starter-model-"):
            continue
        description = fact.metadata.get("description", "").lower()
        model_type = fact.metadata.get("model_type", "").lower()
        looks_like_transcription = (
            "transcription" in description
            or "whisper" in description
            or "whisper" in model_type
            or model_type == "transcription"
        )
        if looks_like_transcription and fact.value == "missing":
            return True
    return False


def _has_no_detected_email_client(facts: Sequence[SetupDiscoveryFact]) -> bool:
    """True when discovery surfaced zero usable email clients."""

    for fact in facts:
        if fact.id.startswith("email-client-"):
            return False
    return True


def _always(_facts: Sequence[SetupDiscoveryFact]) -> bool:
    return True


# --- The catalog itself ------------------------------------------------------

SETUP_AGENDA_CATALOG: List[CatalogAgendaItem] = [
    CatalogAgendaItem(
        id="setup_local_reasoning_model",
        title="Get a local reasoning model installed",
        intent=(
            "Make sure at least one local reasoning model is on disk so the user has a "
            "private offline option. Include only when discovery shows a starter model "
            "missing."
        ),
        kind="action",
        applicability=_has_starter_model_missing,
    ),
    CatalogAgendaItem(
        id="setup_local_transcription_model",
        title="Get local transcription ready",
        intent=(
            "Install a transcription model so dictation and voice notes work without a "
            "network. Include only when the transcription starter isn't installed yet."
        ),
        kind="action",
        applicability=_has_transcription_model_missing,
    ),
    CatalogAgendaItem(
        id="connect_email_account",
        title="Connect an email account",
        intent=(
            "Stand up at least one mail connection so Dill has a real surface to work "
            "against. Include only when no email client was detected at orientation."
        ),
        kind="action",
        applicability=_has_no_detected_email_client,
    ),
    CatalogAgendaItem(
        id="capture_writing_voice_samples",
        title="Capture a few writing voice samples for Dill",
        intent=(
            "Have Dill learn the user's voice from real sent emails so future drafts "
            "sound like them. Always relevant on a fresh setup; can be deferred if the "
            "user already has a populated writing profile."
        ),
        kind="action",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="confirm_activity_capture_preferences",
        title="Confirm activity-capture preferences",
        intent=(
            "Walk through what automatic context capture does and let the user decide "
            "the frequency and processing mode. Always relevant."
        ),
        kind="action",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="intro_dill",
        title="Show what Dill can do",
        intent=(
            "Hands-on Dill demo against a real email so the user sees a draft in their "
            "voice rather than a description of one."
        ),
        kind="demo",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="intro_paprika",
        title="Show what Paprika can do",
        intent=(
            "Hands-on Paprika demo on a concrete task surfaced from the user's actual "
            "setup so they feel what handing work off looks like."
        ),
        kind="demo",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="choose_invocation_preferences",
        title="Choose how to invoke Basil",
        intent=(
            "Help the user understand and choose between menu bar access, typing, "
            "global hotkeys, double-tap modifier gestures, and the voice listener "
            "with the wake phrase Hey Basil. This is not just UI literacy: when Dill, "
            "Paprika, or Transcription are useful for this user, explain exactly how "
            "to invoke each capability now and where to customize its hotkey."
        ),
        kind="action",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="literacy_basil_home_and_todos",
        title="Explain Basil Home and To-Dos",
        intent="Explain the Basil Home workspace, durable To-Do status and context, and how a selected To-Do can be delegated to a worker task without implying autonomous status changes.",
        kind="literacy",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="literacy_status_bubble_colors",
        title="Explain what the status bubble colors mean",
        intent=(
            "Cover the menu-bar status indicator: idle, thinking, listening, error. "
            "Replaces the literacy moment the old Swift onboarding handled explicitly."
        ),
        kind="literacy",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="literacy_menu_bar_item",
        title="Walk through the menu bar item",
        intent=(
            "Show where Basil lives in the menu bar, what the icon states are, and "
            "what each menu item does. Include the core app-status literacy from "
            "the old onboarding flow: menu dots, bubble colors, hotkeys/menu "
            "entry points, and speak-vs-type options."
        ),
        kind="literacy",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="literacy_agent_task_widget",
        title="Walk through the agent-task result widget",
        intent=(
            "Explain how Paprika's result widget surfaces an in-flight or finished "
            "task, including the controls for inspecting and acting on results."
        ),
        kind="literacy",
        applicability=_always,
    ),
    CatalogAgendaItem(
        id="literacy_double_tap_capture",
        title="Show the double-tap capture gesture",
        intent=(
            "Teach the global capture gesture (double-tap of the configured modifier) "
            "for invoking Basil from anywhere."
        ),
        kind="literacy",
        applicability=_always,
    ),
]


# --- Public API --------------------------------------------------------------

def default_catalog_items() -> List[CatalogAgendaItem]:
    """Return the full catalog (no applicability filtering)."""

    return list(SETUP_AGENDA_CATALOG)


def applicable_catalog_seed(
    facts: Iterable[SetupDiscoveryFact],
) -> List[Dict[str, Any]]:
    """Filter the catalog by applicability and render as seed dicts.

    The returned list is what the stream route ships to the agent in
    the request's `agenda_items` field on the first conversation-phase
    turn. The agent is free to keep, drop, reshape, or extend the
    list when it calls `propose_session_agenda`.
    """

    fact_list = list(facts)
    return [
        item.to_seed_dict()
        for item in SETUP_AGENDA_CATALOG
        if item.applicability(fact_list)
    ]
