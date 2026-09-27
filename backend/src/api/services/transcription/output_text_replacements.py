"""Apply configured literal substitutions at the transcription output boundary."""

import re
from typing import Protocol, Sequence


class TranscriptionTextReplacementRule(Protocol):
    """Structural contract shared by persisted replacement rules and tests."""

    source: str
    replacement: str


def apply_text_replacements(
    text: str, rules: Sequence[TranscriptionTextReplacementRule]
) -> str:
    """Apply rules once without rewriting the raw transcription text."""
    if not text or not rules:
        return text

    ordered_rules = sorted(
        enumerate(rules),
        key=lambda item: (-len(item[1].source), item[0]),
    )
    pattern_parts: list[str] = []
    replacements_by_group: dict[str, str] = {}

    for position, (_, rule) in enumerate(ordered_rules):
        words = rule.source.split()
        if not words:
            continue
        group_name = f"rule_{position}"
        phrase_pattern = r"\s+".join(re.escape(word) for word in words)
        pattern_parts.append(f"(?P<{group_name}>{phrase_pattern})")
        replacements_by_group[group_name] = rule.replacement

    if not pattern_parts:
        return text

    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(pattern_parts) + r")(?!\w)",
        re.IGNORECASE,
    )

    def replacement(match: re.Match[str]) -> str:
        return replacements_by_group[match.lastgroup]

    return pattern.sub(replacement, text)
