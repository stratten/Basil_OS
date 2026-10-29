"""Selectable statements about how the user likes to work with an assistant, chosen on the last setup preferences step.

The catalog is the single source of truth: the setup UI renders the labels, and the chosen ids become the short standing instructions saved into the profile's interaction preferences block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class InteractionStyleOption:
    id: str
    label: str
    instruction: str


@dataclass(frozen=True)
class InteractionStyleGroup:
    id: str
    title: str
    multiple: bool
    options: Tuple[InteractionStyleOption, ...]


INTERACTION_STYLE_GROUPS: Tuple[InteractionStyleGroup, ...] = (
    InteractionStyleGroup(
        id="length",
        title="How much do you want me to say?",
        multiple=False,
        options=(
            InteractionStyleOption(
                id="short",
                label="Short answers, lead with the result",
                instruction="Lead with the answer in one or two sentences and keep replies short.",
            ),
            InteractionStyleOption(
                id="balanced",
                label="Brief by default, more detail when I ask",
                instruction="Keep replies brief by default and give more detail only when asked.",
            ),
            InteractionStyleOption(
                id="thorough",
                label="Walk me through the reasoning",
                instruction="Explain the reasoning and show the steps behind answers.",
            ),
        ),
    ),
    InteractionStyleGroup(
        id="format",
        title="How should I lay it out?",
        multiple=True,
        options=(
            InteractionStyleOption(
                id="bullets",
                label="Bullet points for lists",
                instruction="Use bullet lists for anything with more than three items.",
            ),
            InteractionStyleOption(
                id="tables",
                label="Tables for comparisons",
                instruction="Use a table when comparing options side by side.",
            ),
            InteractionStyleOption(
                id="bold",
                label="Bold the key terms",
                instruction="Bold the key terms so replies can be skimmed.",
            ),
        ),
    ),
    InteractionStyleGroup(
        id="checkins",
        title="When should I check with you?",
        multiple=False,
        options=(
            InteractionStyleOption(
                id="careful",
                label="Ask before sending or changing anything",
                instruction="Ask before sending, editing, or deleting anything.",
            ),
            InteractionStyleOption(
                id="routine",
                label="Skip routine confirmations, ask on anything risky",
                instruction="Do not ask for confirmation on routine steps; ask only before anything risky or hard to undo.",
            ),
            InteractionStyleOption(
                id="minimal",
                label="Only ask when something is unclear",
                instruction="Only ask a question when something is genuinely unclear.",
            ),
        ),
    ),
    InteractionStyleGroup(
        id="tone",
        title="What tone suits you?",
        multiple=False,
        options=(
            InteractionStyleOption(
                id="direct",
                label="Direct and efficient",
                instruction="Keep the tone direct and efficient, without small talk.",
            ),
            InteractionStyleOption(
                id="warm",
                label="Warm and conversational",
                instruction="Keep the tone warm and conversational.",
            ),
        ),
    ),
)

MAX_SELECTED_OPTIONS = sum(len(group.options) for group in INTERACTION_STYLE_GROUPS)


def resolve_interaction_style(selections: Mapping[str, Sequence[str]]) -> List[str]:
    """Return the instruction for every selected option, in catalog order.

    Raises ValueError for an unknown group or option, a repeated option, or more than one option in a single-choice group.
    """
    groups_by_id: Dict[str, InteractionStyleGroup] = {group.id: group for group in INTERACTION_STYLE_GROUPS}
    unknown_group = next((group_id for group_id in selections if group_id not in groups_by_id), None)
    if unknown_group is not None:
        raise ValueError(f"Unknown interaction style group '{unknown_group}'.")

    instructions: List[str] = []
    for group in INTERACTION_STYLE_GROUPS:
        chosen_ids = list(selections.get(group.id, ()))
        if len(set(chosen_ids)) != len(chosen_ids):
            raise ValueError(f"Interaction style group '{group.id}' repeats an option.")
        if len(chosen_ids) > 1 and not group.multiple:
            raise ValueError(f"Interaction style group '{group.id}' allows only one option.")
        options_by_id = {option.id: option for option in group.options}
        unknown_option = next((option_id for option_id in chosen_ids if option_id not in options_by_id), None)
        if unknown_option is not None:
            raise ValueError(f"Unknown option '{unknown_option}' in interaction style group '{group.id}'.")
        instructions.extend(
            option.instruction for option in group.options if option.id in chosen_ids
        )
    return instructions
