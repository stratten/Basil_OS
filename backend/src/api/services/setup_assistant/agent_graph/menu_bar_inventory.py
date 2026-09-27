"""Canonical inventory of the Basil macOS menu bar dropdown items.

The setup agent walks new users through "what's in the menu bar"
during the literacy_menu_bar_item agenda item. Before this module
existed, the inventory was a hand-typed list embedded directly in
the setup agent system prompt, and the agent had no guardrail
against the prompt drifting away from the actual Swift menu source
of truth at
``client/Sources/Services/StatusBar/StatusBarMenuBuilder.swift``.

This module centralizes the structured inventory; the system prompt
renders it dynamically via ``menu_bar_inventory_for_prompt``. A
companion script at ``backend/scripts/check_menu_bar_inventory.py`` is
run from ``scripts/build-setup-assistant-assets.sh`` on every dev
and release build to compare ``canonical_menu_titles`` against the
titles parsed out of the Swift source. Drift fails the build loudly
so a developer who touches the Swift menu gets a clear instruction
to update this catalog before they merge.

This is the Option A + Option B halfway point: not a single source
of truth across the Swift/Python boundary (that would require a
shared manifest and a Swift refactor — see Option C in the planning
discussion), but a single source of truth on the Python side plus a
build-time consistency check against the Swift source.

Updating this catalog: edit ``MENU_BAR_INVENTORY`` in place, keep
``canonical_menu_titles`` in display order, and re-run the drift
check (``python3 backend/scripts/check_menu_bar_inventory.py``) to
confirm parity with the Swift source before committing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple


MenuBarItemVisibility = Literal["always", "conditional"]


@dataclass(frozen=True)
class MenuBarItem:
    """One row in the Basil menu bar dropdown.

    ``title`` is the user-visible primary title with any leading
    whitespace stripped — the Swift source uses a literal indent
    prefix (e.g. ``"   Transcription History"``) for visual nesting
    under another item; that rendering concern is captured separately
    on ``indent`` rather than embedded into the canonical title we
    diff against.

    ``description`` is a one-line, first-person explanation the agent
    can speak directly. Keep it short — the agent will assemble its
    own walkthrough prose around these snippets, and over-stuffed
    descriptions push the prompt over budget without adding clarity.

    ``default_hotkey`` is the keyboard shortcut shown as a tab-aligned
    suffix on the menu item when the user has not customized their
    bindings. Stored as a display string with the actual key symbols
    (e.g. ``"F8"``, ``"\u2318\u2318"`` for double-press command,
    ``"\u2325\u2423"`` for option+space) because that is exactly what
    appears in the menu. ``None`` for items with no shortcut.

    ``toggle_labels`` captures the runtime title flip for items whose
    primary title used to change based on current state. The menu now
    keeps stable noun labels for background toggles and uses the native
    checkmark to indicate active/enabled state. This tuple remains as
    structured prompt context for setup guidance, not as the displayed
    runtime title.

    ``visibility`` and ``visibility_note`` capture conditional items
    that may not appear in the menu in every session — today only
    the Activity Capture toggle is conditional, hidden unless the
    user has enabled activity capture in Settings.

    ``indent`` is ``True`` for items rendered with a leading
    whitespace prefix in the Swift source so the menu visually nests
    them under the prior item (today: Transcription History under
    Transcription).
    """

    title: str
    description: str
    default_hotkey: Optional[str] = None
    toggle_labels: Optional[Tuple[str, str]] = None
    visibility: MenuBarItemVisibility = "always"
    visibility_note: Optional[str] = None
    indent: bool = False


# --- The canonical inventory ------------------------------------------------
#
# Display order must match StatusBarMenuBuilder.buildMenu() — the drift
# check compares the ordered title list, not just the set. When the Swift
# source reorders items, this list must be updated in lockstep.
MENU_BAR_INVENTORY: List[MenuBarItem] = [
    MenuBarItem(
        title="Settings",
        description=(
            "Opens the Basil Settings window where the user tunes profile, "
            "hotkeys, models, connections, activity-capture frequency, "
            "transcription preferences, and memory/skill capture."
        ),
    ),
    MenuBarItem(
        title="Basil Home",
        description=(
            "Opens Basil Home, the unified workspace for conversations, To-Dos, and linked agent-task progress."
        ),
    ),
    MenuBarItem(
        title="Hotkeys",
        description=(
            "Toggle for whether Basil responds to global hotkeys at all. "
            "A checkmark indicates the hotkeys are currently enabled."
        ),
        toggle_labels=("Hotkeys", "Hotkeys"),
    ),
    MenuBarItem(
        title='Voice Activation ("Hey Basil")',
        description=(
            'Toggle for the "Hey Basil" wake-word activation path so the '
            "user can invoke Basil by voice. A checkmark indicates voice "
            "activation is enabled."
        ),
        toggle_labels=('Voice Activation ("Hey Basil")', 'Voice Activation ("Hey Basil")'),
    ),
    MenuBarItem(
        title="Activity Capture",
        description=(
            "Toggle for the rolling context-capture sweeps. A checkmark "
            "indicates a capture is currently running."
        ),
        toggle_labels=("Activity Capture", "Activity Capture"),
        visibility="conditional",
        visibility_note=(
            "Hidden by default. Only appears in the menu once the user "
            "has enabled activity capture in Settings."
        ),
    ),
    MenuBarItem(
        title="Meeting Detection",
        description=(
            "Manually starts or stops the mechanical meeting-detection "
            "monitor, which watches for meeting-app audio and offers to "
            "start transcription. A checkmark indicates the monitor is "
            "currently running."
        ),
        toggle_labels=("Meeting Detection", "Meeting Detection"),
        visibility="conditional",
        visibility_note=(
            "Hidden by default. Only appears in the menu once the user "
            "has enabled Meeting Detection in Settings."
        ),
    ),
    MenuBarItem(
        title="Conversation",
        description=(
            "Opens the main Basil conversation window — the same surface "
            "this setup conversation lives in."
        ),
        default_hotkey="F8",
    ),
    MenuBarItem(
        title="Transcription",
        description=(
            "Opens the push-to-talk transcription widget; hold to record, "
            "release to transcribe."
        ),
        # Double-press of Command (U+2318 COMMAND KEY twice).
        default_hotkey="\u2318\u2318",
    ),
    MenuBarItem(
        title="Transcription History",
        description=(
            "Opens a window listing prior transcriptions so the user can "
            "copy or revisit them."
        ),
        indent=True,
    ),
    MenuBarItem(
        title="Transcribe Audio File",
        description=(
            "Opens a file picker for transcribing an existing audio file "
            "on disk."
        ),
        indent=True,
    ),
    MenuBarItem(
        title="Open Dill",
        description=(
            "Opens Dill — my writing and reply partner — as a free-form "
            "assistant session."
        ),
        # Double-press of Option (U+2325 OPTION KEY twice).
        default_hotkey="\u2325\u2325",
    ),
    MenuBarItem(
        title="Open Paprika",
        description=(
            "Opens Paprika — my task-running helper — ready to take a "
            "task prompt."
        ),
        # Option + Space (U+2325 OPTION KEY, U+2423 OPEN BOX).
        default_hotkey="\u2325\u2423",
    ),
    MenuBarItem(
        title="Proactive Suggestions",
        description=(
            "Opens the Proactive Suggestions panel, where Basil can check "
            "the visible window and suggest timely Dill or Paprika help. "
            "A checkmark indicates proactive suggestions are currently "
            "running."
        ),
        toggle_labels=("Proactive Suggestions", "Proactive Suggestions"),
    ),
    MenuBarItem(
        title="Meeting / Call Transcription",
        description=(
            "Opens the meeting and call transcription panel for capturing "
            "microphone and system audio."
        ),
    ),
    MenuBarItem(
        title="Quit",
        description="Quits the Basil app.",
    ),
]


# --- Swift interpolation substitutions --------------------------------------
#
# A handful of menu titles in the Swift source are constructed via string
# interpolation against ``BasilTeamIdentity`` rather than literal strings —
# e.g. ``NSMenuItem(title: "Open \(BasilTeamIdentity.assistantSession.displayName)", ...)``.
# The drift check resolves those interpolations against this table before
# comparing against ``canonical_menu_titles``.
#
# Keys are the exact Swift expression as it appears inside the ``\(...)``,
# without surrounding whitespace. Values are the resolved display name as
# it actually renders to the user. When the Dill/Paprika display names
# change in BasilTeamIdentity.swift, update both sides here AND in the
# matching MENU_BAR_INVENTORY entry above — the drift check will fail
# loudly if only one half is updated.
SWIFT_DISPLAY_NAME_SUBSTITUTIONS: Dict[str, str] = {
    "BasilTeamIdentity.assistantSession.displayName": "Dill",
    "BasilTeamIdentity.agentTask.displayName": "Paprika",
}


# --- Public API -------------------------------------------------------------


def canonical_menu_titles() -> List[str]:
    """Ordered title list the drift check compares against.

    Order matches Swift ``StatusBarMenuBuilder.buildMenu()`` declaration
    order; reordering on either side without matching the other is
    treated as drift.
    """

    return [item.title for item in MENU_BAR_INVENTORY]


def menu_bar_inventory_for_prompt() -> str:
    """Render the inventory as the bulleted block embedded in the system prompt.

    Format intentionally matches the hand-typed paragraph that this
    catalog replaced in ``setup_agent_system_prompt.py``: each item is
    a top-level ``-`` bullet with the title in ``**bold**``, an
    optional default-hotkey parenthetical, an em-dash, and the
    description. Toggle pairs and conditional visibility appear inline
    after the description so the agent has all the grounding for a
    given item in one bullet.

    Pure-text output (no leading or trailing blank lines) so the
    caller can wrap it with surrounding prose.
    """

    lines: List[str] = []
    for item in MENU_BAR_INVENTORY:
        title_segment = f"**{item.title}**"
        if item.toggle_labels and item.toggle_labels[0] != item.toggle_labels[1]:
            off_label, on_label = item.toggle_labels
            title_segment = f"**{off_label} / {on_label}**"
        if item.default_hotkey:
            title_segment = f"{title_segment} ({item.default_hotkey})"

        description = item.description
        if item.visibility == "conditional" and item.visibility_note:
            description = f"{description} {item.visibility_note}"
        if item.indent:
            description = (
                f"{description} Rendered visually nested under the prior item."
            )

        lines.append(f"  - {title_segment} \u2014 {description}")
    return "\n".join(lines)
