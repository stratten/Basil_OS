"""Chooses the pattern that "Remember this choice" stores.

The agent may propose the leading words that identify what a command does (``gh gist view``). A proposal is accepted only when those words are exactly the first words of the command being approved, so a proposal can narrow what is remembered but can never add to it or name some other command. Without a valid proposal Basil falls back to its older heuristic, which is often just the command name; the card then says so instead of implying something narrower.
"""

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from .command_words import (
    effective_command,
    has_shell_syntax,
    join_words,
    pattern_words,
    split_words,
)

MAX_PROPOSAL_CHARS = 200
MAX_PROPOSAL_WORDS = 6

SOURCE_AGENT = "agent"
SOURCE_GENERALIZED = "generalized"


@dataclass(frozen=True)
class RememberPattern:
    """The pattern to store, and where it came from."""

    pattern: str
    source: str


def advice_pattern(raw: Any) -> Optional[str]:
    """The pattern the agent put in its remember advice, or None when it gave none."""
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("pattern")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def validate_proposed_pattern(command_words: List[str], proposed: Any) -> Optional[List[str]]:
    """The proposal as words when it is a leading run of the command's own words, otherwise None."""
    if not isinstance(proposed, str) or not proposed.strip() or len(proposed) > MAX_PROPOSAL_CHARS:
        return None
    if has_shell_syntax(proposed):
        return None
    words = split_words(proposed)
    if words is None or len(words) > MAX_PROPOSAL_WORDS or len(words) > len(command_words):
        return None
    if command_words[:len(words)] != words:
        return None
    return words


def select_remember_pattern(command: str, proposed: Optional[str], generalizer: Any) -> RememberPattern:
    """Pick the pattern to remember for ``command``: the agent's valid proposal, otherwise the heuristic's."""
    effective = effective_command(command)
    if effective.words is None:
        return RememberPattern(generalizer.generalize_command(command), SOURCE_GENERALIZED)
    words = validate_proposed_pattern(effective.words, proposed)
    if words is not None:
        return RememberPattern(join_words(words), SOURCE_AGENT)
    return RememberPattern(generalizer.generalize_command(join_words(effective.words)), SOURCE_GENERALIZED)


def is_broad_pattern(pattern: str, command: str) -> bool:
    """Whether remembering ``pattern`` would also approve commands unlike the one in front of the user: a single word that the command goes on beyond."""
    words = pattern_words(pattern)
    effective = effective_command(command)
    if not words or effective.words is None:
        return False
    return len(words) == 1 and len(effective.words) > 1
