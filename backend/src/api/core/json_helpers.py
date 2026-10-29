"""Small JSON helpers shared by the persistence layers.

``json_loads_or_empty`` is the lenient reader used when a missing or malformed JSON column should read as an empty mapping. ``load_json_array`` and ``load_json_object`` are the strict readers for required JSON columns: they raise the caller's own persistence error type so each repository keeps its own error contract. ``canonical_json`` is the stable text form used for fingerprints and idempotency comparisons.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def json_loads_or_empty(value: Optional[str]) -> Any:
    """Parse ``value`` as JSON, returning ``{}`` for empty input or any parse failure."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def canonical_json(value: object) -> str:
    """Return a stable, key-sorted, compact JSON text for ``value``."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json_array(raw: object, field_name: str, error_type: type[Exception]) -> list[object]:
    """Parse a required JSON array column, raising ``error_type`` when it is absent, invalid, or not an array."""
    if not isinstance(raw, str):
        raise error_type(f"{field_name} is missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise error_type(f"{field_name} contains invalid JSON") from exc
    if not isinstance(value, list):
        raise error_type(f"{field_name} must contain a JSON array")
    return value


def load_json_object(raw: object, field_name: str, error_type: type[Exception]) -> dict[str, object]:
    """Parse a required JSON object column, raising ``error_type`` when it is absent, invalid, or not an object."""
    if not isinstance(raw, str):
        raise error_type(f"{field_name} is missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise error_type(f"{field_name} contains invalid JSON") from exc
    if not isinstance(value, dict):
        raise error_type(f"{field_name} must contain a JSON object")
    return dict(value)
