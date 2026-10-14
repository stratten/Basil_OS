"""Pure helpers for standing watches: natural-language parsing, validation and timeline payloads."""

from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Dict, Optional, Tuple

from .gate import keywords_from_topic
from .models import CompanionWatch
from .similarity import normalize_text

MAX_ACTIVE_WATCHES = 8
MIN_TOPIC_CHARS = 3
MAX_TOPIC_CHARS = 120
MAX_INSTRUCTION_CHARS = 500

_WATCH_REQUEST = re.compile(
    r"^\s*(?:when|whenever|once|if)\s+(?P<topic>.+?)\s+"
    r"(?:comes?\s+up|(?:is|are|gets?)\s+(?:mentioned|discussed|brought\s+up))"
    r"\s*[,:;\-\u2013\u2014]?\s*(?P<instruction>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)


class WatchRejected(ValueError):
    """Raised with a user-facing reason when a watch cannot be created."""


def parse_watch_request(text: str) -> Optional[Tuple[str, str]]:
    """``(topic, instruction)`` for text like "when billing comes up, show me the endpoint"; otherwise ``None``."""
    match = _WATCH_REQUEST.match(text or "")
    if match is None:
        return None
    topic = normalize_text(match.group("topic"))
    instruction = normalize_text(match.group("instruction")).strip(" .,;:-\u2013\u2014")
    if not topic or not instruction:
        return None
    return topic, instruction


def default_watch_id() -> str:
    return f"w-{uuid.uuid4().hex[:8]}"


def build_watch_created_payload(
    topic: str,
    instruction: str,
    *,
    active_count: int,
    id_factory: Callable[[], str] = default_watch_id,
) -> Dict[str, Any]:
    """Validated payload for a ``watch`` timeline event with ``state == "created"``."""
    cleaned_topic = normalize_text(topic)
    cleaned_instruction = normalize_text(instruction)
    if len(cleaned_topic) < MIN_TOPIC_CHARS:
        raise WatchRejected("Describe the topic in a few words.")
    if len(cleaned_topic) > MAX_TOPIC_CHARS:
        raise WatchRejected(f"The topic can be at most {MAX_TOPIC_CHARS} characters.")
    if len(cleaned_instruction) > MAX_INSTRUCTION_CHARS:
        raise WatchRejected(f"The instruction can be at most {MAX_INSTRUCTION_CHARS} characters.")
    keywords = keywords_from_topic(cleaned_topic)
    if not keywords:
        raise WatchRejected("The topic needs at least one specific word.")
    if active_count >= MAX_ACTIVE_WATCHES:
        raise WatchRejected(f"You can have at most {MAX_ACTIVE_WATCHES} active watches. Cancel one first.")
    return {
        "watch_id": id_factory(),
        "state": "created",
        "topic": cleaned_topic,
        "instruction": cleaned_instruction or f"Show me what is relevant about {cleaned_topic}.",
        "keywords": keywords,
    }


def watch_event_payload(watch: CompanionWatch, state: str) -> Dict[str, Any]:
    """Payload for a ``triggered`` or ``canceled`` watch event."""
    return {
        "watch_id": watch.id,
        "state": state,
        "topic": watch.topic,
        "instruction": watch.instruction,
        "keywords": list(watch.keywords),
    }
