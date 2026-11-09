"""Hex color parsing and formatting for agent-driven appearance changes. Contrast math lives in `api.core.appearance.token_contract`."""

from __future__ import annotations

import re
from typing import Any, List, Sequence

_HEX_PATTERN = re.compile(r"#?([0-9a-fA-F]{6})")


def parse_hex_color(value: Any) -> List[float]:
    """Turn "#RRGGBB" (the # is optional) into [red, green, blue], each 0.0 to 1.0."""
    if not isinstance(value, str):
        raise ValueError("A color must be a hex string such as #FF69B4.")
    match = _HEX_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"'{value}' is not a six-digit hex color such as #FF69B4.")
    digits = match.group(1)
    return [int(digits[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]


def format_hex_color(rgb: Sequence[float]) -> str:
    """Turn [red, green, blue] (each 0.0 to 1.0) into an uppercase "#RRGGBB" string."""
    channels = [max(0, min(255, int(round(float(channel) * 255.0)))) for channel in rgb]
    return "#{:02X}{:02X}{:02X}".format(*channels)
