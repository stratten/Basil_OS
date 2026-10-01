"""Persisted shapes for direct-conversation exchange summaries and the running brief."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Optional, Sequence, Tuple

TURN_SUMMARY_METADATA_KEY = "turn_summary"
CONVERSATION_BRIEF_METADATA_KEY = "conversation_brief"
SUMMARY_FORMAT_VERSION = 1
MAX_TURN_SUMMARY_ATTEMPTS = 3


class TurnSummaryStatus(StrEnum):
    """Outcome of the latest summary attempt for one exchange."""

    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class TurnSummaryRecord:
    """Summary stored on the last assistant message of one exchange."""

    status: TurnSummaryStatus
    text: Optional[str]
    source_fingerprint: str
    model_id: Optional[str]
    attempt_count: int
    version: int = SUMMARY_FORMAT_VERSION

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "text": self.text,
            "source_fingerprint": self.source_fingerprint,
            "model_id": self.model_id,
            "attempt_count": self.attempt_count,
            "version": self.version,
        }


@dataclass(frozen=True)
class ConversationBriefRecord:
    """Running brief stored in conversation metadata, covering an ordered prefix of exchange summaries."""

    text: str
    covered_anchor_ids: Tuple[str, ...]
    covered_fingerprint: str
    model_id: Optional[str]
    version: int = SUMMARY_FORMAT_VERSION

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "covered_anchor_ids": list(self.covered_anchor_ids),
            "covered_fingerprint": self.covered_fingerprint,
            "model_id": self.model_id,
            "version": self.version,
        }


def exchange_fingerprint(user_text: str, assistant_text: str) -> str:
    """Identify the exact exchange text a summary was written from."""
    digest = hashlib.sha256()
    digest.update(f"basil-exchange-summary-v{SUMMARY_FORMAT_VERSION}".encode("utf-8"))
    digest.update(b"\x00")
    digest.update(user_text.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(assistant_text.encode("utf-8"))
    return digest.hexdigest()


def coverage_fingerprint(entries: Sequence[Tuple[str, str]]) -> str:
    """Identify the ordered (anchor id, exchange fingerprint) pairs a brief was written from."""
    digest = hashlib.sha256()
    digest.update(f"basil-conversation-brief-v{SUMMARY_FORMAT_VERSION}".encode("utf-8"))
    for anchor_id, source_fingerprint in entries:
        digest.update(b"\x00")
        digest.update(anchor_id.encode("utf-8"))
        digest.update(b"\x01")
        digest.update(source_fingerprint.encode("utf-8"))
    return digest.hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value
    return None


def parse_turn_summary(metadata: Any) -> Optional[TurnSummaryRecord]:
    """Read a stored exchange summary, returning None for absent or malformed records."""
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get(TURN_SUMMARY_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        status = TurnSummaryStatus(raw.get("status"))
    except (TypeError, ValueError):
        return None
    source_fingerprint = _non_empty_string(raw.get("source_fingerprint"))
    version = raw.get("version")
    attempt_count = raw.get("attempt_count")
    if source_fingerprint is None or not _is_int(version) or not _is_int(attempt_count) or attempt_count < 0:
        return None
    text = _non_empty_string(raw.get("text"))
    if status == TurnSummaryStatus.COMPLETED and text is None:
        return None
    return TurnSummaryRecord(
        status=status,
        text=text if status == TurnSummaryStatus.COMPLETED else None,
        source_fingerprint=source_fingerprint,
        model_id=_non_empty_string(raw.get("model_id")),
        attempt_count=attempt_count,
        version=version,
    )


def parse_conversation_brief(metadata: Any) -> Optional[ConversationBriefRecord]:
    """Read the stored conversation brief, returning None for absent or malformed records."""
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get(CONVERSATION_BRIEF_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    text = _non_empty_string(raw.get("text"))
    covered_fingerprint = _non_empty_string(raw.get("covered_fingerprint"))
    version = raw.get("version")
    raw_anchor_ids = raw.get("covered_anchor_ids")
    if text is None or covered_fingerprint is None or not _is_int(version):
        return None
    if not isinstance(raw_anchor_ids, list) or not raw_anchor_ids:
        return None
    if not all(_non_empty_string(anchor_id) for anchor_id in raw_anchor_ids):
        return None
    return ConversationBriefRecord(
        text=text,
        covered_anchor_ids=tuple(raw_anchor_ids),
        covered_fingerprint=covered_fingerprint,
        model_id=_non_empty_string(raw.get("model_id")),
        version=version,
    )
