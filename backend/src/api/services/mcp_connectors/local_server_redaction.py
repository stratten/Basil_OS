"""Hides secret values from text that is about to be shown to the person or the agent.

A background program may print its own token or the one Basil gave it, and its output is kept in a log that error messages quote. Anything that quotes the log goes through here first.
"""

from __future__ import annotations

from typing import Iterable

HIDDEN = "[hidden]"
MIN_SECRET_LENGTH = 4
"""A shorter value would blank out ordinary words, so it is not treated as something to hide."""


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    """``text`` with every secret value replaced by a marker. Longer values are replaced first so one that contains another is hidden whole."""
    if not text:
        return text
    for secret in sorted({value for value in secrets if value and len(value) >= MIN_SECRET_LENGTH}, key=len, reverse=True):
        text = text.replace(secret, HIDDEN)
    return text
