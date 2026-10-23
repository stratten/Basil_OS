"""Strict JSON conversion and privacy-safe projections for work-ledger data."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Mapping


class LedgerJSONNormalizationError(TypeError):
    """Raised when a ledger value cannot be safely represented as JSON."""


_EMAIL_BODY_FIELDS = frozenset({"body", "content", "html_body", "text", "raw"})
_EMAIL_METADATA_FIELDS = (
    "id",
    "subject",
    "sender",
    "recipient",
    "date_sent",
    "is_read",
    "is_flagged",
    "folder",
    "message_id",
    "thread_id",
)


def to_ledger_json_value(value: Any) -> Any:
    """Convert supported values recursively without stringifying unknown objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_ledger_json_value(value.value)
    if hasattr(value, "model_dump"):
        return to_ledger_json_value(value.model_dump(mode="json"))
    if is_dataclass(value):
        return to_ledger_json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_ledger_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_ledger_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [to_ledger_json_value(item) for item in value]
        return sorted(normalized, key=lambda item: repr(item))
    raise LedgerJSONNormalizationError(
        f"Unsupported ledger JSON value: {type(value).__name__}"
    )


def to_ledger_json_object(value: Any) -> dict[str, Any]:
    """Convert a value and require an object for JSON object columns."""
    normalized = to_ledger_json_value(value)
    if not isinstance(normalized, dict):
        raise LedgerJSONNormalizationError("Ledger JSON object value must be a mapping.")
    return normalized


def sanitize_ledger_email_record(value: Any) -> dict[str, Any]:
    """Return compact email metadata, excluding bodies and attachment payloads."""
    normalized = to_ledger_json_value(value)
    if not isinstance(normalized, dict):
        raise LedgerJSONNormalizationError("Email record must normalize to a mapping.")
    compact = {
        field: normalized[field]
        for field in _EMAIL_METADATA_FIELDS
        if field in normalized
    }
    compact.update(
        {
            key: item
            for key, item in normalized.items()
            if key not in _EMAIL_BODY_FIELDS
            and key != "attachments"
            and key not in compact
        }
    )
    return compact


def sanitize_ledger_email_list(value: Any) -> dict[str, Any]:
    """Project an EmailDataList into body-free invocation evidence."""
    coverage = getattr(value, "coverage_metadata", None)
    if coverage is None:
        raise LedgerJSONNormalizationError("Email list has no coverage metadata.")
    return {
        "coverage_metadata": to_ledger_json_object(coverage),
        "items": [sanitize_ledger_email_record(email) for email in value],
    }
