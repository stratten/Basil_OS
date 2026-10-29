"""Prompt context trimming helpers for agent execution."""

from __future__ import annotations

import logging
import re


def parse_token_limit_error(error_str: str) -> tuple[int, int] | None:
    """
    Parse token limit error to extract actual and maximum token counts.

    Args:
        error_str: Error message like "prompt is too long: 203619 tokens > 200000 maximum"

    Returns:
        Tuple of (actual_tokens, max_tokens) or None if not a token limit error
    """
    match = re.search(r"prompt is too long: (\d+) tokens > (\d+) maximum", error_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def trim_oldest_context(user_input: str, chars_to_remove: int, trim_logger: logging.Logger) -> str | None:
    """
    Remove characters from context while preserving the user agent task.

    Identifies context sections (chain context, screen context) and trims from the oldest.
    Never touches the actual user agent task at the end.
    """
    if chars_to_remove <= 0:
        return user_input

    # Prefer trimming lower-priority assembled context sections before
    # touching current request or explicit high-value references.
    # FOLLOW UP CONTEXT is trimmed last among these -- for a follow-up turn
    # it is the highest-value section (it carries the prior turn's resolved
    # file/reference identity), so screen/retry/reference-material context
    # should be shed first when a reactive token-limit trim is needed.
    trimmable_sections = [
        "SCREEN CONTEXT",
        "RETRY CONTEXT",
        "REFERENCE MATERIALS",
        "FOLLOW UP CONTEXT",
        # Legacy marker retained only for prompts formatted before the shared
        # context assembler introduced agent-task naming.
        "PREVIOUS TASK IN THIS CHAIN",
    ]

    for section_name in trimmable_sections:
        # ContextSection.render() (agent_context_assembler.py) builds its marker
        # via `name.upper().replace(" ", "_")`, e.g. "FOLLOW UP CONTEXT" renders
        # as "===== FOLLOW_UP_CONTEXT =====". Search using that same
        # transformation -- searching for the raw, space-separated section_name
        # would never match the underscored marker actually in the text, so
        # every section here would silently fall through to the crude
        # "trim from the beginning" fallback below regardless of this list.
        marker_name = section_name.upper().replace(" ", "_")
        start_marker = f"===== {marker_name} ====="
        end_marker = f"===== END {marker_name} ====="
        section_start = user_input.find(start_marker)
        section_end = user_input.find(end_marker)

        if section_start < 0 or section_end <= section_start:
            continue

        section_end += len(end_marker)
        section = user_input[section_start:section_end]
        section_length = len(section)

        if section_length > chars_to_remove:
            keep_chars = section_length - chars_to_remove
            replacement = (
                f"{start_marker}\n"
                f"[...{section_name.lower()} truncated by {chars_to_remove:,} chars to fit token limit...]\n"
                + section[-keep_chars:]
            )
            trimmed = user_input[:section_start] + replacement + user_input[section_end:]
            trim_logger.info("✂️ Trimmed %s: removed %s chars", section_name, f"{chars_to_remove:,}")
            return trimmed

        replacement = f"[{section_name.title()} removed to fit token limit]\n\n"
        trimmed = user_input[:section_start] + replacement + user_input[section_end:]
        remaining_to_remove = chars_to_remove - section_length
        trim_logger.info(
            "✂️ Removed %s (%s chars), still need to remove %s chars",
            section_name,
            f"{section_length:,}",
            f"{remaining_to_remove:,}",
        )
        if remaining_to_remove > 0:
            return trim_oldest_context(trimmed, remaining_to_remove, trim_logger)
        return trimmed

    # No structured context found - try to trim from the beginning of the input
    # but preserve "Current request:" or similar markers
    current_request_marker = user_input.find("Current request:")
    if current_request_marker < 0:
        current_request_marker = user_input.find("current request:")

    if current_request_marker > chars_to_remove:
        # We can trim from the beginning
        trimmed = f"[...context truncated by {chars_to_remove:,} chars to fit token limit...]\n" + user_input[chars_to_remove:]
        trim_logger.info(f"✂️ Trimmed beginning of context: removed {chars_to_remove:,} chars")
        return trimmed
    if current_request_marker > 0:
        # Trim everything before the current request marker
        trimmed = "[Context removed to fit token limit]\n\n" + user_input[current_request_marker:]
        trim_logger.info(f"✂️ Removed all context before user request ({current_request_marker:,} chars)")
        return trimmed

    # Can't find safe trim points - trim from the beginning anyway, but be conservative
    if len(user_input) > chars_to_remove + 1000:
        trimmed = f"[...truncated {chars_to_remove:,} chars...]\n" + user_input[chars_to_remove:]
        trim_logger.info(f"✂️ Force-trimmed {chars_to_remove:,} chars from beginning")
        return trimmed

    trim_logger.warning(f"⚠️ Cannot safely trim {chars_to_remove:,} chars from input of length {len(user_input):,}")
    return None



