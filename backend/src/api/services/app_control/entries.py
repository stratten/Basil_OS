"""The settings an agent can control today: Appearance, plus entries that are deliberately off limits."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from api.core.models.preference_models.ui_and_capture import TEXT_SCALE_STEPS

from api.core.appearance.token_contract import contrast_ratio, meets_minimum_contrast

from .colors import format_hex_color, parse_hex_color
from .manifest import ControlEntry, ControlRegistry, GroupRule, Tier

APPEARANCE_GROUP = "appearance"
APPEARANCE_SETTINGS_PATH = "Settings > Appearance"

BACKGROUND_KEY = "appearance.background_color"
TEXT_KEY = "appearance.text_color"

MIN_TEXT_CONTRAST = 4.5

# Mirrors client/Sources/Support/AestheticSystem.swift's `availableFonts`. That native list is the source of truth; the Setup Assistant keeps its own copy until it is moved onto this registry.
AVAILABLE_FONTS: Tuple[str, ...] = ("Helvetica-Light", "Arial", "Avenir-Light", "SF Pro Text", "Menlo")

# The processing bubble is a status signal: purple means "Basil is working", and it must stay distinct from the ready green and the recording red. So its colors need the user's approval and are never changed along with a palette.
PROCESSING_BUBBLE_NOTE = "Change this only when the user names the processing bubble. A request to change Basil's colors, palette or theme does not include it, so leave it out of those changes. It must be sent in a call that changes nothing else, and the user is asked to approve it."

# AppearanceSettings fields that no entry controls, with the reason. The coverage test fails when a field is in neither the entries nor this table, so a new Appearance setting cannot ship unclassified.
NOT_AGENT_CONTROLLABLE: Dict[str, str] = {}


def _color_entry(key: str, label: str, description: str, field_prefix: str, *, tier: Tier = Tier.COSMETIC, change_alone: bool = False) -> ControlEntry:
    fields = (f"{field_prefix}_red", f"{field_prefix}_green", f"{field_prefix}_blue")

    def read(preferences: Any) -> List[float]:
        return [float(getattr(preferences.ui, name)) for name in fields]

    def write(preferences: Any, raw: Any) -> None:
        for name, value in zip(fields, raw):
            setattr(preferences.ui, name, float(value))

    return ControlEntry(
        key=key,
        label=label,
        description=description,
        kind="color",
        tier=tier,
        where_in_settings=APPEARANCE_SETTINGS_PATH,
        publish_group=APPEARANCE_GROUP,
        change_alone=change_alone,
        covers=fields,
        parse=parse_hex_color,
        read=read,
        write=write,
        render=format_hex_color,
    )


def _parse_choice(allowed: Tuple[str, ...]):
    def parse(value: Any) -> str:
        text = value.strip().lower() if isinstance(value, str) else ""
        if text not in allowed:
            raise ValueError(f"Choose one of: {', '.join(allowed)}.")
        return text

    return parse


def _parse_font(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    for font in AVAILABLE_FONTS:
        if font.lower() == text.lower():
            return font
    raise ValueError(f"Choose one of these fonts: {', '.join(AVAILABLE_FONTS)}.")


def _parse_text_scale(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    for step in TEXT_SCALE_STEPS:
        if abs(step - number) < 1e-9:
            return step
    steps = ", ".join(str(step) for step in TEXT_SCALE_STEPS)
    raise ValueError(f"Text size must be one of: {steps}. 1.0 is the default.")


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "on", "yes"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "off", "no"):
        return False
    raise ValueError("Use true or false.")


def _ui_field_entry(
    key: str,
    label: str,
    description: str,
    tier: Tier,
    field_name: str,
    kind: str,
    parse: Any,
    allowed: Tuple[Any, ...] = (),
) -> ControlEntry:
    def read(preferences: Any) -> Any:
        return getattr(preferences.ui, field_name)

    def write(preferences: Any, raw: Any) -> None:
        setattr(preferences.ui, field_name, raw)

    return ControlEntry(
        key=key,
        label=label,
        description=description,
        kind=kind,  # type: ignore[arg-type]
        tier=tier,
        where_in_settings=APPEARANCE_SETTINGS_PATH,
        publish_group=APPEARANCE_GROUP,
        covers=(field_name,),
        allowed=allowed,
        parse=parse,
        read=read,
        write=write,
    )


def _readability_check(after: Mapping[str, Any]) -> Optional[str]:
    background = after.get(BACKGROUND_KEY)
    text = after.get(TEXT_KEY)
    if background is None or text is None:
        return None
    if meets_minimum_contrast(text, background, "normal"):
        return None
    ratio = contrast_ratio(text, background)
    return (
        f"Text color {format_hex_color(text)} on background color {format_hex_color(background)} would have a contrast ratio of {ratio:.1f}:1, "
        f"below the {MIN_TEXT_CONTRAST:.1f}:1 needed to stay readable. Choose a lighter or darker color for one of them, and send both in the same change if you are changing the whole palette."
    )


def build_appearance_entries() -> Tuple[ControlEntry, ...]:
    return (
        _color_entry(BACKGROUND_KEY, "Background color", "The base color behind every Basil window and panel.", "background_color"),
        _color_entry("appearance.primary_color", "Primary color", "The main accent color for buttons, highlights, and active controls.", "primary_color"),
        _color_entry("appearance.secondary_color", "Secondary color", "The lighter accent color used beside the primary color.", "secondary_color"),
        _color_entry(TEXT_KEY, "Text color", "The color of text drawn on the background.", "text_color"),
        _color_entry(
            "appearance.processing_color",
            "Processing bubble color",
            PROCESSING_BUBBLE_NOTE + " The base color of the bubble that shows an agent is working.",
            "processing_color",
            tier=Tier.BEHAVIORAL,
            change_alone=True,
        ),
        _color_entry(
            "appearance.processing_accent_color",
            "Processing bubble accent color",
            PROCESSING_BUBBLE_NOTE + " The lighter highlight color of the processing bubble.",
            "processing_accent_color",
            tier=Tier.BEHAVIORAL,
            change_alone=True,
        ),
        _ui_field_entry(
            "appearance.text_scale",
            "Text size",
            "How large text is across Basil, as a multiplier. 1.0 is the default; 1.25 is noticeably larger.",
            Tier.COSMETIC,
            "text_scale",
            "enum",
            _parse_text_scale,
            allowed=TEXT_SCALE_STEPS,
        ),
        _ui_field_entry(
            "appearance.preferred_font",
            "Font",
            "The typeface used across Basil. Choose one of the fonts listed in allowed.",
            Tier.COSMETIC,
            "preferred_font",
            "enum",
            _parse_font,
            allowed=AVAILABLE_FONTS,
        ),
        _ui_field_entry(
            "appearance.surface_finish",
            "Surface finish",
            "How panels are drawn: flat (solid colors), metal (brushed-metal sheen), or metal_backdrop (metal with a textured backdrop).",
            Tier.COSMETIC,
            "surface_finish",
            "enum",
            _parse_choice(("flat", "metal", "metal_backdrop")),
            allowed=("flat", "metal", "metal_backdrop"),
        ),
        _ui_field_entry(
            "appearance.blueprint_reveal",
            "Blueprint reveal animation",
            "Whether supporting panels play the green blueprint drawing animation as they appear.",
            Tier.COSMETIC,
            "blueprint_reveal",
            "bool",
            _parse_bool,
        ),
        _ui_field_entry(
            "appearance.agent_task_chain_expansion",
            "Open turns in a task chain",
            "Whether opening an earlier turn of a multi-turn task closes the one that was open (single) or leaves several open at once (multiple).",
            Tier.BEHAVIORAL,
            "agent_task_chain_expansion",
            "enum",
            _parse_choice(("single", "multiple")),
            allowed=("single", "multiple"),
        ),
    )


def build_human_only_entries() -> Tuple[ControlEntry, ...]:
    return (
        ControlEntry(
            key="security.command_approval",
            label="Command and script approval",
            description="Which shell commands and AppleScripts run without asking you. An agent cannot change this, because it would be widening its own permissions.",
            kind="enum",
            tier=Tier.HUMAN_ONLY,
            where_in_settings="Settings",
        ),
        ControlEntry(
            key="connections.credentials",
            label="Connected accounts, API keys, and sign-ins",
            description="The accounts and keys Basil uses to reach other services. An agent cannot read or change them.",
            kind="enum",
            tier=Tier.HUMAN_ONLY,
            where_in_settings="Settings",
        ),
    )


def build_default_registry() -> ControlRegistry:
    from .schema_entries import build_schema_entries

    registry = ControlRegistry()
    appearance_entries = build_appearance_entries()
    curated_paths = {f"ui.{name}" for entry in appearance_entries for name in entry.covers}
    for entry in appearance_entries + build_human_only_entries():
        registry.register(entry)
    for entry in build_schema_entries(covered_by_curated=curated_paths):
        registry.register(entry)
    registry.add_rule(GroupRule(keys=frozenset({BACKGROUND_KEY, TEXT_KEY}), check=_readability_check))
    return registry


_DEFAULT_REGISTRY: Optional[ControlRegistry] = None


def get_default_registry() -> ControlRegistry:
    """The registry the agent tool uses, built once per process."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY
