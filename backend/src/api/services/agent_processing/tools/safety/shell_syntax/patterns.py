"""Matching the configured dangerous patterns against the commands a string runs.

A pattern is compared with the words of each command, never with the raw text, so a filename that merely contains the pattern's letters (`mv 'MD BCBA Information.csv' x` against `format`) does not match.
"""

from __future__ import annotations

import shlex
from typing import List

from .commands import collect_commands

# Shell metacharacter patterns are not token-shaped commands, so they are matched literally anywhere in the text.
_LITERAL_PATTERNS = frozenset({':(){ :|:& };:'})


def _pattern_words(pattern: str) -> List[str]:
    try:
        return shlex.split(pattern)
    except ValueError:
        return pattern.split()


def command_matches_pattern(command: str, pattern: str) -> bool:
    """Whether any command in `command` matches the pattern, ignoring case."""
    normalized = (pattern or '').strip().lower()
    if not normalized:
        return False
    if normalized in _LITERAL_PATTERNS:
        return normalized in command.lower()

    found = collect_commands(command)
    argvs = [[part.lower() for part in argv] for argv in found.argvs]
    if found.fallback_words:
        argvs.append([word.lower() for word in found.fallback_words])

    pattern_words = _pattern_words(normalized)
    if len(pattern_words) > 1:
        # Multi-word patterns such as "sudo rm" and "rm -rf /" match consecutive words of one command.
        size = len(pattern_words)
        for argv in argvs:
            for index in range(0, len(argv) - size + 1):
                if argv[index:index + size] == pattern_words:
                    return True
        if normalized == 'dd if=':
            return any(
                argv and argv[0].split('/')[-1] == 'dd' and any(part.startswith('if=') for part in argv[1:])
                for argv in argvs
            )
        return False

    if normalized in {argv[0].split('/')[-1] for argv in argvs if argv}:
        return True
    if normalized.endswith('='):
        return any(part.startswith(normalized) for argv in argvs for part in argv)
    return False
