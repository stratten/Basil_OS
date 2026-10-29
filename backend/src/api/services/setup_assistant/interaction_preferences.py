"""Managed "interaction preferences" block inside the profile's freeform custom instructions.

The setup agent interviews the user about how they like to work with an assistant. The answers are saved in the existing profile field
``custom_instructions``, which already reaches Paprika's agent prompt, final synthesis, and assistant sessions and which the user can see and edit
in the profile editor. The block is delimited so a later interview replaces only its own text and never overwrites freeform text the user wrote.
"""

from __future__ import annotations

from typing import Optional

BLOCK_START = "--- Interaction preferences (learned during setup) ---"
BLOCK_END = "--- End interaction preferences ---"
CUSTOM_INSTRUCTIONS_MAX_LENGTH = 4000


def merge_interaction_preferences(existing: Optional[str], preferences_text: str) -> str:
    """Return ``existing`` with its managed block replaced (or appended) so it holds ``preferences_text``.

    Raises ValueError for empty preferences or a result longer than the profile field allows.
    """
    cleaned = (preferences_text or "").strip()
    if not cleaned:
        raise ValueError("Interaction preferences must not be empty.")
    if BLOCK_START in cleaned or BLOCK_END in cleaned:
        raise ValueError("Interaction preferences must not contain the block delimiters.")

    block = f"{BLOCK_START}\n{cleaned}\n{BLOCK_END}"
    current = (existing or "").strip()
    start_index = current.find(BLOCK_START)
    end_index = current.find(BLOCK_END, start_index + len(BLOCK_START)) if start_index != -1 else -1

    if start_index != -1 and end_index != -1:
        before = current[:start_index].rstrip()
        after = current[end_index + len(BLOCK_END):].lstrip()
        parts = [part for part in (before, block, after) if part]
        merged = "\n\n".join(parts)
    elif current:
        merged = f"{current}\n\n{block}"
    else:
        merged = block

    if len(merged) > CUSTOM_INSTRUCTIONS_MAX_LENGTH:
        raise ValueError(
            f"Interaction preferences are too long: the profile allows {CUSTOM_INSTRUCTIONS_MAX_LENGTH} characters of standing instructions "
            f"and this would make {len(merged)}. Summarize the preferences more briefly."
        )
    return merged
