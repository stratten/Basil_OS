from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal, Tuple

AppearanceRgbColor = Tuple[float, float, float]
AppearanceContrastTextSize = Literal["normal", "large"]

DERIVED_SURFACE_TOKENS: Final = (
    "surfaceRaised",
    "surfaceSunken",
    "surfaceOverlay",
    "surfaceSelected",
    "surfaceHover",
    "surfaceDisabled",
)
DERIVED_TEXT_TOKENS: Final = (
    "textSecondary",
    "textTertiary",
    "textOnPrimary",
    "textOnSuccess",
    "textOnWarning",
    "textOnError",
)
DERIVED_STRUCTURAL_TOKENS: Final = ("separator", "fieldBorder", "focusRing", "shadow")
FIXED_SEMANTIC_STATE_TOKENS: Final = (
    "recordingBase",
    "recordingAccent",
    "successBase",
    "warningBase",
    "errorBase",
    "processingBase",
    "processingAccent",
    "readyBase",
    "readyAccent",
)


@dataclass(frozen=True)
class AppearanceTokenContract:
    derived_surface_tokens: Tuple[str, ...] = DERIVED_SURFACE_TOKENS
    derived_text_tokens: Tuple[str, ...] = DERIVED_TEXT_TOKENS
    derived_structural_tokens: Tuple[str, ...] = DERIVED_STRUCTURAL_TOKENS
    fixed_semantic_state_tokens: Tuple[str, ...] = FIXED_SEMANTIC_STATE_TOKENS


def contrast_ratio(foreground: AppearanceRgbColor, background: AppearanceRgbColor) -> float:
    foreground_luminance = relative_luminance(foreground)
    background_luminance = relative_luminance(background)
    lighter, darker = sorted((foreground_luminance, background_luminance), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def meets_minimum_contrast(
    foreground: AppearanceRgbColor,
    background: AppearanceRgbColor,
    text_size: AppearanceContrastTextSize = "normal",
) -> bool:
    required_ratio = 3.0 if text_size == "large" else 4.5
    return contrast_ratio(foreground, background) >= required_ratio


def relative_luminance(color: AppearanceRgbColor) -> float:
    red, green, blue = _validate_rgb_color(color)
    return (0.2126 * _linearize_srgb(red)) + (0.7152 * _linearize_srgb(green)) + (0.0722 * _linearize_srgb(blue))


def _linearize_srgb(component: float) -> float:
    return component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4


def _validate_rgb_color(color: AppearanceRgbColor) -> AppearanceRgbColor:
    if len(color) != 3:
        raise ValueError("Appearance colors must contain exactly three RGB components.")
    if not all(math.isfinite(component) and 0.0 <= component <= 1.0 for component in color):
        raise ValueError("Appearance RGB components must be finite values from 0.0 through 1.0.")
    return color
