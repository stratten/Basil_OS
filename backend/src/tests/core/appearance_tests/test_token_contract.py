import math

import pytest

from api.core.appearance.token_contract import (
    AppearanceTokenContract,
    contrast_ratio,
    meets_minimum_contrast,
)


def test_contract_exposes_every_derived_and_fixed_token_name() -> None:
    contract = AppearanceTokenContract()

    assert contract.derived_surface_tokens == (
        "surfaceRaised", "surfaceSunken", "surfaceOverlay", "surfaceSelected", "surfaceHover", "surfaceDisabled",
    )
    assert contract.derived_text_tokens == (
        "textSecondary", "textTertiary", "textOnPrimary", "textOnSuccess", "textOnWarning", "textOnError",
    )
    assert contract.derived_structural_tokens == ("separator", "fieldBorder", "focusRing", "shadow")
    assert contract.fixed_semantic_state_tokens == (
        "recordingBase", "recordingAccent", "successBase", "warningBase", "errorBase", "processingBase",
        "processingAccent", "readyBase", "readyAccent",
    )


def test_contrast_ratio_uses_wcag_relative_luminance() -> None:
    assert contrast_ratio((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)) == pytest.approx(21.0)
    assert contrast_ratio((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)) == pytest.approx(1.0)


def test_minimum_contrast_distinguishes_normal_and_large_text() -> None:
    foreground = (0.50, 0.50, 0.50)
    background = (1.0, 1.0, 1.0)

    assert meets_minimum_contrast(foreground, background, "normal") is False
    assert meets_minimum_contrast(foreground, background, "large") is True


@pytest.mark.parametrize("color", [(-0.1, 0.0, 0.0), (1.1, 0.0, 0.0), (math.nan, 0.0, 0.0)])
def test_invalid_rgb_components_are_rejected(color: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        contrast_ratio(color, (1.0, 1.0, 1.0))
