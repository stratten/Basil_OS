"""Tests for the text_scale appearance preference."""

import json
import sys
import unittest
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.core.models.preference_models.ui_and_capture import (
    TEXT_SCALE_STEPS,
    UIPreferences,
    snap_text_scale,
)
from api.core.models.preferences import Preferences
from api.main import app

pytestmark = pytest.mark.use_temp_home

client = TestClient(app)

BASE_PAYLOAD = {
    "background_color_red": 1.0,
    "background_color_green": 1.0,
    "background_color_blue": 1.0,
    "preferred_font": "Helvetica-Light",
}


class TestSnapTextScale(unittest.TestCase):
    def test_every_offered_step_maps_to_itself(self) -> None:
        for step in TEXT_SCALE_STEPS:
            self.assertEqual(snap_text_scale(step), step)

    def test_values_between_steps_snap_to_the_nearest(self) -> None:
        self.assertEqual(snap_text_scale(0.96), 1.0)
        self.assertEqual(snap_text_scale(1.04), 1.0)
        self.assertEqual(snap_text_scale(1.12), 1.1)
        self.assertEqual(snap_text_scale(1.2), 1.25)
        self.assertEqual(snap_text_scale(1.33), 1.4)

    def test_values_outside_the_range_clamp_to_the_ends(self) -> None:
        self.assertEqual(snap_text_scale(0.1), 0.9)
        self.assertEqual(snap_text_scale(-3), 0.9)
        self.assertEqual(snap_text_scale(9), 1.4)

    def test_an_exact_tie_prefers_the_smaller_step(self) -> None:
        self.assertEqual(snap_text_scale(0.95), 0.9)

    def test_integers_are_accepted(self) -> None:
        self.assertEqual(snap_text_scale(1), 1.0)

    def test_anything_that_is_not_a_finite_number_means_one(self) -> None:
        for value in (None, "1.25", True, float("nan"), float("inf"), float("-inf"), [1.4], {}):
            self.assertEqual(snap_text_scale(value), 1.0, msg=repr(value))


class TestUIPreferencesTextScale(unittest.TestCase):
    def test_default_is_one(self) -> None:
        self.assertEqual(UIPreferences().text_scale, 1.0)

    def test_a_stored_off_step_value_is_snapped_when_loaded(self) -> None:
        self.assertEqual(UIPreferences(text_scale=1.3).text_scale, 1.25)

    def test_a_stored_garbage_value_loads_as_one(self) -> None:
        self.assertEqual(UIPreferences(text_scale="large").text_scale, 1.0)

    def test_existing_preferences_without_the_key_load_with_the_default(self) -> None:
        dumped = UIPreferences().model_dump()
        del dumped["text_scale"]
        self.assertEqual(UIPreferences(**dumped).text_scale, 1.0)


class TestAppearanceTextScaleRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self._original_preferences = Preferences.load()

    def tearDown(self) -> None:
        self._original_preferences.save()

    def test_get_defaults_to_one(self) -> None:
        response = client.get("/settings/appearance")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["text_scale"], 1.0)

    def test_put_persists_a_step_and_returns_it(self) -> None:
        put_response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "text_scale": 1.25})

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(put_response.json()["updated_settings"]["text_scale"], 1.25)
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["text_scale"], 1.25)

    def test_put_snaps_an_off_step_value_before_saving(self) -> None:
        put_response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "text_scale": 1.33})

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(put_response.json()["updated_settings"]["text_scale"], 1.4)
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["text_scale"], 1.4)

    def test_put_clamps_extreme_values(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "text_scale": 50})
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["text_scale"], 1.4)
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "text_scale": 0})
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["text_scale"], 0.9)

    def test_put_without_the_field_means_one(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "text_scale": 1.4})
        put_response = client.put("/settings/appearance", json=BASE_PAYLOAD)

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["text_scale"], 1.0)

    def test_put_with_a_non_numeric_value_means_one(self) -> None:
        put_response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "text_scale": "huge"})

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["text_scale"], 1.0)

    def test_put_leaves_the_other_appearance_choices_alone(self) -> None:
        client.put(
            "/settings/appearance",
            json={**BASE_PAYLOAD, "blueprint_reveal": True, "agent_task_chain_expansion": "multiple", "text_scale": 0.9},
        )

        settings = client.get("/settings/appearance").json()["settings"]
        self.assertIs(settings["blueprint_reveal"], True)
        self.assertEqual(settings["agent_task_chain_expansion"], "multiple")
        self.assertEqual(settings["text_scale"], 0.9)

    def test_the_value_survives_a_reload_from_the_saved_preferences_file(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "text_scale": 1.1})

        self.assertEqual(Preferences.load().ui.text_scale, 1.1)
        self.assertEqual(json.loads(Preferences.load().model_dump_json())["ui"]["text_scale"], 1.1)
