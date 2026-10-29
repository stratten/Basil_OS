"""Normalization helpers for automatic activity-capture app exclusions."""

from __future__ import annotations


def normalize_excluded_bundle_ids(bundle_ids: list[str] | None) -> list[str]:
    """Trim and dedupe automatic activity-capture exclusions case-insensitively."""
    normalized: list[str] = []
    seen: set[str] = set()

    for raw in bundle_ids or []:
        trimmed = raw.strip()
        if not trimmed:
            continue
        key = trimmed.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(trimmed)

    return normalized
