"""Deterministic recognition of a chat message that asks for an investigation."""

from __future__ import annotations

import re
from typing import Optional

from .models import MAX_QUESTION_CHARS

_INVESTIGATE = re.compile(
    r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:investigate|research|look\s+into|dig\s+into|look\s+up|find\s+out)\s+"
    r"(?:whether\s+|if\s+|about\s+|on\s+)?(?P<question>\S.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_TRAILING = re.compile(r"\s*(?:for me|please|thanks|thank you)?[\s.!?]*$", re.IGNORECASE)
MIN_QUESTION_CHARS = 6


def normalize_question(text: str) -> str:
    """Collapse whitespace and cut to the question limit on a word boundary when possible."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= MAX_QUESTION_CHARS:
        return collapsed
    cut = collapsed[:MAX_QUESTION_CHARS]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > MAX_QUESTION_CHARS // 2 else cut).rstrip()


def parse_investigation_request(text: str) -> Optional[str]:
    """The question when ``text`` starts with an investigate verb and names something to look into; otherwise ``None``."""
    match = _INVESTIGATE.match(text or "")
    if match is None:
        return None
    question = normalize_question(_TRAILING.sub("", match.group("question")))
    if len(question) < MIN_QUESTION_CHARS:
        return None
    return question
