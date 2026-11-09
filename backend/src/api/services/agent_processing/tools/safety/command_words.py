"""Word-level reading of a shell command, shared by remembering and matching.

A remembered command is compared word by word against the command the agent actually runs, never against a shortened copy of it. A shell wrapper (``bash -lc '...'``) is looked through only when its inner command is plain words, because anything that chains, pipes, redirects, or substitutes could run more than the user approved.
"""

import os
import re
import shlex
from dataclasses import dataclass
from typing import List, Optional

SHELL_WRAPPERS = frozenset({"bash", "sh", "zsh", "fish", "dash", "ksh"})

_VERSION_SUFFIX = re.compile(r"[\d.]+$")

# Characters and sequences that let one shell string run more than one thing: chaining, pipes, background jobs, redirection, command substitution, and line breaks. Deliberately blunt: a quoted occurrence is treated the same, so the user is asked again rather than guessed at.
_SHELL_SYNTAX = re.compile(r"[;&|<>`\n\r]|\$\(")


def normalized_command_name(token: str) -> str:
    """Return the lowercase executable name without its directory or trailing version digits (python3.11 becomes python)."""
    base = os.path.basename(token.strip()).lower()
    stripped = _VERSION_SUFFIX.sub("", base)
    return stripped or base


def is_shell_wrapper(token: str) -> bool:
    return normalized_command_name(token) in SHELL_WRAPPERS


def split_words(command: str) -> Optional[List[str]]:
    """Split a command into words the way a shell would, or None when it is empty or cannot be read."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    return words or None


def join_words(words: List[str]) -> str:
    """Join words back into one command string, quoting any that need it."""
    return " ".join(shlex.quote(word) for word in words)


def has_shell_syntax(text: str) -> bool:
    """Whether ``text`` contains anything a shell would treat as chaining, piping, redirecting, or substituting."""
    return bool(_SHELL_SYNTAX.search(text))


def wrapper_command_flag_index(words: List[str]) -> Optional[int]:
    """Index of a shell wrapper's command flag (-c, -lc, -ec), or None when the wrapper is not given a command string."""
    for index in range(1, len(words)):
        word = words[index]
        if word.startswith("-") and not word.startswith("--") and "c" in word[1:]:
            return index
        if not word.startswith("-"):
            return None
    return None


@dataclass(frozen=True)
class EffectiveCommand:
    """The words that would actually run, with the reason when they cannot be trusted to be only those words."""

    words: Optional[List[str]]
    chained: bool = False


def effective_command(command: str) -> EffectiveCommand:
    """Read the command as it will run: a plain command is its own words, and a ``bash -lc 'one command'`` wrapper is the words of its inner command.

    ``words`` is None when the command is empty, unreadable, a wrapper without exactly one command string, a wrapper around another wrapper, or an inner command that chains, pipes, redirects, or substitutes (``chained`` is True for that last case). Such a command can only be approved as itself, never through a remembered pattern.
    """
    words = split_words(command)
    if words is None:
        return EffectiveCommand(None)
    if not is_shell_wrapper(words[0]):
        return EffectiveCommand(words)
    flag_index = wrapper_command_flag_index(words)
    if flag_index is None:
        return EffectiveCommand(None)
    inner = words[flag_index + 1:]
    if len(inner) != 1:
        return EffectiveCommand(None)
    inner_text = inner[0]
    if has_shell_syntax(inner_text):
        return EffectiveCommand(None, chained=True)
    inner_words = split_words(inner_text)
    if inner_words is None or is_shell_wrapper(inner_words[0]):
        return EffectiveCommand(None)
    return EffectiveCommand(inner_words)


def pattern_words(pattern: str) -> Optional[List[str]]:
    """The words a stored pattern requires.

    Patterns saved by older versions may still carry the wrapper in front of the command (``bash -lc gh``); the wrapper is dropped so they compare against the inner command like every other pattern.
    """
    words = split_words(pattern)
    if words is None:
        return None
    if is_shell_wrapper(words[0]):
        flag_index = wrapper_command_flag_index(words)
        if flag_index is None:
            return None
        inner = words[flag_index + 1:]
        return inner or None
    return words
