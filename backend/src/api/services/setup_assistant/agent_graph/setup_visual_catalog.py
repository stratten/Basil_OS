"""Curated catalog of setup-conversation visuals the agent can show.

These are the static images the setup agent can surface inline in
the conversation via the `show_setup_visual` tool. Each entry is a
declarative pairing of:

- a stable `id` slug (e.g. ``intro_dill_email_response``) the agent
  references in tool calls,
- a `web_path` under `/images/setup/...` that the SetupAssistant
  WKWebView can resolve (the source PNG is staged there by
  scripts/build-setup-assistant-assets.sh before Vite builds),
- a `caption` shown beneath the image in the inline card,
- an `alt` string for accessibility,
- a `kind` (`screenshot` | `icon` | `composite`) so the frontend
  can size and frame the asset appropriately, and
- an optional `related_agenda_item_id` linking the visual to the
  catalog agenda item it most naturally accompanies.

Renaming a slug or moving a file requires updating BOTH this file
AND the matching staging entry in build-setup-assistant-assets.sh;
the build script's existence check will surface the mismatch loudly.

Gaps explicitly NOT covered today (no source asset exists yet):
- Paprika running a real task (intro_paprika has only the icon)
- Agent-task widget states (literacy_agent_task_widget)
- Sent-email picker UI (capture_writing_voice_samples)
- Model download UI (setup_local_*_model)
- The double-tap gesture itself (literacy_double_tap_capture uses
  a voice-command result screenshot as the closest existing analog)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


SetupVisualKind = Literal["screenshot", "icon", "icon_pair", "bubble_sequence", "composite"]


@dataclass(frozen=True)
class SetupVisual:
    id: str
    web_path: str
    caption: str
    alt: str
    kind: SetupVisualKind
    related_agenda_item_id: Optional[str] = None
    # Optional second image for side-by-side cards (e.g. screenshot
    # comparisons or compact paired icons). When present, the frontend
    # renders both images under the same caption according to `kind`.
    secondary_web_path: Optional[str] = None
    secondary_alt: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_payload_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "web_path": self.web_path,
            "caption": self.caption,
            "alt": self.alt,
            "kind": self.kind,
            "related_agenda_item_id": self.related_agenda_item_id,
            "secondary_web_path": self.secondary_web_path,
            "secondary_alt": self.secondary_alt,
            "tags": list(self.tags),
        }


# --- The catalog itself ------------------------------------------------------

SETUP_VISUAL_CATALOG: List[SetupVisual] = [
    # --- Menu bar / status visuals -----------------------------------
    SetupVisual(
        id="menu_bar_idle_vs_recording",
        web_path="/images/setup/setup_menu_bar_idle.png",
        secondary_web_path="/images/setup/setup_menu_bar_recording.png",
        caption=(
            "Basil's menu bar icon. Left: at rest. Right: actively "
            "listening or capturing."
        ),
        alt="Two Basil menu bar icons side by side",
        secondary_alt="Basil menu bar icon while recording",
        kind="icon_pair",
        related_agenda_item_id="literacy_menu_bar_item",
        tags=["menu_bar", "literacy"],
    ),
    SetupVisual(
        id="invocation_menu_bar_entry_points",
        web_path="/images/setup/setup_menu_bar_idle.png",
        secondary_web_path="/images/setup/setup_menu_bar_recording.png",
        caption=(
            "The menu bar is one of Basil's everyday entry points. The same "
            "icon also shows whether Basil is idle or actively listening."
        ),
        alt="Two Basil menu bar icons side by side",
        secondary_alt="Basil menu bar icon while recording",
        kind="icon_pair",
        related_agenda_item_id="choose_invocation_preferences",
        tags=["menu_bar", "invocation"],
    ),
    SetupVisual(
        id="status_bar_idle",
        web_path="/images/setup/status_bar_idle.png",
        caption="Status indicator at rest.",
        alt="Basil status bar icon in its idle state",
        kind="icon",
        related_agenda_item_id="literacy_status_bubble_colors",
        tags=["status_bar", "literacy"],
    ),
    SetupVisual(
        id="status_bar_recording",
        web_path="/images/setup/status_bar_recording.png",
        caption="Status indicator while Basil is recording.",
        alt="Basil status bar icon while recording",
        kind="icon",
        related_agenda_item_id="literacy_status_bubble_colors",
        tags=["status_bar", "literacy"],
    ),
    SetupVisual(
        id="bubble_ready_listening_working",
        # Rendered by the setup web component; no raster image is loaded.
        web_path="rendered://setup/bubble_ready_listening_working",
        caption=(
            "The main Basil bubble states. Green: ready. Red: listening "
            "or recording. Purple: working on your request."
        ),
        alt="Three Basil bubble states labeled ready, listening, and working",
        kind="bubble_sequence",
        related_agenda_item_id="literacy_menu_bar_item",
        tags=["bubble", "status", "literacy"],
    ),
    # --- Capability screenshots --------------------------------------
    SetupVisual(
        id="intro_dill_email_response",
        web_path="/images/setup/intro_dill_email_response.png",
        caption=(
            "An example of Dill drafting a reply against a real email "
            "in someone's own voice."
        ),
        alt="Screenshot of Dill drafting an email reply",
        kind="screenshot",
        related_agenda_item_id="intro_dill",
        tags=["dill", "demo"],
    ),
    SetupVisual(
        id="activity_capture_summary",
        web_path="/images/setup/activity_capture_summary.png",
        caption=(
            "What an automatic activity summary looks like once "
            "context capture is on."
        ),
        alt="Screenshot of an activity capture summary view",
        kind="screenshot",
        related_agenda_item_id="confirm_activity_capture_preferences",
        tags=["activity_capture", "literacy"],
    ),
    SetupVisual(
        id="voice_command_folder_analysis",
        web_path="/images/setup/voice_command_folder_analysis.png",
        caption=(
            "Voice command in action: triggering Basil from anywhere "
            "to analyze a folder."
        ),
        alt="Screenshot of a voice-triggered folder analysis result",
        kind="screenshot",
        related_agenda_item_id="literacy_double_tap_capture",
        tags=["voice_command", "literacy"],
    ),
    SetupVisual(
        id="voice_command_file_find_and_merge",
        web_path="/images/setup/voice_command_file_find_and_merge.png",
        caption=(
            "Another voice-triggered example: asking Basil to find "
            "and merge related files."
        ),
        alt="Screenshot of a voice-triggered file find and merge result",
        kind="screenshot",
        related_agenda_item_id="literacy_double_tap_capture",
        tags=["voice_command", "literacy"],
    ),
    # --- Agent identity icons ----------------------------------------
    SetupVisual(
        id="dill_icon",
        web_path="/images/setup/dill_icon.png",
        caption="Dill — your writing and reply partner.",
        alt="Dill's app icon",
        kind="icon",
        related_agenda_item_id="intro_dill",
        tags=["dill", "icon"],
    ),
    SetupVisual(
        id="paprika_icon",
        web_path="/images/setup/paprika_icon.png",
        caption="Paprika — your task-running helper.",
        alt="Paprika's app icon",
        kind="icon",
        related_agenda_item_id="intro_paprika",
        tags=["paprika", "icon"],
    ),
]


# --- Public API --------------------------------------------------------------

_VISUALS_BY_ID: Dict[str, SetupVisual] = {visual.id: visual for visual in SETUP_VISUAL_CATALOG}


def get_setup_visual(visual_id: str) -> Optional[SetupVisual]:
    """Resolve a visual by id. Returns None when no such visual exists."""

    return _VISUALS_BY_ID.get(visual_id)


def available_visual_ids() -> List[str]:
    """All catalog ids, in declaration order. Used by the tool layer to
    validate the agent's `visual_id` argument before emitting an SSE
    event the frontend would silently drop."""

    return [visual.id for visual in SETUP_VISUAL_CATALOG]


def available_visuals_for_prompt() -> str:
    """Render the catalog as a compact bullet list for the system prompt.

    Each line carries the slug, the kind, the matching agenda item id
    (when present), and the caption. The agent reads this once at
    turn build time and uses it to decide whether a paired visual
    exists for the current agenda item rather than improvising a
    path that would fail validation at the tool boundary.
    """

    lines: List[str] = []
    for visual in SETUP_VISUAL_CATALOG:
        agenda_suffix = (
            f" -- pairs with agenda item `{visual.related_agenda_item_id}`"
            if visual.related_agenda_item_id
            else ""
        )
        lines.append(
            f"- `{visual.id}` ({visual.kind}){agenda_suffix}: {visual.caption}"
        )
    return "\n".join(lines)


def visuals_for_agenda_item(agenda_item_id: str) -> List[SetupVisual]:
    """Return all catalog visuals associated with one agenda item id.

    Used by agenda_catalog.py to surface `default_visual_id` on seed
    items (when exactly one match exists) so the agent sees a paired
    visual slug next to the item title in its input bundle.
    """

    return [
        visual
        for visual in SETUP_VISUAL_CATALOG
        if visual.related_agenda_item_id == agenda_item_id
    ]


def primary_visual_id_for_agenda_item(agenda_item_id: str) -> Optional[str]:
    """Return one canonical visual id for an agenda item, or None.

    Heuristic: prefer composites (which are purpose-built for the
    item), then screenshots, then icons. When multiple visuals of
    the same kind tie, return the first in catalog order.
    """

    matches = visuals_for_agenda_item(agenda_item_id)
    if not matches:
        return None
    kind_priority = {"composite": 0, "icon_pair": 1, "screenshot": 2, "icon": 3}
    matches.sort(key=lambda v: kind_priority.get(v.kind, 99))
    return matches[0].id
