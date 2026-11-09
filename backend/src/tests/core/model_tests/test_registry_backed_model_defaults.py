"""The single-model preference defaults come from registry flags, so a registry change moves the default and the flags must stay unambiguous."""

import pytest

from api.core.models.models_registry import get_local_reasoning_models, get_model
from api.core.models.models_registry.local_vision_registry import LOCAL_VISION_MODELS
from api.core.models.preference_models.defaults import (
    _get_default_local_reasoning_model_id,
    _get_default_local_vision_model_id,
)
from api.core.models.preference_models.migrations import RETIRED_LOCAL_MODEL_REPLACEMENTS
from api.core.models.preferences import Preferences
from api.routes.settings_routes.api_models.helpers import _get_local_default_for_capability


@pytest.fixture(autouse=True)
def roomy_machine(monkeypatch):
    """The flagged model is the default only on a machine with enough memory and not so much that the larger upgrade replaces it, so these tests pin one in between. The low-memory fallback and the high-memory upgrade are covered in test_onboarding_starter_hardware_gating.py."""
    monkeypatch.setattr("api.core.models.preference_models.defaults._detected_total_ram_gb", lambda: 32)


def _flagged_reasoning_ids():
    return [
        model_id
        for model_id, cfg in get_local_reasoning_models().items()
        if cfg.get("recommended_for_onboarding") is True and "reasoning" in cfg.get("capabilities", [])
    ]


def _flagged_vision_ids():
    return [model_id for model_id, cfg in LOCAL_VISION_MODELS.items() if cfg.get("default_local_vision_fallback") is True]


def test_exactly_one_local_reasoning_model_is_flagged_for_onboarding():
    assert len(_flagged_reasoning_ids()) == 1


def test_exactly_one_local_vision_model_is_flagged_as_the_default_fallback():
    assert len(_flagged_vision_ids()) == 1


def test_default_helpers_return_the_flagged_registry_ids():
    assert _get_default_local_reasoning_model_id() == _flagged_reasoning_ids()[0]
    assert _get_default_local_vision_model_id() == _flagged_vision_ids()[0]


def test_flagged_defaults_are_resolvable_and_never_retired():
    for model_id in (_get_default_local_reasoning_model_id(), _get_default_local_vision_model_id()):
        assert get_model(model_id) is not None, model_id
        assert model_id not in RETIRED_LOCAL_MODEL_REPLACEMENTS


def test_fresh_preferences_take_every_single_model_default_from_the_registry():
    preferences = Preferences()
    reasoning_default = _get_default_local_reasoning_model_id()

    assert preferences.models.reasoning_model == reasoning_default
    assert preferences.models.language_model == reasoning_default
    assert preferences.activity_capture.processing_model == reasoning_default
    assert preferences.models.local_vision_model_id == _get_default_local_vision_model_id()
    assert get_model(preferences.activity_capture.processing_model) is not None


def test_fallback_default_for_removed_models_is_registry_backed():
    assert _get_local_default_for_capability("reasoning") == _get_default_local_reasoning_model_id()
    assert get_model(_get_local_default_for_capability("reasoning")) is not None
    # The legacy vision_model preference defaults to empty; a retired Moondream id is never written back.
    assert _get_local_default_for_capability("vision") == ""
    assert Preferences().models.vision_model == ""
